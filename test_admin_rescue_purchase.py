import argparse
import io
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from scripts import admin_rescue_purchase
from services import firestore_service


NOW = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
OLD_TOKEN = "old-token-for-test"
NEW_TOKEN = "new-token-for-test"
PRODUCTION_TARGET_ENV = {
    "APP_ENV": "production",
    "FIRESTORE_PROJECT_ID": admin_rescue_purchase.PRODUCTION_PROJECT_ID,
    "FIRESTORE_DATABASE_ID": admin_rescue_purchase.PRODUCTION_DATABASE_ID,
    "FIRESTORE_PURCHASES_COLLECTION": admin_rescue_purchase.PRODUCTION_COLLECTION,
    "APP_BASE_URL": admin_rescue_purchase.PRODUCTION_APP_ORIGIN,
    "ADMIN_RESCUE_CANONICAL_APP_ORIGIN": admin_rescue_purchase.PRODUCTION_APP_ORIGIN,
}
STAGING_TARGET_ENV = {
    "APP_ENV": "staging",
    "FIRESTORE_PROJECT_ID": admin_rescue_purchase.STAGING_PROJECT_ID,
    "FIRESTORE_DATABASE_ID": admin_rescue_purchase.STAGING_DATABASE_ID,
    "FIRESTORE_PURCHASES_COLLECTION": admin_rescue_purchase.STAGING_COLLECTION,
    "APP_BASE_URL": admin_rescue_purchase.STAGING_APP_ORIGIN,
    "ADMIN_RESCUE_CANONICAL_APP_ORIGIN": admin_rescue_purchase.STAGING_APP_ORIGIN,
}


@pytest.fixture(autouse=True)
def clear_rescue_target_environment(monkeypatch):
    for key in admin_rescue_purchase.REQUIRED_TARGET_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def set_target_environment(monkeypatch, values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def make_purchase(**updates):
    purchase = {
        "purchase_id": "p_test_rescue",
        "payment_status": "paid",
        "used_flag": False,
        "generation_processing": False,
        "checkout_completed_at": NOW - timedelta(days=1),
        "token_expires_at": NOW + timedelta(days=6),
        "product_type": "regular",
        "access_token_hash": firestore_service.hash_access_token(OLD_TOKEN),
        "stripe_event_id": "evt_test_placeholder",
        "pdf_status": None,
    }
    purchase.update(updates)
    return purchase


class FakeSnapshot:
    def __init__(self, record):
        self.record = record

    @property
    def exists(self):
        return self.record is not None

    def to_dict(self):
        return dict(self.record or {})


class FakeDocument:
    def __init__(self, record):
        self.record = record
        self.read_transaction = None

    def get(self, transaction=None):
        self.read_transaction = transaction
        return FakeSnapshot(self.record)


class FakeTransaction:
    def __init__(self):
        self.updates = []

    def update(self, document, updates):
        self.updates.append(dict(updates))
        for key, value in updates.items():
            if value is firestore_service.firestore.DELETE_FIELD:
                document.record.pop(key, None)
            else:
                document.record[key] = value


class FakeQuery:
    def __init__(self, record, field=None, value=None):
        self.record = record
        self.field = field
        self.value = value

    def where(self, field, operator, value):
        assert operator == "=="
        return FakeQuery(self.record, field, value)

    def limit(self, count):
        assert count == 1
        return self

    def stream(self):
        if self.record and self.record.get(self.field) == self.value:
            return [FakeSnapshot(self.record)]
        return []


class FakeCollection:
    def __init__(self, record):
        self.document_ref = FakeDocument(record)

    def document(self, purchase_id):
        assert purchase_id == "p_test_rescue"
        return self.document_ref

    def where(self, field, operator, value):
        return FakeQuery(self.document_ref.record).where(field, operator, value)


class FakeFirestoreClient:
    def __init__(self, record):
        self.collection_ref = FakeCollection(record)
        self.transaction_ref = FakeTransaction()

    def collection(self, name):
        assert name == firestore_service.get_firestore_collection_name()
        return self.collection_ref

    def transaction(self):
        return self.transaction_ref


class TrackingTransport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class TrackingClient:
    def __init__(self):
        self.closed = False
        self._transport = TrackingTransport()

    def close(self):
        self.closed = True


def install_fake_firestore(monkeypatch, record):
    client = FakeFirestoreClient(record)
    monkeypatch.setattr(firestore_service, "get_firestore_client", lambda: client)
    monkeypatch.setattr(firestore_service.firestore, "transactional", lambda func: func)
    return client


def test_paid_unused_idle_purchase_within_window_is_eligible():
    assert (
        firestore_service.get_purchase_token_rescue_status(make_purchase(), now=NOW)
        == firestore_service.TOKEN_RESCUE_ELIGIBLE
    )


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"payment_status": "pending"}, firestore_service.TOKEN_RESCUE_NOT_PAID),
        ({"used_flag": True}, firestore_service.TOKEN_RESCUE_USED),
        ({"generation_processing": True}, firestore_service.TOKEN_RESCUE_PROCESSING),
        ({"checkout_completed_at": None}, firestore_service.TOKEN_RESCUE_MISSING_CHECKOUT_COMPLETED_AT),
        (
            {"checkout_completed_at": NOW - timedelta(days=7, seconds=1)},
            firestore_service.TOKEN_RESCUE_EXPIRED,
        ),
        ({"product_type": "unknown"}, firestore_service.TOKEN_RESCUE_UNSUPPORTED_PRODUCT),
        ({"pdf_status": "ready"}, firestore_service.TOKEN_RESCUE_PDF_GENERATED),
        ({"pdf_generated_at": NOW}, firestore_service.TOKEN_RESCUE_PDF_GENERATED),
    ],
)
def test_ineligible_purchase_is_rejected(updates, expected):
    assert firestore_service.get_purchase_token_rescue_status(
        make_purchase(**updates),
        now=NOW,
    ) == expected


def test_window_check_is_independent_from_other_rescue_conditions():
    purchase = make_purchase(payment_status="pending")

    assert firestore_service.is_purchase_token_rescue_window_active(purchase, now=NOW) is True
    assert (
        firestore_service.get_purchase_token_rescue_status(purchase, now=NOW)
        == firestore_service.TOKEN_RESCUE_NOT_PAID
    )


def test_reissue_saves_only_hash_and_invalidates_old_token(monkeypatch):
    record = make_purchase()
    before = dict(record)
    client = install_fake_firestore(monkeypatch, record)
    monkeypatch.setattr(firestore_service, "_now_utc", lambda: NOW)

    status = firestore_service.reissue_purchase_access_token_transaction(
        "p_test_rescue",
        NEW_TOKEN,
    )

    assert status == firestore_service.TOKEN_RESCUE_ELIGIBLE
    assert client.collection_ref.document_ref.read_transaction is client.transaction_ref
    assert len(client.transaction_ref.updates) == 1
    updates = client.transaction_ref.updates[0]
    assert set(updates) == {"access_token_hash", "updated_at"}
    assert updates["access_token_hash"] == firestore_service.hash_access_token(NEW_TOKEN)
    assert "access_token" not in record
    assert NEW_TOKEN not in record.values()
    assert firestore_service.get_purchase_by_access_token(NEW_TOKEN) is not None
    assert firestore_service.get_purchase_by_access_token(OLD_TOKEN) is None

    unchanged_fields = {
        "used_flag",
        "generation_processing",
        "payment_status",
        "token_expires_at",
        "stripe_event_id",
        "pdf_status",
    }
    assert {field: record[field] for field in unchanged_fields} == {
        field: before[field] for field in unchanged_fields
    }


def test_reissue_removes_legacy_plaintext_token(monkeypatch):
    record = make_purchase(access_token=OLD_TOKEN)
    client = install_fake_firestore(monkeypatch, record)
    monkeypatch.setattr(firestore_service, "_now_utc", lambda: NOW)

    status = firestore_service.reissue_purchase_access_token_transaction(
        "p_test_rescue",
        NEW_TOKEN,
    )

    assert status == firestore_service.TOKEN_RESCUE_ELIGIBLE
    assert client.transaction_ref.updates[0]["access_token"] is firestore_service.firestore.DELETE_FIELD
    assert "access_token" not in record
    assert firestore_service.get_purchase_by_access_token(OLD_TOKEN) is None


def test_reissue_rechecks_eligibility_without_writing(monkeypatch):
    record = make_purchase(generation_processing=True)
    client = install_fake_firestore(monkeypatch, record)

    status = firestore_service.reissue_purchase_access_token_transaction(
        "p_test_rescue",
        NEW_TOKEN,
    )

    assert status == firestore_service.TOKEN_RESCUE_PROCESSING
    assert client.transaction_ref.updates == []


def make_args(
    *,
    apply=False,
    confirm_purchase_id=None,
    confirm_target=None,
    copy_url_to_clipboard=False,
):
    return argparse.Namespace(
        purchase_id="p_test_rescue",
        apply=apply,
        confirm_purchase_id=confirm_purchase_id,
        confirm_target=confirm_target,
        copy_url_to_clipboard=copy_url_to_clipboard,
    )


@pytest.mark.parametrize(
    "missing_key",
    [
        "APP_ENV",
        "FIRESTORE_PROJECT_ID",
        "FIRESTORE_DATABASE_ID",
        "FIRESTORE_PURCHASES_COLLECTION",
        "APP_BASE_URL",
        "ADMIN_RESCUE_CANONICAL_APP_ORIGIN",
    ],
)
def test_missing_required_target_value_is_rejected_before_client_creation(monkeypatch, missing_key):
    values = dict(PRODUCTION_TARGET_ENV)
    values[missing_key] = ""
    set_target_environment(monkeypatch, values)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda target: pytest.fail("must reject before Firestore client creation"),
    )

    exit_code = admin_rescue_purchase.run(
        make_args(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("APP_ENV", "local"),
        ("FIRESTORE_PROJECT_ID", "INVALID PROJECT"),
        ("FIRESTORE_DATABASE_ID", "invalid/database"),
        ("FIRESTORE_PURCHASES_COLLECTION", "invalid/collection"),
    ],
)
def test_invalid_target_value_is_rejected(field, value):
    values = dict(STAGING_TARGET_ENV, **{field: value})

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError):
        admin_rescue_purchase.load_rescue_target(values)


@pytest.mark.parametrize(
    "app_base_url",
    [
        "http://staging.example",
        "https://staging.example?mode=test",
        "https://staging.example#resume",
        "https://staging.example?",
        "https://staging.example#",
    ],
)
def test_invalid_app_base_url_is_rejected(app_base_url):
    values = dict(STAGING_TARGET_ENV, APP_BASE_URL=app_base_url)

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError):
        admin_rescue_purchase.load_rescue_target(values)


def test_staging_environment_rejects_production_origin():
    values = dict(
        STAGING_TARGET_ENV,
        APP_BASE_URL=admin_rescue_purchase.PRODUCTION_APP_ORIGIN,
        ADMIN_RESCUE_CANONICAL_APP_ORIGIN=admin_rescue_purchase.PRODUCTION_APP_ORIGIN,
    )

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError):
        admin_rescue_purchase.load_rescue_target(values)


def test_production_environment_rejects_staging_origin():
    values = dict(
        PRODUCTION_TARGET_ENV,
        APP_BASE_URL=admin_rescue_purchase.STAGING_APP_ORIGIN,
        ADMIN_RESCUE_CANONICAL_APP_ORIGIN=admin_rescue_purchase.STAGING_APP_ORIGIN,
    )

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError):
        admin_rescue_purchase.load_rescue_target(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("FIRESTORE_PROJECT_ID", "other-staging-project-456"),
        ("FIRESTORE_DATABASE_ID", "other-staging"),
        ("FIRESTORE_PURCHASES_COLLECTION", "other_purchases"),
    ],
)
def test_staging_environment_rejects_noncanonical_firestore_target(field, value):
    values = dict(STAGING_TARGET_ENV, **{field: value})

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError, match="staging_target_mismatch"):
        admin_rescue_purchase.load_rescue_target(values)


def test_staging_environment_rejects_noncanonical_app_origin():
    values = dict(
        STAGING_TARGET_ENV,
        APP_BASE_URL="https://other-staging.example",
        ADMIN_RESCUE_CANONICAL_APP_ORIGIN="https://other-staging.example",
    )

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError, match="staging_target_mismatch"):
        admin_rescue_purchase.load_rescue_target(values)


def test_staging_environment_rejects_noncanonical_canonical_origin():
    values = dict(
        STAGING_TARGET_ENV,
        ADMIN_RESCUE_CANONICAL_APP_ORIGIN="https://other-staging.example",
    )

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError, match="app_origin_mismatch"):
        admin_rescue_purchase.load_rescue_target(values)


def test_production_environment_rejects_staging_tuple():
    values = dict(STAGING_TARGET_ENV, APP_ENV="production")

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError, match="production_target_mismatch"):
        admin_rescue_purchase.load_rescue_target(values)


def test_staging_environment_rejects_production_tuple():
    values = dict(PRODUCTION_TARGET_ENV, APP_ENV="staging")

    with pytest.raises(admin_rescue_purchase.RescueTargetConfigError, match="staging_target_mismatch"):
        admin_rescue_purchase.load_rescue_target(values)


def test_valid_production_target_passes_validation_without_firestore_connection(monkeypatch):
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda target: pytest.fail("validation must not connect to Firestore"),
    )

    target = admin_rescue_purchase.load_rescue_target(PRODUCTION_TARGET_ENV)

    assert target.app_env == "production"
    assert target.app_origin == admin_rescue_purchase.PRODUCTION_APP_ORIGIN


def test_dry_run_does_not_generate_token_or_write(monkeypatch):
    writes = []
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    fake_client = object()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda target: fake_client)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )
    monkeypatch.setattr(
        admin_rescue_purchase.secrets,
        "token_urlsafe",
        lambda length: pytest.fail("dry-run must not generate a token"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda *args: writes.append(args),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(make_args(), stdout=stdout, stderr=stderr)

    assert exit_code == 0
    assert "Environment: staging" in stdout.getvalue()
    assert f"Project: {admin_rescue_purchase.STAGING_PROJECT_ID}" in stdout.getvalue()
    assert "Database: ryujin-staging" in stdout.getvalue()
    assert "Collection: purchases" in stdout.getvalue()
    assert f"App origin: {admin_rescue_purchase.STAGING_APP_ORIGIN}" in stdout.getvalue()
    assert f"Target confirmation: {admin_rescue_purchase.load_rescue_target().confirmation}" in stdout.getvalue()
    assert "mode=dry-run" in stdout.getvalue()
    assert "Purchase eligibility: eligible" in stdout.getvalue()
    assert writes == []
    assert stderr.getvalue() == ""


def test_apply_requires_exact_purchase_id_confirmation(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda target: pytest.fail("must reject before Firestore client creation"),
    )
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(apply=True, confirm_purchase_id="p_other"),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "error=confirm_purchase_id_mismatch" in stderr.getvalue()


def test_apply_requires_exact_target_confirmation(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda target: pytest.fail("must reject before Firestore client creation"),
    )

    exit_code = admin_rescue_purchase.run(
        make_args(apply=True, confirm_purchase_id="p_test_rescue"),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 2


@pytest.mark.parametrize(
    "changed_values",
    [
        {"APP_ENV": "production"},
        {"FIRESTORE_PROJECT_ID": "other-staging-project-456"},
        {"FIRESTORE_DATABASE_ID": "other-staging"},
        {"FIRESTORE_PURCHASES_COLLECTION": "other_purchases"},
        {
            "APP_BASE_URL": "https://other-staging.example",
            "ADMIN_RESCUE_CANONICAL_APP_ORIGIN": "https://other-staging.example",
        },
    ],
)
def test_apply_rejects_target_change_immediately_before_transaction(monkeypatch, changed_values):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    writes = []
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: object())

    def read_purchase(purchase_id, **kwargs):
        for key, value in changed_values.items():
            monkeypatch.setenv(key, value)
        return make_purchase()

    monkeypatch.setattr(admin_rescue_purchase, "get_purchase_by_id", read_purchase)
    monkeypatch.setattr(
        admin_rescue_purchase.secrets,
        "token_urlsafe",
        lambda length: pytest.fail("must reject before token generation"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "error=target_config_changed" in stderr.getvalue()
    assert writes == []


def test_valid_staging_target_allows_dry_run_with_mocked_firestore(monkeypatch):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda target: object())
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )

    exit_code = admin_rescue_purchase.run(
        make_args(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0


def test_apply_without_clipboard_flag_rejects_before_token_or_write(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda value: pytest.fail("missing clipboard flag must reject before Firestore client creation"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase.secrets,
        "token_urlsafe",
        lambda length: pytest.fail("missing clipboard flag must reject before token generation"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda *args, **kwargs: pytest.fail("missing clipboard flag must reject before write"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "error=copy_url_to_clipboard_required" in stderr.getvalue()
    assert NEW_TOKEN not in stderr.getvalue()


def test_apply_failure_does_not_output_generated_token(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: object())
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )
    monkeypatch.setattr(admin_rescue_purchase.secrets, "token_urlsafe", lambda length: NEW_TOKEN)
    monkeypatch.setattr(admin_rescue_purchase, "preflight_windows_clipboard", lambda: None)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda purchase_id, token, **kwargs: firestore_service.TOKEN_RESCUE_PROCESSING,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert NEW_TOKEN not in stderr.getvalue()


def test_apply_can_copy_resume_url_without_printing_secret(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    events = []
    copied_values = []
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: object())
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "preflight_windows_clipboard",
        lambda: events.append("preflight"),
    )

    def generate_token(length):
        events.append("token")
        return NEW_TOKEN

    def write_token(purchase_id, token, **kwargs):
        events.append("write")
        assert token == NEW_TOKEN
        return firestore_service.TOKEN_RESCUE_ELIGIBLE

    def copy_url(value):
        events.append("copy")
        copied_values.append(value)

    monkeypatch.setattr(admin_rescue_purchase.secrets, "token_urlsafe", generate_token)
    monkeypatch.setattr(admin_rescue_purchase, "reissue_purchase_access_token_transaction", write_token)
    monkeypatch.setattr(admin_rescue_purchase, "copy_text_to_windows_clipboard", copy_url)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert events == ["preflight", "token", "write", "copy"]
    assert len(copied_values) == 1
    assert copied_values[0].startswith(f"{admin_rescue_purchase.PRODUCTION_APP_ORIGIN}/?")
    assert f"#access_token={NEW_TOKEN}" in copied_values[0]
    assert stdout.getvalue() == "SELF_RESUME_URL_COPIED=true\n"
    combined_output = stdout.getvalue() + stderr.getvalue()
    assert NEW_TOKEN not in combined_output
    assert copied_values[0] not in combined_output


def test_clipboard_preflight_failure_rejects_before_token_or_write(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: object())
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )

    def fail_preflight():
        raise admin_rescue_purchase.ClipboardUnavailableError("test clipboard unavailable")

    monkeypatch.setattr(admin_rescue_purchase, "preflight_windows_clipboard", fail_preflight)
    monkeypatch.setattr(
        admin_rescue_purchase.secrets,
        "token_urlsafe",
        lambda length: pytest.fail("preflight failure must happen before token generation"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda *args, **kwargs: pytest.fail("preflight failure must happen before write"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "error=clipboard_preflight_failed" in stderr.getvalue()


def test_clipboard_copy_failure_after_write_is_explicit_and_does_not_retry(monkeypatch):
    set_target_environment(monkeypatch, PRODUCTION_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    writes = []
    copy_attempts = []
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: object())
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )
    monkeypatch.setattr(admin_rescue_purchase, "preflight_windows_clipboard", lambda: None)
    monkeypatch.setattr(admin_rescue_purchase.secrets, "token_urlsafe", lambda length: NEW_TOKEN)

    def write_token(purchase_id, token, **kwargs):
        writes.append(token)
        return firestore_service.TOKEN_RESCUE_ELIGIBLE

    def fail_copy(value):
        copy_attempts.append(value)
        raise admin_rescue_purchase.ClipboardUnavailableError("test clipboard copy failure")

    monkeypatch.setattr(admin_rescue_purchase, "reissue_purchase_access_token_transaction", write_token)
    monkeypatch.setattr(admin_rescue_purchase, "copy_text_to_windows_clipboard", fail_copy)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 3
    assert writes == [NEW_TOKEN]
    assert len(copy_attempts) == 1
    assert stdout.getvalue() == ""
    assert "error=clipboard_copy_failed_after_write" in stderr.getvalue()
    combined_output = stdout.getvalue() + stderr.getvalue()
    assert NEW_TOKEN not in combined_output
    assert copy_attempts[0] not in combined_output


def test_dry_run_clipboard_flag_is_rejected_without_clipboard_or_firestore(monkeypatch):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "preflight_windows_clipboard",
        lambda: pytest.fail("dry-run must not access the clipboard"),
    )
    monkeypatch.setattr(
        admin_rescue_purchase,
        "create_target_firestore_client",
        lambda target: pytest.fail("invalid dry-run flags must fail before Firestore"),
    )
    stderr = io.StringIO()

    exit_code = admin_rescue_purchase.run(
        make_args(copy_url_to_clipboard=True),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "error=copy_url_to_clipboard_requires_apply" in stderr.getvalue()


def test_firestore_client_cleanup_closes_public_client_and_grpc_transport():
    client = TrackingClient()

    admin_rescue_purchase.close_target_firestore_client(client)

    assert client.closed is True
    assert client._transport.closed is True


@pytest.mark.parametrize(
    ("purchase", "expected_exit_code"),
    [
        (make_purchase(), 0),
        (make_purchase(used_flag=True), 1),
    ],
)
def test_dry_run_closes_firestore_client(monkeypatch, purchase, expected_exit_code):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    client = TrackingClient()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda target: client)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: purchase,
    )

    exit_code = admin_rescue_purchase.run(
        make_args(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == expected_exit_code
    assert client.closed is True
    assert client._transport.closed is True


def test_mock_apply_success_closes_firestore_client(monkeypatch):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    target = admin_rescue_purchase.load_rescue_target()
    client = TrackingClient()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda value: client)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "get_purchase_by_id",
        lambda purchase_id, **kwargs: make_purchase(),
    )
    monkeypatch.setattr(admin_rescue_purchase.secrets, "token_urlsafe", lambda length: NEW_TOKEN)
    monkeypatch.setattr(admin_rescue_purchase, "preflight_windows_clipboard", lambda: None)
    monkeypatch.setattr(admin_rescue_purchase, "copy_text_to_windows_clipboard", lambda value: None)
    monkeypatch.setattr(
        admin_rescue_purchase,
        "reissue_purchase_access_token_transaction",
        lambda purchase_id, token, **kwargs: firestore_service.TOKEN_RESCUE_ELIGIBLE,
    )

    exit_code = admin_rescue_purchase.run(
        make_args(
            apply=True,
            confirm_purchase_id="p_test_rescue",
            confirm_target=target.confirmation,
            copy_url_to_clipboard=True,
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert client.closed is True
    assert client._transport.closed is True


def test_firestore_client_is_closed_when_purchase_read_raises(monkeypatch):
    set_target_environment(monkeypatch, STAGING_TARGET_ENV)
    client = TrackingClient()
    monkeypatch.setattr(admin_rescue_purchase, "create_target_firestore_client", lambda target: client)

    def raise_read_error(purchase_id, **kwargs):
        raise RuntimeError("test read failure")

    monkeypatch.setattr(admin_rescue_purchase, "get_purchase_by_id", raise_read_error)

    with pytest.raises(RuntimeError, match="test read failure"):
        admin_rescue_purchase.run(
            make_args(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

    assert client.closed is True
    assert client._transport.closed is True


def test_dry_run_process_exits_after_background_resource_is_closed():
    script = textwrap.dedent(
        f"""
        import os
        import threading
        from datetime import datetime, timedelta, timezone

        from scripts import admin_rescue_purchase as rescue

        for key, value in {STAGING_TARGET_ENV!r}.items():
            os.environ[key] = value

        class BackgroundClient:
            def __init__(self):
                self.stop = threading.Event()
                self.thread = threading.Thread(target=self.stop.wait, daemon=False)
                self.thread.start()

            def close(self):
                self.stop.set()
                self.thread.join(timeout=2)

        client = BackgroundClient()
        rescue.create_target_firestore_client = lambda target: client
        rescue.get_purchase_by_id = lambda purchase_id, **kwargs: {{
            "purchase_id": "p_test_rescue",
            "payment_status": "paid",
            "used_flag": False,
            "generation_processing": False,
            "checkout_completed_at": datetime.now(timezone.utc) - timedelta(days=1),
            "product_type": "regular",
            "pdf_status": None,
        }}
        raise SystemExit(rescue.main(["p_test_rescue"]))
        """
    )
    environment = os.environ.copy()

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=admin_rescue_purchase.REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "Purchase eligibility: eligible" in result.stdout
    assert result.stderr == ""
