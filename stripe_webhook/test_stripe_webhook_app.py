import sys
import types
from types import SimpleNamespace


if "flask" not in sys.modules:
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
    stripe_module = types.ModuleType("stripe")
    stripe_module.api_key = None
    stripe_module.Webhook = SimpleNamespace(construct_event=lambda **kwargs: {})
    stripe_module.error = SimpleNamespace(SignatureVerificationError=Exception)
    sys.modules["stripe"] = stripe_module

if "google.cloud.firestore" not in sys.modules:
    google_module = sys.modules.setdefault("google", types.ModuleType("google"))
    cloud_module = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
    firestore_module = types.ModuleType("google.cloud.firestore")
    firestore_module.Client = lambda: None
    cloud_module.firestore = firestore_module
    google_module.cloud = cloud_module
    sys.modules["google.cloud.firestore"] = firestore_module

from stripe_webhook import stripe_webhook_app


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
