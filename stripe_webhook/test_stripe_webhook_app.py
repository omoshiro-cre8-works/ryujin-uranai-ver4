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
