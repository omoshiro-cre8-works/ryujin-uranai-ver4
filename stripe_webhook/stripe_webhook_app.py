import datetime
import logging
import os
from typing import Any

from flask import Flask, jsonify, request
from google.cloud import firestore
import stripe

app = Flask(__name__)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FIRESTORE_COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION_NAME", "purchases")

stripe.api_key = STRIPE_SECRET_KEY


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def get_firestore_client() -> firestore.Client:
    return firestore.Client()


def get_purchase_doc_ref(purchase_id: str):
    db = get_firestore_client()
    return db.collection(FIRESTORE_COLLECTION_NAME).document(purchase_id)


def get_purchase_record(purchase_id: str) -> dict[str, Any] | None:
    snapshot = get_purchase_doc_ref(purchase_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict() or {}


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
    purchase_id = metadata.get("purchase_id") or session.get("client_reference_id")
    if not purchase_id:
        logger.warning("purchase_id_not_found_in_session")
        return False

    record = get_purchase_record(purchase_id)
    if not record:
        logger.warning("purchase_record_not_found", extra={"purchase_id": purchase_id})
        return False

    existing_event_id = record.get("stripe_event_id")
    if existing_event_id and event_id and existing_event_id == event_id:
        logger.info(
            "duplicate_webhook_event_ignored",
            extra={"purchase_id": purchase_id, "stripe_event_id": event_id},
        )
        return True

    payment_status = session.get("payment_status")
    status = session.get("status")

    if payment_status != "paid" and status != "complete":
        logger.info(
            "session_not_paid_yet",
            extra={
                "purchase_id": purchase_id,
                "payment_status": payment_status,
                "status": status,
            },
        )
        return False

    update_purchase_record(
        purchase_id,
        payment_status="paid",
        stripe_checkout_session_id=session.get("id"),
        stripe_event_id=event_id,
        amount_total=session.get("amount_total"),
        currency=session.get("currency"),
        checkout_completed_at=utc_now(),
        webhook_confirmed_at=utc_now(),
    )

    logger.info(
        "purchase_marked_paid_by_webhook",
        extra={
            "purchase_id": purchase_id,
            "stripe_checkout_session_id": session.get("id"),
            "stripe_event_id": event_id,
        },
    )
    return True


@app.get("/")
def healthcheck():
    return jsonify(
        {
            "status": "ok",
            "service": "stripe-webhook",
            "collection": FIRESTORE_COLLECTION_NAME,
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
        handled = mark_purchase_paid_from_session(event_object, event_id)
        return jsonify({"received": True, "handled": handled}), 200

    return jsonify({"received": True, "ignored_event_type": event_type}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
