from types import SimpleNamespace

import app


def test_direct_checkout_accepts_regular_and_review():
    assert app.should_use_direct_checkout("checkout", "regular", False)
    assert app.should_use_direct_checkout("checkout", "review", False)


def test_direct_checkout_rejects_invalid_or_purchase_return():
    assert not app.should_use_direct_checkout("checkout", "invalid", False)
    assert not app.should_use_direct_checkout("checkout", "review", True)
    assert not app.should_use_direct_checkout("other", "review", False)


def test_review_stripe_readiness_does_not_require_regular_price(monkeypatch):
    stripe_stub = SimpleNamespace(api_key=None)
    monkeypatch.setattr(app, "stripe", stripe_stub)
    monkeypatch.setattr(app, "STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REGULAR", "")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REVIEW", "price_review_test")

    assert app.stripe_client_ready(app.PRODUCT_TYPE_REVIEW)
    assert stripe_stub.api_key == "sk_test_placeholder"


def test_regular_stripe_readiness_requires_regular_price(monkeypatch):
    stripe_stub = SimpleNamespace(api_key=None)
    monkeypatch.setattr(app, "stripe", stripe_stub)
    monkeypatch.setattr(app, "STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REGULAR", "")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REVIEW", "price_review_test")

    assert not app.stripe_client_ready(app.PRODUCT_TYPE_REGULAR)


def test_review_checkout_price_uses_review_price_id(monkeypatch):
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REGULAR", "price_regular_test")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REVIEW", "price_review_test")
    monkeypatch.setattr(app, "STRIPE_PRICE_ID_REVIEW_CAMPAIGN", "")
    monkeypatch.setattr(app, "CAMPAIGN_END_AT", "")

    price_id, amount_jpy = app.get_active_checkout_price(app.PRODUCT_TYPE_REVIEW)

    assert price_id == "price_review_test"
    assert amount_jpy == app.REVIEW_AMOUNT_JPY


def make_streamlit_stub():
    return SimpleNamespace(
        session_state={"checkout_url": None, "checkout_product_type": None},
        markdown=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
    )


def test_regular_direct_checkout_uses_regular_product(monkeypatch):
    calls = []
    streamlit_stub = make_streamlit_stub()

    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "stripe_client_ready", lambda product_type: True)
    monkeypatch.setattr(
        app,
        "get_active_checkout_price",
        lambda product_type, logger: calls.append(("price", product_type)) or ("price_regular", 300),
    )
    monkeypatch.setattr(
        app,
        "create_checkout_session",
        lambda product_type, logger: calls.append(("checkout", product_type))
        or ("https://checkout.example/regular", None),
    )
    monkeypatch.setattr(
        app,
        "render_checkout_link",
        lambda url, amount: calls.append(("link", url, amount)),
    )

    app.render_direct_checkout(app.PRODUCT_TYPE_REGULAR, SimpleNamespace())

    assert calls == [
        ("price", "regular"),
        ("checkout", "regular"),
        ("link", "https://checkout.example/regular", 300),
    ]


def test_review_direct_checkout_uses_review_product_and_minimal_screen(monkeypatch):
    calls = []
    rendered_markdown = []
    rendered_info = []
    streamlit_stub = make_streamlit_stub()
    streamlit_stub.markdown = lambda value, **kwargs: rendered_markdown.append(value)
    streamlit_stub.info = lambda value, **kwargs: rendered_info.append(value)

    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "stripe_client_ready", lambda product_type: True)
    monkeypatch.setattr(
        app,
        "get_active_checkout_price",
        lambda product_type, logger: calls.append(("price", product_type)) or ("price_review", 680),
    )
    monkeypatch.setattr(
        app,
        "create_checkout_session",
        lambda product_type, logger: calls.append(("checkout", product_type))
        or ("https://checkout.example/review", None),
    )
    monkeypatch.setattr(
        app,
        "render_checkout_link",
        lambda url, amount: calls.append(("link", url, amount)),
    )
    monkeypatch.setattr(
        app,
        "render_pre_payment_intro",
        lambda *args, **kwargs: calls.append(("unexpected", "intro")),
    )
    monkeypatch.setattr(
        app,
        "render_usage_flow",
        lambda *args, **kwargs: calls.append(("unexpected", "flow")),
    )
    monkeypatch.setattr(
        app,
        "render_pdf_sample_section",
        lambda *args, **kwargs: calls.append(("unexpected", "samples")),
    )
    monkeypatch.setattr(
        app,
        "render_pdf_contents_summary",
        lambda *args, **kwargs: calls.append(("unexpected", "summary")),
    )

    app.render_direct_checkout(app.PRODUCT_TYPE_REVIEW, SimpleNamespace())

    assert calls == [
        ("price", "review"),
        ("checkout", "review"),
        ("link", "https://checkout.example/review", 680),
    ]
    assert any("龍神さまのお告げ 見返し便" in value for value in rendered_markdown)
    assert any("680円" in value for value in rendered_markdown)
    assert any("見返し便フォーム" in value for value in rendered_info)


class AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def test_tracking_param_normalization_rules(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "product_type": "review",
            "test_mode": "owner",
            "button": "first_view",
            "utm_source": " instagram ",
            "utm_campaign": "x" * 130,
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.get_tracking_params_from_query()

    assert params["product_type"] == "review"
    assert params["test_mode"] == "owner"
    assert params["button_position"] == "top"
    assert params["utm_source"] == "instagram"
    assert len(params["utm_campaign"]) == app.TRACKING_VALUE_MAX_LENGTH


def test_tracking_param_invalid_values_fall_back(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "product_type": "bad",
            "test_mode": "staff",
            "button_position": "side",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.get_tracking_params_from_query()

    assert params["product_type"] == "regular"
    assert params["test_mode"] == "none"
    assert params["button_position"] == "unknown"


def test_button_position_legacy_aliases():
    assert app.normalize_button_position("top") == "top"
    assert app.normalize_button_position("middle") == "middle"
    assert app.normalize_button_position("bottom") == "bottom"
    assert app.normalize_button_position("sample_after") == "middle"
    assert app.normalize_button_position("sumple_after") == "middle"
    assert app.normalize_button_position("unknown_value") == "unknown"


def test_success_url_includes_tracking_params(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="hero",
            test_mode="owner",
            button_position="top",
        ),
        query_params={},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    url = app.build_checkout_success_url("p_1", "token_1", "review")

    assert "session_id={CHECKOUT_SESSION_ID}" in url
    assert "purchase_id=p_1" in url
    assert "product_type=review" in url
    assert "utm_source=instagram" in url
    assert "utm_medium=paid_social" in url
    assert "utm_campaign=summer" in url
    assert "utm_content=hero" in url
    assert "test_mode=owner" in url
    assert "button_position=top" in url
    assert "ga4_client_id" not in url
    assert "ga4_session_id" not in url


def test_create_checkout_session_keeps_existing_metadata_and_adds_tracking(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="cs_test_1", url="https://checkout.example/session")

    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="hero",
            test_mode="owner",
            button_position="top",
        ),
    )
    stripe_stub = SimpleNamespace(
        checkout=SimpleNamespace(Session=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "stripe", stripe_stub)
    monkeypatch.setattr(app, "stripe_client_ready", lambda product_type: True)
    monkeypatch.setattr(app, "get_active_checkout_price", lambda product_type, logger: ("price_review", 680))
    monkeypatch.setattr(
        app,
        "create_purchase_record",
        lambda price_id, amount_jpy, product_type, price_type: {
            "purchase_id": "p_1",
            "_access_token": "token_1",
        },
    )
    monkeypatch.setattr(app, "update_purchase_record", lambda purchase_id, **updates: {})
    monkeypatch.setattr(app, "track_ga4_event", lambda *args, **kwargs: True)

    checkout_url, error = app.create_checkout_session("review", SimpleNamespace(info=lambda *args, **kwargs: None))

    assert error is None
    assert checkout_url == "https://checkout.example/session"
    assert captured["client_reference_id"] == "p_1"
    metadata = captured["metadata"]
    assert metadata["purchase_id"] == "p_1"
    assert metadata["product_type"] == "review"
    assert metadata["price_type"] == "review_regular"
    assert metadata["price_id"] == "price_review"
    assert metadata["amount_jpy"] == "680"
    assert metadata["service_id"] == "ryujin"
    assert metadata["utm_source"] == "instagram"
    assert metadata["test_mode"] == "owner"
    assert metadata["button_position"] == "top"


def test_track_purchase_ga4_event_once_sends_and_marks(monkeypatch):
    calls = []

    monkeypatch.setattr(app, "is_ga4_event_sent", lambda purchase_id, event_name: False)
    monkeypatch.setattr(
        app,
        "track_ga4_event",
        lambda event_name, logger, params: calls.append((event_name, params)) or True,
    )
    monkeypatch.setattr(
        app,
        "mark_ga4_event_sent_if_unset",
        lambda purchase_id, event_name: calls.append(("mark", purchase_id, event_name)) or True,
    )

    sent = app.track_purchase_ga4_event_once(
        "reading_started",
        "p_1",
        "regular",
        SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert sent is True
    assert calls == [
        ("reading_started", {"product_type": "regular"}),
        ("mark", "p_1", "reading_started"),
    ]


def test_track_purchase_ga4_event_once_skips_sent_purchase(monkeypatch):
    calls = []

    monkeypatch.setattr(app, "is_ga4_event_sent", lambda purchase_id, event_name: True)
    monkeypatch.setattr(
        app,
        "track_ga4_event",
        lambda *args, **kwargs: calls.append("track") or True,
    )
    monkeypatch.setattr(
        app,
        "mark_ga4_event_sent_if_unset",
        lambda *args, **kwargs: calls.append("mark") or True,
    )

    handled = app.track_purchase_ga4_event_once(
        "pdf_generated",
        "p_1",
        "review",
        SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert handled is True
    assert calls == []


def test_track_purchase_ga4_event_once_does_not_mark_when_ga4_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(app, "is_ga4_event_sent", lambda purchase_id, event_name: False)
    monkeypatch.setattr(app, "track_ga4_event", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        app,
        "mark_ga4_event_sent_if_unset",
        lambda *args, **kwargs: calls.append("mark") or True,
    )

    sent = app.track_purchase_ga4_event_once(
        "reading_started",
        "p_1",
        "regular",
        SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert sent is False
    assert calls == []
def test_track_ga4_event_passes_wix_client_and_session_ids(monkeypatch):
    captured = {}
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="wix",
            utm_medium="lp",
            utm_campaign="summer",
            utm_content="hero",
            test_mode="owner",
            button_position="top",
            ga4_client_id="1498719245.1765352125",
            ga4_session_id="1786245136",
        ),
        query_params={
            "session_id": "cs_test_1",
            "ga4_client_id": "1498719245.1765352125",
            "ga4_session_id": "1786245136",
            "utm_source": "wix",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "GA4_ENABLED", True)
    monkeypatch.setattr(app, "GA4_MEASUREMENT_ID", "G-TEST")
    monkeypatch.setattr(app, "GA4_API_SECRET", "secret")

    def fake_send_ga4_event(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(app, "send_ga4_event", fake_send_ga4_event)

    sent = app.track_ga4_event("checkout_session_created", SimpleNamespace())

    assert sent is True
    assert captured["client_id"] == "1498719245.1765352125"
    assert captured["session_id"] == "1786245136"
    assert captured["params"]["utm_source"] == "wix"
    assert "cs_test_1" not in captured["params"]["page_location"]
    assert "ga4_client_id" not in captured["params"]["page_location"]
    assert "ga4_session_id" not in captured["params"]["page_location"]

def test_ga4_identifiers_from_query_are_separate_from_tracking(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(ga4_client_id="fallback-client", ga4_session_id=None),
        query_params={
            "ga4_client_id": "1498719245.1765352125",
            "ga4_session_id": "1786245136",
            "session_id": "cs_test_1",
            "utm_source": "wix",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    app.update_ga4_identifiers_from_query()
    tracking_params = app.get_tracking_params_from_query()

    assert streamlit_stub.session_state.ga4_client_id == "1498719245.1765352125"
    assert streamlit_stub.session_state.ga4_session_id == "1786245136"
    assert "ga4_client_id" not in tracking_params
    assert "ga4_session_id" not in tracking_params
    assert "session_id" not in tracking_params
    assert tracking_params["utm_source"] == "wix"


def test_ga4_identifiers_keep_existing_fallback_when_query_missing(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(ga4_client_id="fallback-client", ga4_session_id=None),
        query_params={"session_id": "cs_test_1"},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    app.update_ga4_identifiers_from_query()

    assert streamlit_stub.session_state.ga4_client_id == "fallback-client"
    assert streamlit_stub.session_state.ga4_session_id is None


def test_success_url_includes_ga4_identifiers_when_present(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="hero",
            test_mode="owner",
            button_position="top",
            ga4_client_id="1498719245.1765352125",
            ga4_session_id="1786245136",
        ),
        query_params={},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    url = app.build_checkout_success_url("p_1", "token_1", "review")

    assert "session_id={CHECKOUT_SESSION_ID}" in url
    assert "ga4_client_id=1498719245.1765352125" in url
    assert "ga4_session_id=1786245136" in url
