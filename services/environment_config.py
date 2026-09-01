from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class EnvironmentConfigError(RuntimeError):
    """Raised when environment isolation settings are unsafe or incomplete."""


PRODUCTION_ENV = "production"
STAGING_ENV = "staging"
LOCAL_ENV = "local"
TEST_ENV = "test"
DEFAULT_FIRESTORE_DATABASE_ID = "(default)"
PRODUCTION_FIRESTORE_COLLECTION = "purchases"

_APP_ENV_ALIASES = {
    "prod": PRODUCTION_ENV,
    "production": PRODUCTION_ENV,
    "staging": STAGING_ENV,
    "stage": STAGING_ENV,
    "local": LOCAL_ENV,
    "dev": LOCAL_ENV,
    "development": LOCAL_ENV,
    "test": TEST_ENV,
    "testing": TEST_ENV,
}


@dataclass(frozen=True)
class FirestoreSettings:
    app_env: str
    project_id: str | None
    database_id: str | None
    collection_name: str


@dataclass(frozen=True)
class StripeSettings:
    app_env: str
    mode: str


def _read_env(env: Mapping[str, str] | None, key: str) -> str:
    source = os.environ if env is None else env
    return str(source.get(key, "")).strip()


def get_app_environment(env: Mapping[str, str] | None = None) -> str:
    raw_value = _read_env(env, "APP_ENV") or LOCAL_ENV
    normalized = _APP_ENV_ALIASES.get(raw_value.lower())
    if normalized is None:
        raise EnvironmentConfigError(
            "APP_ENV は production / staging / local / test のいずれかを指定してください。"
        )
    return normalized


def get_firestore_settings(env: Mapping[str, str] | None = None) -> FirestoreSettings:
    app_env = get_app_environment(env)
    project_id = _read_env(env, "FIRESTORE_PROJECT_ID") or None
    database_id = _read_env(env, "FIRESTORE_DATABASE_ID") or DEFAULT_FIRESTORE_DATABASE_ID
    collection_name = _read_env(env, "FIRESTORE_COLLECTION_NAME") or PRODUCTION_FIRESTORE_COLLECTION

    if app_env == STAGING_ENV:
        if not project_id:
            raise EnvironmentConfigError("staging では FIRESTORE_PROJECT_ID が必須です。")
        if not _read_env(env, "FIRESTORE_DATABASE_ID"):
            raise EnvironmentConfigError("staging では FIRESTORE_DATABASE_ID が必須です。")
        if database_id == DEFAULT_FIRESTORE_DATABASE_ID:
            raise EnvironmentConfigError(
                "staging では Firestore の (default) database を使用できません。"
            )
        if not _read_env(env, "FIRESTORE_COLLECTION_NAME"):
            raise EnvironmentConfigError("staging では FIRESTORE_COLLECTION_NAME が必須です。")
        if collection_name == PRODUCTION_FIRESTORE_COLLECTION:
            raise EnvironmentConfigError(
                "staging では production 用 Firestore collection を使用できません。"
            )
    elif app_env in {LOCAL_ENV, TEST_ENV} and not project_id:
        raise EnvironmentConfigError(
            "local/test 環境では FIRESTORE_PROJECT_ID を明示してください。"
        )

    return FirestoreSettings(
        app_env=app_env,
        project_id=project_id,
        database_id=database_id,
        collection_name=collection_name,
    )


def build_firestore_client_kwargs(
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], FirestoreSettings]:
    settings = get_firestore_settings(env)
    kwargs: dict[str, str] = {}
    if settings.project_id:
        kwargs["project"] = settings.project_id
    if settings.database_id != DEFAULT_FIRESTORE_DATABASE_ID or settings.project_id:
        kwargs["database"] = settings.database_id or DEFAULT_FIRESTORE_DATABASE_ID
    return kwargs, settings


def get_firestore_collection_name(env: Mapping[str, str] | None = None) -> str:
    return get_firestore_settings(env).collection_name


def get_stripe_settings(
    env: Mapping[str, str] | None = None,
    secret_key: str | None = None,
) -> StripeSettings:
    app_env = get_app_environment(env)
    raw_mode = _read_env(env, "STRIPE_MODE")

    if app_env == PRODUCTION_ENV:
        mode = raw_mode.lower() if raw_mode else "live"
        if mode != "live":
            raise EnvironmentConfigError("production では STRIPE_MODE=live が必要です。")
    elif app_env == STAGING_ENV:
        if not raw_mode:
            raise EnvironmentConfigError("staging では STRIPE_MODE=test が必須です。")
        mode = raw_mode.lower()
        if mode != "test":
            raise EnvironmentConfigError("staging では STRIPE_MODE=test のみ使用できます。")
    else:
        mode = raw_mode.lower() if raw_mode else "test"
        if mode not in {"test", "live"}:
            raise EnvironmentConfigError("STRIPE_MODE は live または test を指定してください。")
        if mode == "live":
            raise EnvironmentConfigError(
                "local/test 環境では Stripe live mode を使用できません。"
            )

    key = (secret_key or "").strip()
    if key:
        if app_env == STAGING_ENV and key.startswith(("sk_live_", "rk_live_")):
            raise EnvironmentConfigError(
                "staging では Stripe live secret key を使用できません。"
            )
        if app_env == PRODUCTION_ENV and key.startswith(("sk_test_", "rk_test_")):
            raise EnvironmentConfigError(
                "production では Stripe test secret key を使用できません。"
            )

    return StripeSettings(app_env=app_env, mode=mode)
