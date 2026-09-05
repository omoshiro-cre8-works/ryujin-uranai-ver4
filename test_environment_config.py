import re
import subprocess
import sys
from pathlib import Path

import pytest

from stripe_webhook.environment_config import (
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
    assert get_app_environment({"APP_ENV": "StAgInG"}) == "staging"
    assert get_app_environment({"APP_ENV": "staging"}) == "staging"
    assert get_app_environment({"APP_ENV": "test"}) == "test"


def test_unknown_app_env_fails_closed():
    with pytest.raises(EnvironmentConfigError, match="APP_ENV"):
        get_app_environment({"APP_ENV": "preview"})


def test_app_env_uses_production_webhook_compatibility_from_k_service():
    assert get_app_environment({"K_SERVICE": "ai-uranai-webhook"}) == "production"


def test_app_env_requires_explicit_staging_for_staging_webhook_service():
    with pytest.raises(EnvironmentConfigError, match="APP_ENV=staging"):
        get_app_environment({"K_SERVICE": "ai-uranai-webhook-staging"})


def test_app_env_rejects_unknown_cloud_run_service_without_explicit_app_env():
    with pytest.raises(EnvironmentConfigError, match="Cloud Run"):
        get_app_environment({"K_SERVICE": "ai-uranai-h1-staging"})


def test_app_env_missing_and_blank_are_local_outside_cloud_run():
    assert get_app_environment({}) == "local"
    assert get_app_environment({"APP_ENV": "   "}) == "local"


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
        "FIRESTORE_COLLECTION_NAME": "purchases",
    }

    kwargs, settings = build_firestore_client_kwargs(env)

    assert kwargs == {"project": "staging-project", "database": "ryujin-staging"}
    assert settings.collection_name == "purchases"
    assert get_firestore_collection_name(env) == "purchases"


@pytest.mark.parametrize(
    "env_update, message",
    [
        ({"FIRESTORE_PROJECT_ID": ""}, "FIRESTORE_PROJECT_ID"),
        ({"FIRESTORE_DATABASE_ID": ""}, "FIRESTORE_DATABASE_ID"),
        ({"FIRESTORE_DATABASE_ID": "(default)"}, "default"),
        ({"FIRESTORE_COLLECTION_NAME": ""}, "FIRESTORE_COLLECTION_NAME"),
    ],
)
def test_staging_firestore_fails_closed(env_update, message):
    env = {
        "APP_ENV": "staging",
        "FIRESTORE_PROJECT_ID": "staging-project",
        "FIRESTORE_DATABASE_ID": "ryujin-staging",
        "FIRESTORE_COLLECTION_NAME": "purchases",
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


def test_local_and_test_reject_live_stripe_key_prefix():
    with pytest.raises(EnvironmentConfigError, match="live secret key"):
        get_stripe_settings(
            {"APP_ENV": "local", "STRIPE_MODE": "test"},
            secret_key="sk_live_placeholder",
        )
    with pytest.raises(EnvironmentConfigError, match="live secret key"):
        get_stripe_settings(
            {"APP_ENV": "test"},
            secret_key="rk_live_placeholder",
        )


def test_firestore_service_client_uses_configured_database(monkeypatch):
    from services import firestore_service

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "staging-project")
    monkeypatch.setenv("FIRESTORE_DATABASE_ID", "ryujin-staging")
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
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
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
    monkeypatch.setattr(firestore_service.firestore, "Client", FakeClient)

    with pytest.raises(EnvironmentConfigError):
        firestore_service.get_firestore_client()

    assert calls == []


def test_local_firestore_without_project_preserves_existing_client_creation(monkeypatch):
    from services import firestore_service

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.setattr(firestore_service.firestore, "Client", FakeClient)

    firestore_service.get_firestore_client()

    assert calls == [{}]


def test_production_webhook_compat_env_preserves_existing_defaults():
    env = {
        "K_SERVICE": "ai-uranai-webhook",
        "FIRESTORE_COLLECTION_NAME": "purchases",
    }

    kwargs, firestore_settings = build_firestore_client_kwargs(env)
    stripe_settings = get_stripe_settings(env, secret_key="sk_live_placeholder")

    assert kwargs == {}
    assert firestore_settings.app_env == "production"
    assert firestore_settings.project_id is None
    assert firestore_settings.database_id == DEFAULT_FIRESTORE_DATABASE_ID
    assert firestore_settings.collection_name == "purchases"
    assert stripe_settings.mode == "live"


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
    monkeypatch.setenv("FIRESTORE_COLLECTION_NAME", "purchases")
    monkeypatch.setattr(stripe_webhook_app.firestore, "Client", FakeClient)

    stripe_webhook_app.get_purchase_doc_ref("p_1")

    assert calls == [
        ("client", {"project": "staging-project", "database": "ryujin-staging"}),
        ("collection", "purchases"),
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


def test_webhook_docker_context_can_import_environment_config():
    root = Path(__file__).resolve().parent
    script = """
import sys, types
from types import SimpleNamespace
class FakeFlask:
    def __init__(self, *args, **kwargs): pass
    def get(self, *args, **kwargs): return lambda func: func
    def post(self, *args, **kwargs): return lambda func: func
flask_module = types.ModuleType("flask")
flask_module.Flask = FakeFlask
flask_module.jsonify = lambda value=None, **kwargs: value if value is not None else kwargs
flask_module.request = SimpleNamespace(get_data=lambda: b"", headers={})
sys.modules["flask"] = flask_module
stripe_module = types.ModuleType("stripe")
stripe_module.api_key = None
stripe_module.Webhook = SimpleNamespace(construct_event=lambda **kwargs: {})
stripe_module.error = SimpleNamespace(SignatureVerificationError=Exception)
sys.modules["stripe"] = stripe_module
google_module = sys.modules.setdefault("google", types.ModuleType("google"))
cloud_module = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
firestore_module = types.ModuleType("google.cloud.firestore")
firestore_module.Client = lambda **kwargs: None
cloud_module.firestore = firestore_module
google_module.cloud = cloud_module
sys.modules["google.cloud.firestore"] = firestore_module
import stripe_webhook_app
print("ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root / "stripe_webhook",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
