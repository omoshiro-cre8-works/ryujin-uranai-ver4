import logging
import sys
import types
from types import SimpleNamespace


if "flask" not in sys.modules:
    try:
        import flask  # noqa: F401
    except ImportError:
        class FakeFlask:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                return lambda func: func

            def post(self, *args, **kwargs):
                return lambda func: func

            def run(self, *args, **kwargs):
                pass

        flask_module = types.ModuleType("flask")
        flask_module.Flask = FakeFlask
        flask_module.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
        flask_module.request = SimpleNamespace(get_data=lambda: b"", headers={})
        sys.modules["flask"] = flask_module

if "stripe" not in sys.modules:
    try:
        import stripe  # noqa: F401
    except ImportError:
        stripe_module = types.ModuleType("stripe")
        stripe_module.api_key = None
        stripe_module.Webhook = SimpleNamespace(construct_event=lambda **kwargs: {})
        stripe_module.error = SimpleNamespace(SignatureVerificationError=Exception)
        sys.modules["stripe"] = stripe_module

if "google.cloud.firestore" not in sys.modules:
    try:
        from google.cloud import firestore  # noqa: F401
    except ImportError:
        google_module = sys.modules.setdefault("google", types.ModuleType("google"))
        cloud_module = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
        firestore_module = types.ModuleType("google.cloud.firestore")
        firestore_module.Client = lambda *args, **kwargs: None
        firestore_module.transactional = lambda func: func
        cloud_module.firestore = firestore_module
        google_module.cloud = cloud_module
        sys.modules["google.cloud.firestore"] = firestore_module

from stripe_webhook import stripe_webhook_app


DUMMY_LIVE_KEY = "sk_live_dummy_pr6_not_real"
DUMMY_TEST_KEY = "sk_test_dummy_pr6_not_real"
DUMMY_WEBHOOK_SECRET = "whsec_dummy_pr6_not_real"


def purchase_record() -> dict:
    return {
        "purchase_id": "p_1",
        "stripe_checkout_session_id": "cs_test_1",
        "payment_status": "pending",
        "amount_jpy": 300,
        "currency": "jpy",
        "price_id": "price_1",
        "product_type": "regular",
        "price_type": "regular_campaign",
        "stripe_event_id": None,
        "entry_lp": "lp_e",
        "entry_utm_source": "instagram",
        "entry_utm_medium": "paid_social",
        "entry_utm_campaign": "summer",
        "entry_utm_content": "lp_e_ad",
        "current_lp": "lp_e",
        "button_position": "sample_bottom",
    }


def checkout_session(*, payment_status: str = "paid", status: str = "complete") -> dict:
    return {
        "id": "cs_test_1",
        "client_reference_id": "p_1",
        "payment_status": payment_status,
        "status": status,
        "amount_total": 300,
        "currency": "jpy",
        "metadata": {
            "purchase_id": "p_1",
            "price_id": "price_1",
            "product_type": "regular",
            "price_type": "regular_campaign",
        },
    }


def test_complete_but_unpaid_session_is_not_marked_paid(monkeypatch) -> None:
    updates = []
    monkeypatch.setattr(
        stripe_webhook_app,
        "get_purchase_record",
        lambda purchase_id: purchase_record(),
    )
    monkeypatch.setattr(
        stripe_webhook_app,
        "update_purchase_record",
        lambda purchase_id, **kwargs: updates.append((purchase_id, kwargs)),
    )

    handled = stripe_webhook_app.mark_purchase_paid_from_session(
        checkout_session(payment_status="unpaid", status="complete"),
        "evt_1",
    )

    assert not handled
    assert updates == []


def test_paid_session_with_matching_record_is_marked_paid(monkeypatch) -> None:
    updates = []
    monkeypatch.setattr(
        stripe_webhook_app,
        "get_purchase_record",
        lambda purchase_id: purchase_record(),
    )
    monkeypatch.setattr(
        stripe_webhook_app,
        "update_purchase_record",
        lambda purchase_id, **kwargs: updates.append((purchase_id, kwargs)),
    )

    handled = stripe_webhook_app.mark_purchase_paid_from_session(
        checkout_session(),
        "evt_1",
    )

    assert handled
    assert len(updates) == 1
    assert updates[0][0] == "p_1"
    assert updates[0][1]["payment_status"] == "paid"
    assert "entry_lp" not in updates[0][1]
    assert "entry_utm_source" not in updates[0][1]
    assert "current_lp" not in updates[0][1]
    assert "button_position" not in updates[0][1]


def test_paid_session_with_amount_mismatch_is_not_marked_paid(monkeypatch) -> None:
    updates = []
    session = checkout_session()
    session["amount_total"] = 999
    monkeypatch.setattr(
        stripe_webhook_app,
        "get_purchase_record",
        lambda purchase_id: purchase_record(),
    )
    monkeypatch.setattr(
        stripe_webhook_app,
        "update_purchase_record",
        lambda purchase_id, **kwargs: updates.append((purchase_id, kwargs)),
    )

    handled = stripe_webhook_app.mark_purchase_paid_from_session(session, "evt_1")

    assert not handled
    assert updates == []


def test_paid_session_with_purchase_id_mismatch_is_not_marked_paid(monkeypatch) -> None:
    updates = []
    session = checkout_session()
    session["client_reference_id"] = "p_other"
    monkeypatch.setattr(
        stripe_webhook_app,
        "get_purchase_record",
        lambda purchase_id: purchase_record(),
    )
    monkeypatch.setattr(
        stripe_webhook_app,
        "update_purchase_record",
        lambda purchase_id, **kwargs: updates.append((purchase_id, kwargs)),
    )

    handled = stripe_webhook_app.mark_purchase_paid_from_session(session, "evt_1")

    assert not handled
    assert updates == []


def test_production_webhook_compat_healthcheck_succeeds(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_LIVE_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response = stripe_webhook_app.healthcheck()

    assert response["status"] == "ok"
    assert response["collection"] == "purchases"


def test_explicit_production_healthcheck_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_LIVE_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response = stripe_webhook_app.healthcheck()

    assert response["status"] == "ok"
    assert response["collection"] == "purchases"


def test_staging_healthcheck_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook-staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "dummy-staging-project-pr6")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "dummy-staging-db-pr6")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "dummy_purchases_staging_pr6")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response = stripe_webhook_app.healthcheck()

    assert response["status"] == "ok"
    assert response["collection"] == "dummy_purchases_staging_pr6"


def test_local_healthcheck_succeeds_without_firestore_project(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "dummy_local_pr6")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response = stripe_webhook_app.healthcheck()

    assert response["status"] == "ok"
    assert response["collection"] == "dummy_local_pr6"


def test_staging_webhook_without_app_env_fails_healthcheck(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook-staging")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response, status = stripe_webhook_app.healthcheck()

    assert status == 500
    assert response["status"] == "error"
    assert response["error"] == "configuration invalid"


def test_unknown_cloud_run_service_fails_healthcheck(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("K_SERVICE", "unknown-cloud-run-service-pr6")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    response, status = stripe_webhook_app.healthcheck()

    assert status == 500
    assert response == {"status": "error", "error": "configuration invalid"}


def test_staging_healthcheck_fails_closed_for_firestore_settings(monkeypatch) -> None:
    base_env = {
        "APP_ENV": "staging",
        "K_SERVICE": "ai-uranai-webhook-staging",
        "FIRESTORE_PROJECT_ID": "dummy-staging-project-pr6",
        "FIRESTORE_DATABASE_ID": "dummy-staging-db-pr6",
        "FIRESTORE_COLLECTION_NAME": "dummy_purchases_staging_pr6",
        "STRIPE_MODE": "test",
    }
    bad_envs = [
        {"FIRESTORE_PROJECT_ID": None},
        {"FIRESTORE_DATABASE_ID": None},
        {"FIRESTORE_DATABASE_ID": "(default)"},
        {"FIRESTORE_COLLECTION_NAME": None},
        {"FIRESTORE_COLLECTION_NAME": "purchases"},
    ]
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)

    for override in bad_envs:
        for key, value in {**base_env, **override}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

        response, status = stripe_webhook_app.healthcheck()

        assert status == 500
        assert response == {"status": "error", "error": "configuration invalid"}


def test_staging_healthcheck_fails_closed_for_stripe_settings(monkeypatch) -> None:
    base_env = {
        "APP_ENV": "staging",
        "K_SERVICE": "ai-uranai-webhook-staging",
        "FIRESTORE_PROJECT_ID": "dummy-staging-project-pr6",
        "FIRESTORE_DATABASE_ID": "dummy-staging-db-pr6",
        "FIRESTORE_COLLECTION_NAME": "dummy_purchases_staging_pr6",
        "STRIPE_MODE": "test",
    }
    cases = [
        ({"STRIPE_MODE": None}, DUMMY_TEST_KEY, DUMMY_WEBHOOK_SECRET),
        ({"STRIPE_MODE": "live"}, DUMMY_TEST_KEY, DUMMY_WEBHOOK_SECRET),
        ({"STRIPE_MODE": "unknown"}, DUMMY_TEST_KEY, DUMMY_WEBHOOK_SECRET),
        ({}, DUMMY_LIVE_KEY, DUMMY_WEBHOOK_SECRET),
        ({}, "", DUMMY_WEBHOOK_SECRET),
        ({}, DUMMY_TEST_KEY, ""),
    ]

    for override, secret_key, webhook_secret in cases:
        for key, value in {**base_env, **override}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", secret_key)
        monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", webhook_secret)

        response, status = stripe_webhook_app.healthcheck()

        assert status == 500
        assert response == {"status": "error", "error": "configuration invalid"}
        assert DUMMY_LIVE_KEY not in str(response)
        assert DUMMY_TEST_KEY not in str(response)
        assert DUMMY_WEBHOOK_SECRET not in str(response)


def test_healthcheck_has_no_external_client_or_stripe_api_key_side_effect(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook-staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "dummy-staging-project-pr6")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "dummy-staging-db-pr6")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "dummy_purchases_staging_pr6")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_TEST_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)
    monkeypatch.setattr(stripe_webhook_app.stripe, "api_key", "sentinel")
    monkeypatch.setattr(
        stripe_webhook_app.firestore,
        "Client",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Firestore client created")),
    )

    response = stripe_webhook_app.healthcheck()

    assert response["status"] == "ok"
    assert stripe_webhook_app.stripe.api_key == "sentinel"


def test_healthcheck_logs_generic_config_error_without_secret(monkeypatch, caplog) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook-staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "dummy-staging-project-pr6")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "dummy-staging-db-pr6")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "dummy_purchases_staging_pr6")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", DUMMY_LIVE_KEY)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", DUMMY_WEBHOOK_SECRET)
    caplog.set_level(logging.ERROR, logger=stripe_webhook_app.logger.name)

    response, status = stripe_webhook_app.healthcheck()

    assert status == 500
    assert response == {"status": "error", "error": "configuration invalid"}
    assert "webhook_health_configuration_invalid" in caplog.text
    assert any(getattr(record, "component", None) == "stripe" for record in caplog.records)
    assert DUMMY_LIVE_KEY not in caplog.text
    assert DUMMY_TEST_KEY not in caplog.text
    assert DUMMY_WEBHOOK_SECRET not in caplog.text


def test_production_webhook_compat_uses_existing_firestore_defaults(monkeypatch) -> None:
    calls = []

    class FakeDocument:
        pass

    class FakeCollection:
        def document(self, purchase_id):
            calls.append(("document", purchase_id))
            return FakeDocument()

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def collection(self, name):
            calls.append(("collection", name))
            return FakeCollection()

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
    monkeypatch.setattr(stripe_webhook_app.firestore, "Client", FakeClient)

    stripe_webhook_app.get_purchase_doc_ref("p_1")

    assert calls == [
        ("client", {}),
        ("collection", "purchases"),
        ("document", "p_1"),
    ]


def test_webhook_sets_stripe_api_key_only_after_config_validation(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setattr(stripe_webhook_app.stripe, "api_key", None)

    response, status = stripe_webhook_app.stripe_webhook()

    assert status == 500
    assert "sk_test_placeholder" not in str(response)
    assert stripe_webhook_app.stripe.api_key is None


def test_webhook_unsupported_event_uses_signature_validation_and_skips_firestore(monkeypatch) -> None:
    client_calls = []
    construct_calls = []

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    monkeypatch.setenv("K_SERVICE", "ai-uranai-webhook")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", "sk_live_placeholder")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setattr(
        stripe_webhook_app.stripe.Webhook,
        "construct_event",
        lambda **kwargs: construct_calls.append(kwargs)
        or {"type": "customer.created", "id": "evt_1", "data": {"object": {}}},
    )
    monkeypatch.setattr(
        stripe_webhook_app.firestore,
        "Client",
        lambda **kwargs: client_calls.append(kwargs),
    )

    response, status = stripe_webhook_app.stripe_webhook()

    assert status == 200
    assert response["ignored_event_type"] == "customer.created"
    assert len(construct_calls) == 1
    assert client_calls == []


def test_webhook_completed_event_returns_config_error_without_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setattr(stripe_webhook_app, "STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setattr(
        stripe_webhook_app.stripe.Webhook,
        "construct_event",
        lambda **kwargs: {
            "type": "checkout.session.completed",
            "id": "evt_1",
            "data": {
                "object": {
                    "metadata": {"purchase_id": "p_1"},
                    "client_reference_id": "p_1",
                    "payment_status": "paid",
                    "id": "cs_1",
                }
            },
        },
    )

    response, status = stripe_webhook_app.stripe_webhook()

    assert status == 500
    assert "FIRESTORE_PROJECT_ID" in response["error"] or "FIRESTORE_DATABASE_ID" in response["error"]
    assert "sk_test_placeholder" not in str(response)
    assert "whsec_placeholder" not in str(response)
