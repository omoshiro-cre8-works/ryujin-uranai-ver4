import datetime
from types import SimpleNamespace

import pytest

import app


class AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class StopCalled(RuntimeError):
    pass


def make_streamlit_stub() -> SimpleNamespace:
    calls = []
    return SimpleNamespace(
        calls=calls,
        session_state=AttrDict(),
        query_params={},
        set_page_config=lambda **kwargs: calls.append(("set_page_config", kwargs)),
        divider=lambda: calls.append(("divider", None)),
        info=lambda value, **kwargs: calls.append(("info", value)),
        warning=lambda value, **kwargs: calls.append(("warning", value)),
        stop=lambda: (_ for _ in ()).throw(StopCalled()),
    )


def make_purchase(**updates):
    now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    purchase = {
        "purchase_id": "p_self_resume",
        "payment_status": "paid",
        "used_flag": False,
        "generation_processing": False,
        "checkout_completed_at": now - datetime.timedelta(days=1),
        "token_expires_at": now + datetime.timedelta(days=6),
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    purchase.update(updates)
    return purchase


def setup_main_route(monkeypatch, active_purchase):
    st_stub = make_streamlit_stub()
    calls = []

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "configure_logging", lambda: None)
    monkeypatch.setattr(app, "render_app_css", lambda: None)
    monkeypatch.setattr(app, "init_session_state", lambda: None)
    monkeypatch.setattr(app, "update_ga4_identifiers_from_query", lambda: None)
    monkeypatch.setattr(app, "update_tracking_session_state_from_query", lambda: None)
    monkeypatch.setattr(app, "has_purchase_return_query_params", lambda: False)
    monkeypatch.setattr(app, "is_direct_checkout_request", lambda: False)
    monkeypatch.setattr(app, "get_current_purchase_record", lambda: active_purchase)
    monkeypatch.setattr(app, "get_requested_product_type", lambda: app.PRODUCT_TYPE_REGULAR)
    monkeypatch.setattr(app, "track_streamlit_page_view", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_header", lambda *args, **kwargs: calls.append(("header", args, kwargs)))
    monkeypatch.setattr(app, "render_self_resume_notice", lambda purchase: calls.append(("resume_notice", purchase)))
    monkeypatch.setattr(app, "render_fortune_form", lambda purchase, logger: calls.append(("regular_form", purchase)))
    monkeypatch.setattr(app, "render_review_fortune_form", lambda purchase, logger: calls.append(("review_form", purchase)))
    monkeypatch.setattr(app, "render_generation_processing_screen", lambda purchase: calls.append(("processing", purchase)))
    monkeypatch.setattr(app, "render_completion_screen", lambda product_type: calls.append(("completion", product_type)))
    monkeypatch.setattr(app, "render_payment_section", lambda *args, **kwargs: calls.append(("payment", args, kwargs)))
    monkeypatch.setattr(app, "render_notice_box", lambda: calls.append(("notice", None)))
    monkeypatch.setattr(app, "render_form_gap", lambda value: calls.append(("gap", value)))
    monkeypatch.setattr(app, "utc_now", lambda: datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc))
    return st_stub, calls


def test_self_resume_valid_paid_unused_within_window_routes_to_form(monkeypatch):
    _, calls = setup_main_route(monkeypatch, make_purchase())
    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", lambda purchase, logger: None)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: False)

    app.main()

    assert ("regular_form", make_purchase()) in calls
    assert not any(call[0] == "processing" for call in calls)


def test_self_resume_processing_routes_to_processing_without_form(monkeypatch):
    _, calls = setup_main_route(monkeypatch, make_purchase(generation_processing=True))
    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", lambda purchase, logger: None)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: False)

    app.main()

    assert any(call[0] == "processing" for call in calls)
    assert not any(call[0] in {"regular_form", "review_form"} for call in calls)


def test_self_resume_expired_purchase_does_not_route_to_form(monkeypatch):
    _, calls = setup_main_route(
        monkeypatch,
        make_purchase(
            checkout_completed_at=datetime.datetime(2025, 12, 20, tzinfo=datetime.timezone.utc),
            token_expires_at=datetime.datetime(2025, 12, 27, tzinfo=datetime.timezone.utc),
        ),
    )
    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", lambda purchase, logger: None)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: False)

    app.main()

    assert not any(call[0] in {"regular_form", "review_form", "processing"} for call in calls)


def test_purchase_id_token_mismatch_does_not_fallback_to_active_purchase(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "purchase_id": "p_a",
        "access_token": "token_b",
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }
    st_stub.session_state.active_purchase_id = "p_previous"
    st_stub.session_state.active_access_token = "previous_token"
    st_stub.session_state.self_resume_url = "https://example.test/previous"
    st_stub.session_state.self_resume_purchase_id = "p_previous"

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "get_purchase_by_access_token", lambda token: {"purchase_id": "p_b"})
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: pytest.fail("must not fallback"))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.active_purchase_id is None
    assert st_stub.session_state.active_access_token is None
    assert st_stub.session_state.self_resume_url is None
    assert st_stub.session_state.self_resume_purchase_id is None
    assert st_stub.query_params == {}


def test_used_ready_pdf_routes_to_pdf_recovery(monkeypatch):
    _, calls = setup_main_route(monkeypatch, make_purchase(used_flag=True, pdf_status="ready"))
    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", lambda purchase, logger: None)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: calls.append(("pdf_recovery", purchase)) or True)

    with pytest.raises(StopCalled):
        app.main()

    assert any(call[0] == "pdf_recovery" for call in calls)
    assert not any(call[0] in {"regular_form", "review_form"} for call in calls)


def test_processing_ready_pdf_finalizes_before_processing_screen(monkeypatch):
    active_purchase = make_purchase(generation_processing=True, pdf_status="ready")
    finalized_purchase = make_purchase(used_flag=True, generation_processing=False, pdf_status="ready")
    _, calls = setup_main_route(monkeypatch, active_purchase)

    def finalize(purchase, logger):
        calls.append(("finalize", purchase))
        return finalized_purchase

    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", finalize)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: calls.append(("pdf_recovery", purchase)) or True)

    with pytest.raises(StopCalled):
        app.main()

    assert any(call[0] == "finalize" for call in calls)
    assert any(call[0] == "pdf_recovery" for call in calls)
    assert not any(call[0] == "processing" for call in calls)
