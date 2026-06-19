from datetime import datetime, timedelta, timezone

import pytest

from services import firestore_service


class FakeSnapshot:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeDocument:
    def __init__(self):
        self.payload = None

    def set(self, payload):
        self.payload = dict(payload)


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
        self.document_ref = FakeDocument()

    def document(self, purchase_id):
        return self.document_ref

    def where(self, field, operator, value):
        return FakeQuery(self.records).where(field, operator, value)


class FakeFirestoreClient:
    def __init__(self, records=None):
        self.collection_ref = FakeCollection(records)

    def collection(self, name):
        assert name == firestore_service.COLLECTION_NAME
        return self.collection_ref


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
