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
    monkeypatch.setattr(app, "ensure_canonical_origin", lambda: "canonical")
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


def test_render_self_resume_notice_includes_copy_guidance_and_contact(monkeypatch):
    rendered_html = []
    rendered_components = []
    dummy_resume_url = (
        "https://example.test/resume?action=resume&purchase_id=dummy#dummy-token"
    )
    st_stub = SimpleNamespace(
        session_state=AttrDict(
            self_resume_url=dummy_resume_url,
            self_resume_purchase_id="p_self_resume",
        ),
        html=lambda value: rendered_html.append(value),
    )

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(
        app.components,
        "html",
        lambda value, **kwargs: rendered_components.append((value, kwargs)),
    )

    app.render_self_resume_notice(make_purchase())

    notice_html = rendered_html[0]
    copy_html, copy_options = rendered_components[0]
    assert dummy_resume_url not in notice_html
    assert "再開用リンク" not in notice_html
    assert "鑑定を始める前に、再開URLを保存してください" in notice_html
    assert "7日間" in notice_html
    assert "再開期限：" in notice_html
    assert "先に「再開URLをコピー」を押し" in notice_html
    assert "メモ帳アプリなどに貼り付けて保存" in notice_html
    assert "Instagramアプリ内ブラウザなどをご利用の場合" in notice_html
    assert "お問い合わせ" in notice_html
    assert f'href="{app.WIX_CONTACT_URL}"' in notice_html
    assert app.WIX_CONTACT_URL == "https://www.omoshiro-cre8works.com/contact"
    assert "再開URLをコピー" in copy_html
    assert (
        'data-copy-value="https://example.test/resume?action=resume&amp;purchase_id=dummy#dummy-token"'
        in copy_html
    )
    assert "navigator.clipboard.writeText(value)" in copy_html
    assert "copyWithFallback(value)" in copy_html
    assert "await copyResumeUrl(resumeUrl)" in copy_html
    assert '<span id="copy-self-resume-status" role="status" aria-live="polite" hidden>' in copy_html
    assert '<button id="show-self-resume-url" type="button" hidden>' in copy_html
    assert '<div id="manual-copy-container" hidden></div>' in copy_html
    assert """copyStatus.textContent = 'コピーしました。メモ帳などに貼り付けて保存してください。';
                copyStatus.className = 'copy-success';
                copyStatus.hidden = false;
                copyButton.hidden = false;
                showUrlButton.hidden = true;
                manualCopyContainer.hidden = true;""" in copy_html
    assert """copyStatus.textContent = 'コピーできませんでした。';
                copyStatus.className = 'copy-error';
                copyStatus.hidden = false;
                copyButton.hidden = true;
                showUrlButton.hidden = false;
                manualCopyContainer.hidden = true;""" in copy_html
    assert "manualUrl.value = copyButton.dataset.copyValue" in copy_html
    assert "manualUrl.setAttribute('aria-label', '手動コピー用の再開URL')" in copy_html
    assert "manualUrl.readOnly = true" in copy_html
    assert """copyButton.hidden = true;
            copyStatus.hidden = true;
            manualCopyContainer.hidden = false;
            showUrlButton.hidden = true;""" in copy_html
    assert "manualUrl.focus()" in copy_html
    assert "manualUrl.select()" in copy_html
    assert "flex-basis: 100%" in copy_html
    assert "height: 4rem" in copy_html
    assert "resize: none" in copy_html
    assert "ブックマーク" not in notice_html
    assert "ブックマーク" not in copy_html
    assert copy_options == {"height": 104, "scrolling": False}


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
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }
    st_stub.session_state.active_purchase_id = "p_previous"
    st_stub.session_state.active_access_token = "previous_token"
    st_stub.session_state.self_resume_url = "https://example.test/previous"
    st_stub.session_state.self_resume_purchase_id = "p_previous"
    cleanups = []

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "read_fragment_token_from_browser", lambda purchase_id: ("token_b", "received"))
    monkeypatch.setattr(app, "get_purchase_by_access_token", lambda token: {"purchase_id": "p_b"})
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: pytest.fail("must not fallback"))
    monkeypatch.setattr(
        app,
        "cleanup_self_resume_token",
        lambda purchase_id, reason="done": cleanups.append((purchase_id, reason)),
    )

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.active_purchase_id is None
    assert st_stub.session_state.active_access_token is None
    assert st_stub.session_state.self_resume_url is None
    assert st_stub.session_state.self_resume_purchase_id is None
    assert st_stub.query_params == {}
    assert cleanups == [("p_a", "invalid")]


def test_self_resume_fragment_pending_does_not_fallback_to_active_purchase(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "purchase_id": "p_a",
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }
    st_stub.session_state.active_purchase_id = "p_previous"
    st_stub.session_state.active_access_token = "previous_token"
    st_stub.session_state.self_resume_url = "https://example.test/previous"
    st_stub.session_state.self_resume_purchase_id = "p_previous"

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "read_fragment_token_from_browser", lambda purchase_id: (None, "pending"))
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: pytest.fail("must not fallback"))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.active_purchase_id is None
    assert st_stub.session_state.active_access_token is None
    assert st_stub.session_state.self_resume_url is None
    assert st_stub.session_state.self_resume_purchase_id is None
    assert st_stub.session_state.purchase_token_pending is True
    assert st_stub.session_state.purchase_token_missing is False


def test_self_resume_reload_accepts_short_lived_session_token_and_keeps_routing_query(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "purchase_id": "p_reload",
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }
    purchase = make_purchase(purchase_id="p_reload")
    validated_tokens = []

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(
        app,
        "read_fragment_token_from_browser",
        lambda purchase_id: ("dummy_reload_token", "received"),
    )
    monkeypatch.setattr(
        app,
        "get_purchase_by_access_token",
        lambda token: validated_tokens.append(token) or purchase,
    )

    assert app.get_current_purchase_record() == purchase
    assert validated_tokens == ["dummy_reload_token"]
    assert st_stub.session_state.active_purchase_id == "p_reload"
    assert st_stub.session_state.active_access_token == "dummy_reload_token"
    assert st_stub.query_params == {
        "purchase_id": "p_reload",
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }
    assert "access_token" not in st_stub.query_params


@pytest.mark.parametrize("token_status", ["missing", "stale", "malformed", "error"])
def test_self_resume_missing_or_unusable_session_token_shows_recovery_state(
    monkeypatch,
    token_status,
):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "purchase_id": "p_reload",
        "product_type": app.PRODUCT_TYPE_REGULAR,
        "action": "resume",
    }

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(
        app,
        "read_fragment_token_from_browser",
        lambda purchase_id: (None, token_status),
    )
    monkeypatch.setattr(
        app,
        "get_purchase_by_access_token",
        lambda token: pytest.fail("missing token must not be authenticated"),
    )

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.purchase_token_pending is False
    assert st_stub.session_state.purchase_token_missing is True
    assert st_stub.session_state.purchase_token_auth_failed is False
    assert st_stub.query_params["action"] == "resume"


def test_self_resume_missing_state_renders_recovery_guidance(monkeypatch):
    st_stub, calls = setup_main_route(monkeypatch, None)
    st_stub.session_state.purchase_token_missing = True
    monkeypatch.setattr(app, "finalize_interrupted_pdf_generation_if_ready", lambda purchase, logger: None)
    monkeypatch.setattr(app, "render_pdf_recovery_screen", lambda purchase, logger: False)

    app.main()

    assert (
        "warning",
        "再開情報を確認できませんでした。保存してある再開URLをもう一度開いてください。",
    ) in st_stub.calls
    assert not any(call[0] in {"regular_form", "review_form", "payment"} for call in calls)


def test_self_resume_fragment_reader_uses_separate_short_lived_storage(monkeypatch):
    captured = {}

    def mount(action, **kwargs):
        captured["action"] = action
        captured.update(kwargs)
        return {"status": "received", "token": "dummy_fragment_token"}

    monkeypatch.setattr(app, "mount_token_bridge", mount)

    assert app.read_fragment_token_from_browser("p_dummy") == (
        "dummy_fragment_token",
        "received",
    )
    assert captured == {
        "action": "read_fragment",
        "purchase_id": "p_dummy",
        "key_suffix": "p_dummy",
        "storage_prefix": app.SELF_RESUME_TOKEN_STORAGE_PREFIX,
        "ttl_seconds": app.SELF_RESUME_TOKEN_TTL_SECONDS,
    }
    assert app.SELF_RESUME_TOKEN_STORAGE_PREFIX != app.PENDING_CHECKOUT_TOKEN_STORAGE_PREFIX
    assert app.SELF_RESUME_TOKEN_TTL_SECONDS == 2 * 60 * 60


def test_self_resume_fragment_bridge_stores_before_cleanup_without_long_lived_storage():
    script = app.TOKEN_BRIDGE_JS

    fragment_branch = script.split('if (payload.action === "read_fragment") {', 1)[1]
    assert "storeToken(purchaseId, token);" in fragment_branch
    assert fragment_branch.index("storeToken(purchaseId, token);") < fragment_branch.index(
        "cleanupFragment();", fragment_branch.index("storeToken(purchaseId, token);")
    )
    assert "readStoredToken(purchaseId)" in fragment_branch
    assert "history.replaceState" in script
    assert "sessionStorage" in script
    assert "localStorage" not in script
    assert "console." not in script


def test_success_return_accepts_session_storage_token_for_same_purchase(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "session_id": "cs_test_1",
        "purchase_id": "p_success",
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    cleanups = []
    purchase = make_purchase(purchase_id="p_success")

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "sync_purchase_from_session", lambda session_id, logger: purchase)
    monkeypatch.setattr(app, "read_checkout_token_from_browser", lambda purchase_id: ("token_success", "received"))
    monkeypatch.setattr(app, "get_purchase_by_access_token", lambda token: {"purchase_id": "p_success"})
    monkeypatch.setattr(app, "cleanup_pending_checkout_token", lambda purchase_id, reason="done": cleanups.append((purchase_id, reason)))

    assert app.get_current_purchase_record() == purchase
    assert st_stub.session_state.active_purchase_id == "p_success"
    assert st_stub.session_state.active_access_token == "token_success"
    assert "access_token" not in st_stub.query_params
    assert st_stub.query_params == {}
    assert cleanups == [("p_success", "success")]


def test_success_return_rejects_query_purchase_mismatch(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "session_id": "cs_test_1",
        "purchase_id": "p_query",
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    cleanups = []
    purchase = make_purchase(purchase_id="p_session")

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "sync_purchase_from_session", lambda session_id, logger: purchase)
    monkeypatch.setattr(app, "read_checkout_token_from_browser", lambda purchase_id: pytest.fail("must not read token"))
    monkeypatch.setattr(app, "cleanup_pending_checkout_token", lambda purchase_id, reason="done": cleanups.append((purchase_id, reason)))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.purchase_token_auth_failed is True
    assert st_stub.query_params == {}
    assert cleanups == [("p_query", "mismatch")]


def test_success_return_rejects_missing_query_purchase_id(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "session_id": "cs_test_1",
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    cleanups = []
    purchase = make_purchase(purchase_id="p_session")

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "sync_purchase_from_session", lambda session_id, logger: purchase)
    monkeypatch.setattr(app, "read_checkout_token_from_browser", lambda purchase_id: pytest.fail("must not read token"))
    monkeypatch.setattr(app, "cleanup_pending_checkout_token", lambda purchase_id, reason="done": cleanups.append((purchase_id, reason)))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.purchase_token_auth_failed is True
    assert st_stub.query_params == {}
    assert cleanups == [("p_session", "mismatch")]


def test_success_return_rejects_invalid_session_storage_token(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "session_id": "cs_test_1",
        "purchase_id": "p_success",
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    cleanups = []
    purchase = make_purchase(purchase_id="p_success")

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "sync_purchase_from_session", lambda session_id, logger: purchase)
    monkeypatch.setattr(app, "read_checkout_token_from_browser", lambda purchase_id: ("wrong_token", "received"))
    monkeypatch.setattr(app, "get_purchase_by_access_token", lambda token: None)
    monkeypatch.setattr(app, "cleanup_pending_checkout_token", lambda purchase_id, reason="done": cleanups.append((purchase_id, reason)))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.purchase_token_auth_failed is True
    assert st_stub.session_state.active_purchase_id is None
    assert st_stub.query_params == {}
    assert cleanups == [("p_success", "invalid")]


def test_success_return_stale_session_storage_token_is_rejected(monkeypatch):
    st_stub = make_streamlit_stub()
    st_stub.query_params = {
        "session_id": "cs_test_1",
        "purchase_id": "p_success",
        "product_type": app.PRODUCT_TYPE_REGULAR,
    }
    purchase = make_purchase(purchase_id="p_success")

    monkeypatch.setattr(app, "st", st_stub)
    monkeypatch.setattr(app, "sync_purchase_from_session", lambda session_id, logger: purchase)
    monkeypatch.setattr(app, "read_checkout_token_from_browser", lambda purchase_id: (None, "stale"))
    monkeypatch.setattr(app, "get_purchase_by_access_token", lambda token: pytest.fail("must not authenticate stale token"))

    assert app.get_current_purchase_record() is None
    assert st_stub.session_state.purchase_token_auth_failed is True


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
