import datetime
import logging
import os
from typing import Any

from flask import Flask, jsonify, request
from google.cloud import firestore
import stripe

try:
    from stripe_webhook.environment_config import (
        EnvironmentConfigError,
        build_firestore_client_kwargs,
        get_firestore_collection_name,
        get_stripe_settings,
    )
except ImportError:  # pragma: no cover - used when the build context is stripe_webhook/
    from environment_config import (
        EnvironmentConfigError,
        build_firestore_client_kwargs,
        get_firestore_collection_name,
        get_stripe_settings,
    )

app = Flask(__name__)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRODUCT_TYPE_REGULAR = "regular"
PRODUCT_TYPE_REVIEW = "review"
VALID_PRODUCT_TYPES = {PRODUCT_TYPE_REGULAR, PRODUCT_TYPE_REVIEW}


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def get_firestore_client() -> firestore.Client:
    client_kwargs, _ = build_firestore_client_kwargs()
    return firestore.Client(**client_kwargs)


def get_purchase_doc_ref(purchase_id: str):
    db = get_firestore_client()
    return db.collection(get_firestore_collection_name()).document(purchase_id)


def get_purchase_record(purchase_id: str) -> dict[str, Any] | None:
    snapshot = get_purchase_doc_ref(purchase_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict() or {}


def normalize_product_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in VALID_PRODUCT_TYPES:
        return normalized
    return PRODUCT_TYPE_REGULAR


def update_purchase_record(purchase_id: str, **updates: Any) -> dict[str, Any] | None:
    snapshot = get_purchase_doc_ref(purchase_id).get()
    if not snapshot.exists:
        return None

    updates["updated_at"] = utc_now()
    get_purchase_doc_ref(purchase_id).update(updates)

    refreshed = get_purchase_doc_ref(purchase_id).get()
    return refreshed.to_dict() if refreshed.exists else None


def mark_purchase_paid_from_session(session: dict[str, Any], event_id: str | None) -> bool:
    metadata = session.get("metadata") or {}
    metadata_purchase_id = metadata.get("purchase_id")
    client_reference_id = session.get("client_reference_id")
    if metadata_purchase_id and client_reference_id and metadata_purchase_id != client_reference_id:
        logger.warning("purchase_id_mismatch_in_session")
        return False

    purchase_id = metadata_purchase_id or client_reference_id
    if not purchase_id:
        logger.warning("purchase_id_not_found_in_session")
        return False

    record = get_purchase_record(purchase_id)
    if not record:
        logger.warning("purchase_record_not_found", extra={"purchase_id": purchase_id})
        return False

    payment_status = session.get("payment_status")
    if payment_status != "paid":
        logger.info(
            "session_not_paid_yet",
            extra={
                "purchase_id": purchase_id,
                "payment_status": payment_status,
                "status": session.get("status"),
            },
        )
        return False

    existing_event_id = record.get("stripe_event_id")
    if existing_event_id and event_id and existing_event_id == event_id:
        logger.info(
            "duplicate_webhook_event_ignored",
            extra={"purchase_id": purchase_id, "stripe_event_id": event_id},
        )
        return True

    session_id = session.get("id")
    if not session_id or record.get("stripe_checkout_session_id") != session_id:
        logger.warning("stripe_checkout_session_id_mismatch", extra={"purchase_id": purchase_id})
        return False

    amount_total = session.get("amount_total")
    currency = session.get("currency")
    if not isinstance(amount_total, int) or amount_total != record.get("amount_jpy"):
        logger.warning("stripe_amount_mismatch", extra={"purchase_id": purchase_id})
        return False
    if not currency or currency != record.get("currency"):
        logger.warning("stripe_currency_mismatch", extra={"purchase_id": purchase_id})
        return False

    metadata_price_id = metadata.get("price_id")
    if not metadata_price_id or metadata_price_id != record.get("price_id"):
        logger.warning("stripe_price_id_mismatch", extra={"purchase_id": purchase_id})
        return False

    metadata_product_type = metadata.get("product_type")
    if (
        not metadata_product_type
        or normalize_product_type(metadata_product_type)
        != normalize_product_type(str(record.get("product_type") or ""))
    ):
        logger.warning("stripe_product_type_mismatch", extra={"purchase_id": purchase_id})
        return False

    metadata_price_type = metadata.get("price_type")
    if not metadata_price_type or metadata_price_type != record.get("price_type"):
        logger.warning("stripe_price_type_mismatch", extra={"purchase_id": purchase_id})
        return False

    update_purchase_record(
        purchase_id,
        payment_status="paid",
        stripe_checkout_session_id=session_id,
        stripe_event_id=event_id,
        product_type=normalize_product_type(metadata_product_type),
        price_type=metadata_price_type,
        price_id=metadata_price_id,
        amount_jpy=amount_total,
        amount_total=amount_total,
        currency=currency,
        checkout_completed_at=utc_now(),
        webhook_confirmed_at=utc_now(),
    )

    logger.info(
        "purchase_marked_paid_by_webhook",
        extra={
            "purchase_id": purchase_id,
            "stripe_checkout_session_id": session_id,
            "stripe_event_id": event_id,
        },
    )
    return True


@app.get("/")
def healthcheck():
    try:
        collection_name = get_firestore_collection_name()
    except EnvironmentConfigError:
        logger.error(
            "webhook_health_configuration_invalid",
            extra={"component": "firestore", "status": "configuration_invalid"},
        )
        return jsonify({"status": "error", "error": "configuration invalid"}), 500

    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        logger.error(
            "webhook_health_configuration_invalid",
            extra={"component": "stripe", "status": "configuration_invalid"},
        )
        return jsonify({"status": "error", "error": "configuration invalid"}), 500

    try:
        get_stripe_settings(secret_key=STRIPE_SECRET_KEY)
    except EnvironmentConfigError:
        logger.error(
            "webhook_health_configuration_invalid",
            extra={"component": "stripe", "status": "configuration_invalid"},
        )
        return jsonify({"status": "error", "error": "configuration invalid"}), 500

    return jsonify(
        {
            "status": "ok",
            "service": "stripe-webhook",
            "collection": collection_name,
        }
    )


@app.post("/stripe/webhook")
def stripe_webhook():
    if not STRIPE_SECRET_KEY:
        logger.error("missing_STRIPE_SECRET_KEY")
        return jsonify({"error": "missing STRIPE_SECRET_KEY"}), 500

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("missing_STRIPE_WEBHOOK_SECRET")
        return jsonify({"error": "missing STRIPE_WEBHOOK_SECRET"}), 500

    try:
        get_stripe_settings(secret_key=STRIPE_SECRET_KEY)
    except EnvironmentConfigError as exc:
        logger.error("stripe_environment_config_error", extra={"reason": str(exc)})
        return jsonify({"error": str(exc)}), 500

    stripe.api_key = STRIPE_SECRET_KEY

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        logger.warning("invalid_webhook_payload")
        return jsonify({"error": "invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        logger.warning("invalid_webhook_signature")
        return jsonify({"error": "invalid signature"}), 400

    event_type = event.get("type")
    event_id = event.get("id")
    event_object = (event.get("data") or {}).get("object") or {}

    logger.info(
        "stripe_webhook_received",
        extra={"event_type": event_type, "stripe_event_id": event_id},
    )

    if event_type == "checkout.session.completed":
        try:
            handled = mark_purchase_paid_from_session(event_object, event_id)
        except EnvironmentConfigError as exc:
            logger.error("webhook_environment_config_error", extra={"reason": str(exc)})
            return jsonify({"error": str(exc)}), 500
        return jsonify({"received": True, "handled": handled}), 200

    return jsonify({"received": True, "ignored_event_type": event_type}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
