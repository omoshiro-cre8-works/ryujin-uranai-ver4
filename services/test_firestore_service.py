from datetime import datetime, timedelta, timezone

import pytest

from services import firestore_service


class FakeSnapshot:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeDocument:
    def __init__(self, record=None):
        self.payload = None
        self.record = record
        self.read_transaction = None

    def set(self, payload):
        self.payload = dict(payload)

    def get(self, transaction=None):
        self.read_transaction = transaction
        return FakeTransactionSnapshot(self.record)


class FakeTransactionSnapshot(FakeSnapshot):
    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data or {})


class FakeTransaction:
    def __init__(self):
        self.updates = []

    def update(self, doc_ref, updates):
        self.updates.append((doc_ref, dict(updates)))


class FakeQuery:
    def __init__(self, records):
        self.records = records
        self.field = None
        self.value = None

    def where(self, field, operator, value):
        assert operator == "=="
        self.field = field
        self.value = value
        return self

    def limit(self, count):
        assert count == 1
        return self

    def stream(self):
        matches = [
            record
            for record in self.records
            if record.get(self.field) == self.value
        ]
        return [FakeSnapshot(record) for record in matches[:1]]


class FakeCollection:
    def __init__(self, records=None):
        self.records = records or []
        record = self.records[0] if self.records else None
        self.document_ref = FakeDocument(record)

    def document(self, purchase_id):
        return self.document_ref

    def where(self, field, operator, value):
        return FakeQuery(self.records).where(field, operator, value)


class FakeFirestoreClient:
    def __init__(self, records=None):
        self.collection_ref = FakeCollection(records)
        self.transaction_ref = FakeTransaction()

    def collection(self, name):
        assert name == firestore_service.COLLECTION_NAME
        return self.collection_ref

    def transaction(self):
        return self.transaction_ref


def test_create_purchase_record_saves_hash_without_plaintext_token(monkeypatch):
    client = FakeFirestoreClient()
    monkeypatch.setattr(firestore_service, "get_firestore_client", lambda: client)

    token = "secret-access-token"
    firestore_service.create_purchase_record(
        purchase_id="p_1",
        stripe_checkout_session_id="cs_1",
        access_token=token,
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    payload = client.collection_ref.document_ref.payload
    assert payload["access_token_hash"] == firestore_service.hash_access_token(token)
    assert "access_token" not in payload
    assert token not in payload.values()


def test_get_purchase_by_access_token_matches_hash(monkeypatch):
    token = "correct-token"
    record = {
        "purchase_id": "p_hash",
        "access_token_hash": firestore_service.hash_access_token(token),
    }
    monkeypatch.setattr(
        firestore_service,
        "get_firestore_client",
        lambda: FakeFirestoreClient([record]),
    )

    assert firestore_service.get_purchase_by_access_token(token) == record


def test_get_purchase_by_access_token_rejects_wrong_token(monkeypatch):
    record = {
        "purchase_id": "p_hash",
        "access_token_hash": firestore_service.hash_access_token("correct-token"),
    }
    monkeypatch.setattr(
        firestore_service,
        "get_firestore_client",
        lambda: FakeFirestoreClient([record]),
    )

    assert firestore_service.get_purchase_by_access_token("wrong-token") is None


def test_get_purchase_by_access_token_supports_legacy_plaintext_record(monkeypatch):
    token = "legacy-token"
    record = {
        "purchase_id": "p_legacy",
        "access_token": token,
    }
    monkeypatch.setattr(
        firestore_service,
        "get_firestore_client",
        lambda: FakeFirestoreClient([record]),
    )

    result = firestore_service.get_purchase_by_access_token(token)
    assert result["purchase_id"] == "p_legacy"
    assert "access_token" not in result


def _consume_record(**updates):
    token = "transaction-token"
    record = {
        "purchase_id": "p_transaction",
        "payment_status": "paid",
        "used_flag": False,
        "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "access_token_hash": firestore_service.hash_access_token(token),
    }
    record.update(updates)
    return token, record


def _run_consume(monkeypatch, record, token):
    client = FakeFirestoreClient([record])
    monkeypatch.setattr(firestore_service, "get_firestore_client", lambda: client)
    monkeypatch.setattr(firestore_service.firestore, "transactional", lambda func: func)
    consumed = firestore_service.consume_purchase_transaction("p_transaction", token)
    return consumed, client


def test_consume_purchase_transaction_updates_valid_hash_record(monkeypatch):
    token, record = _consume_record()

    consumed, client = _run_consume(monkeypatch, record, token)

    assert consumed is True
    assert client.collection_ref.document_ref.read_transaction is client.transaction_ref
    assert len(client.transaction_ref.updates) == 1
    updates = client.transaction_ref.updates[0][1]
    assert updates["used_flag"] is True
    assert updates["used_at"] == updates["updated_at"]


@pytest.mark.parametrize(
    "record_updates",
    [
        {"used_flag": True},
        {"used_flag": None},
        {"payment_status": "pending"},
        {"token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ],
)
def test_consume_purchase_transaction_does_not_update_invalid_record(
    monkeypatch,
    record_updates,
):
    token, record = _consume_record(**record_updates)

    consumed, client = _run_consume(monkeypatch, record, token)

    assert consumed is False
    assert client.transaction_ref.updates == []


def test_consume_purchase_transaction_rejects_wrong_token(monkeypatch):
    _, record = _consume_record()

    consumed, client = _run_consume(monkeypatch, record, "wrong-token")

    assert consumed is False
    assert client.transaction_ref.updates == []


def test_consume_purchase_transaction_supports_legacy_token(monkeypatch):
    token, record = _consume_record()
    record.pop("access_token_hash")
    record["access_token"] = token

    consumed, client = _run_consume(monkeypatch, record, token)

    assert consumed is True
    assert len(client.transaction_ref.updates) == 1


@pytest.mark.parametrize(
    ("record_updates", "expected"),
    [
        ({}, True),
        ({"payment_status": "pending"}, False),
        ({"used_flag": True}, False),
        ({"token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}, False),
    ],
)
def test_is_purchase_usable_preserves_existing_guards(monkeypatch, record_updates, expected):
    record = {
        "payment_status": "paid",
        "used_flag": False,
        "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    record.update(record_updates)
    monkeypatch.setattr(
        firestore_service,
        "get_purchase_by_access_token",
        lambda access_token: record,
    )

    assert firestore_service.is_purchase_usable("token") is expected


def test_create_purchase_record_saves_tracking_params_without_private_fields(monkeypatch):
    client = FakeFirestoreClient()
    monkeypatch.setattr(firestore_service, "get_firestore_client", lambda: client)

    token = "secret-access-token"
    firestore_service.create_purchase_record(
        purchase_id="p_tracking",
        stripe_checkout_session_id="cs_tracking",
        access_token=token,
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        product_type="review",
        tracking_params={
            "service_id": "ryujin",
            "utm_source": "instagram",
            "utm_medium": "paid_social",
            "utm_campaign": "summer",
            "utm_content": "hero",
            "test_mode": "owner",
            "button_position": "top",
            "user_name": "should-not-save",
            "birth_date": "should-not-save",
            "email": "should-not-save",
            "pdf_body": "should-not-save",
        },
    )

    payload = client.collection_ref.document_ref.payload
    assert payload["product_type"] == "review"
    assert payload["service_id"] == "ryujin"
    assert payload["utm_source"] == "instagram"
    assert payload["utm_medium"] == "paid_social"
    assert payload["utm_campaign"] == "summer"
    assert payload["utm_content"] == "hero"
    assert payload["test_mode"] == "owner"
    assert payload["button_position"] == "top"
    assert "user_name" not in payload
    assert "birth_date" not in payload
    assert "email" not in payload
    assert "pdf_body" not in payload


def test_legacy_purchase_records_can_be_read_without_tracking_fields(monkeypatch):
    record = {
        "purchase_id": "p_legacy",
        "payment_status": "paid",
        "used_flag": False,
        "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    monkeypatch.setattr(
        firestore_service,
        "get_purchase_by_access_token",
        lambda access_token: record,
    )

    assert firestore_service.is_purchase_usable("legacy-token") is True
