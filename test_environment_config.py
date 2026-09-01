import re
from pathlib import Path

import pytest

from services.environment_config import (
    DEFAULT_FIRESTORE_DATABASE_ID,
    EnvironmentConfigError,
    PRODUCTION_FIRESTORE_COLLECTION,
    build_firestore_client_kwargs,
    get_app_environment,
    get_firestore_collection_name,
    get_firestore_settings,
    get_stripe_settings,
)


def test_app_env_normalizes_existing_production_value():
    assert get_app_environment({"APP_ENV": " prod "}) == "production"
    assert get_app_environment({"APP_ENV": "production"}) == "production"
    assert get_app_environment({"APP_ENV": "staging"}) == "staging"
    assert get_app_environment({"APP_ENV": "test"}) == "test"


def test_unknown_app_env_fails_closed():
    with pytest.raises(EnvironmentConfigError, match="APP_ENV"):
        get_app_environment({"APP_ENV": "preview"})


def test_production_preserves_default_firestore_connection():
    kwargs, settings = build_firestore_client_kwargs({"APP_ENV": "prod"})

    assert kwargs == {}
    assert settings.project_id is None
    assert settings.database_id == DEFAULT_FIRESTORE_DATABASE_ID
    assert settings.collection_name == PRODUCTION_FIRESTORE_COLLECTION


def test_production_can_use_explicit_firestore_project_and_default_database():
    kwargs, settings = build_firestore_client_kwargs(
        {
            "APP_ENV": "production",
            "FIRESTORE_PROJECT_ID": "prod-project",
        }
    )

    assert kwargs == {"project": "prod-project", "database": DEFAULT_FIRESTORE_DATABASE_ID}
    assert settings.collection_name == PRODUCTION_FIRESTORE_COLLECTION


def test_staging_uses_explicit_firestore_target():
    env = {
        "APP_ENV": " staging ",
        "FIRESTORE_PROJECT_ID": "staging-project",
        "FIRESTORE_DATABASE_ID": "ryujin-staging",
        "FIRESTORE_COLLECTION_NAME": "purchases_staging",
    }

    kwargs, settings = build_firestore_client_kwargs(env)

    assert kwargs == {"project": "staging-project", "database": "ryujin-staging"}
    assert settings.collection_name == "purchases_staging"
    assert get_firestore_collection_name(env) == "purchases_staging"


@pytest.mark.parametrize(
    "env_update, message",
    [
        ({"FIRESTORE_PROJECT_ID": ""}, "FIRESTORE_PROJECT_ID"),
        ({"FIRESTORE_DATABASE_ID": ""}, "FIRESTORE_DATABASE_ID"),
        ({"FIRESTORE_DATABASE_ID": "(default)"}, "default"),
        ({"FIRESTORE_COLLECTION_NAME": ""}, "FIRESTORE_COLLECTION_NAME"),
        ({"FIRESTORE_COLLECTION_NAME": "purchases"}, "production"),
    ],
)
def test_staging_firestore_fails_closed(env_update, message):
    env = {
        "APP_ENV": "staging",
        "FIRESTORE_PROJECT_ID": "staging-project",
        "FIRESTORE_DATABASE_ID": "ryujin-staging",
        "FIRESTORE_COLLECTION_NAME": "purchases_staging",
    }
    env.update(env_update)

    with pytest.raises(EnvironmentConfigError, match=message):
        get_firestore_settings(env)


def test_production_stripe_defaults_to_live_mode():
    settings = get_stripe_settings({"APP_ENV": "prod"}, secret_key="sk_live_placeholder")

    assert settings.mode == "live"


def test_production_rejects_test_mode_and_test_key():
    with pytest.raises(EnvironmentConfigError, match="STRIPE_MODE=live"):
        get_stripe_settings({"APP_ENV": "production", "STRIPE_MODE": "test"})

    with pytest.raises(EnvironmentConfigError, match="test secret key"):
        get_stripe_settings({"APP_ENV": "production"}, secret_key="sk_test_placeholder")


def test_staging_requires_test_stripe_mode():
    with pytest.raises(EnvironmentConfigError, match="STRIPE_MODE=test"):
        get_stripe_settings({"APP_ENV": "staging"})

    with pytest.raises(EnvironmentConfigError, match="test"):
        get_stripe_settings({"APP_ENV": "staging", "STRIPE_MODE": "live"})


def test_staging_rejects_live_stripe_key_without_leaking_value():
    key = "sk_live_secret_value"

    with pytest.raises(EnvironmentConfigError) as exc:
        get_stripe_settings(
            {"APP_ENV": "staging", "STRIPE_MODE": "test"},
            secret_key=key,
        )

    assert "live secret key" in str(exc.value)
    assert key not in str(exc.value)


def test_local_and_test_do_not_allow_live_stripe_mode():
    with pytest.raises(EnvironmentConfigError, match="live mode"):
        get_stripe_settings({"APP_ENV": "local", "STRIPE_MODE": "live"})

    assert get_stripe_settings({"APP_ENV": "test"}).mode == "test"


def test_firestore_service_client_uses_configured_database(monkeypatch):
    from services import firestore_service

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "staging-project")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "ryujin-staging")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases_staging")
    monkeypatch.setattr(firestore_service.firestore, "Client", FakeClient)

    firestore_service.get_firestore_client()

    assert calls == [{"project": "staging-project", "database": "ryujin-staging"}]


def test_staging_config_error_prevents_firestore_client_creation(monkeypatch):
    from services import firestore_service

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "staging-project")
    monkeypatch.delenv("FIRESTORE_DATABASE_ID", raising=False)
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases_staging")
    monkeypatch.setattr(firestore_service.firestore, "Client", FakeClient)

    with pytest.raises(EnvironmentConfigError):
        firestore_service.get_firestore_client()

    assert calls == []


def test_local_firestore_without_project_fails_before_client_creation(monkeypatch):
    from services import firestore_service

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.setattr(firestore_service.firestore, "Client", FakeClient)

    with pytest.raises(EnvironmentConfigError, match="FIRESTORE_PROJECT_ID"):
        firestore_service.get_firestore_client()

    assert calls == []


def test_webhook_firestore_uses_configured_database_and_collection(monkeypatch):
    from stripe_webhook import stripe_webhook_app

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

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "staging-project")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "ryujin-staging")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases_staging")
    monkeypatch.setattr(stripe_webhook_app.firestore, "Client", FakeClient)

    stripe_webhook_app.get_purchase_doc_ref("p_1")

    assert calls == [
        ("client", {"project": "staging-project", "database": "ryujin-staging"}),
        ("collection", "purchases_staging"),
        ("document", "p_1"),
    ]


def test_executable_code_has_no_direct_production_purchase_collection_reference():
    root = Path(__file__).resolve().parent
    targets = [
        root / "app.py",
        *(
            path
            for path in (root / "services").glob("*.py")
            if not path.name.startswith("test_")
        ),
        *(
            path
            for path in (root / "stripe_webhook").glob("*.py")
            if not path.name.startswith("test_")
        ),
    ]
    pattern = re.compile(r"\.collection\(\s*['\"]purchases['\"]\s*\)")

    offenders = [
        str(path.relative_to(root))
        for path in targets
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
