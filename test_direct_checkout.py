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


def test_tracking_param_sample_bottom_is_kept_from_query(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "button_position": "sample_bottom",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.get_tracking_params_from_query()

    assert params["button_position"] == "sample_bottom"


def test_button_position_legacy_aliases():
    assert app.normalize_button_position("top") == "top"
    assert app.normalize_button_position("middle") == "middle"
    assert app.normalize_button_position("bottom") == "bottom"
    assert app.normalize_button_position("sample_bottom") == "sample_bottom"
    assert app.normalize_button_position("sample_after") == "middle"
    assert app.normalize_button_position("sumple_after") == "middle"
    assert app.normalize_button_position("unknown_value") == "unknown"


def test_lp_value_normalization_rules():
    assert app.normalize_lp_value("lp_d") == "lp_d"
    assert app.normalize_lp_value("lp_campaign_01") == "lp_campaign_01"
    assert app.normalize_lp_value("direct_or_unknown") == "direct_or_unknown"
    assert app.normalize_lp_value("lp_") == "direct_or_unknown"
    assert app.normalize_lp_value("LP_D") == "lp_d"
    assert app.normalize_lp_value("lp-campaign") == "direct_or_unknown"
    assert app.normalize_lp_value("/ai-uranai") == "direct_or_unknown"
    assert app.normalize_lp_value("lp_" + "a" * 29) == "lp_" + "a" * 29
    assert app.normalize_lp_value("lp_" + "a" * 30) == "direct_or_unknown"
    assert app.normalize_lp_value("lp_d\x00") == "lp_d"


def test_query_builds_entry_fields_from_new_params(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "entry_lp": "lp_d",
            "entry_utm_source": "instagram",
            "entry_utm_medium": "paid_social",
            "entry_utm_campaign": "summer",
            "entry_utm_content": "lp_d_ad",
            "current_lp": "lp_a",
            "utm_content": "lp_a",
            "button_position": "bottom",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.get_tracking_params_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["entry_utm_source"] == "instagram"
    assert params["entry_utm_medium"] == "paid_social"
    assert params["entry_utm_campaign"] == "summer"
    assert params["entry_utm_content"] == "lp_d_ad"
    assert params["current_lp"] == "lp_a"
    assert params["utm_content"] == "lp_a"
    assert params["button_position"] == "bottom"


def test_legacy_url_derives_entry_and_current_lp_from_utm_content(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "utm_source": "instagram",
            "utm_medium": "paid_social",
            "utm_campaign": "summer",
            "utm_content": "lp_d",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.get_tracking_params_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["current_lp"] == "lp_d"
    assert params["entry_utm_source"] == "instagram"
    assert params["entry_utm_medium"] == "paid_social"
    assert params["entry_utm_campaign"] == "summer"
    assert params["entry_utm_content"] == "lp_d"


def test_direct_or_unknown_does_not_overwrite_existing_entry_lp(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="regular",
            utm_source="",
            utm_medium="",
            utm_campaign="",
            utm_content="",
            entry_lp="lp_d",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="summer",
            entry_utm_content="lp_d_ad",
            current_lp="lp_d",
            test_mode="none",
            button_position="top",
        ),
        query_params={
            "entry_lp": "direct_or_unknown",
            "current_lp": "lp_a",
            "button_position": "bottom",
            "utm_content": "lp_a",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.update_tracking_session_state_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["entry_utm_source"] == "instagram"
    assert params["current_lp"] == "lp_a"
    assert params["button_position"] == "bottom"
    assert params["utm_content"] == "lp_a"


def test_legacy_lp_a_does_not_overwrite_existing_entry_lp(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="regular",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="lp_d_ad",
            entry_lp="lp_d",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="summer",
            entry_utm_content="lp_d_ad",
            current_lp="lp_d",
            test_mode="none",
            button_position="top",
        ),
        query_params={
            "utm_source": "instagram",
            "utm_medium": "paid_social",
            "utm_campaign": "canonical",
            "utm_content": "lp_a",
            "current_lp": "lp_a",
            "button_position": "bottom",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.update_tracking_session_state_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["entry_utm_campaign"] == "summer"
    assert params["current_lp"] == "lp_a"
    assert params["utm_content"] == "lp_a"
    assert params["utm_campaign"] == "canonical"
    assert params["button_position"] == "bottom"


def test_missing_entry_lp_does_not_overwrite_existing_entry_lp(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            entry_lp="lp_e",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="autumn",
            entry_utm_content="lp_e_ad",
            current_lp="lp_e",
        ),
        query_params={
            "current_lp": "lp_a",
            "button_position": "middle",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.update_tracking_session_state_from_query()

    assert params["entry_lp"] == "lp_e"
    assert params["entry_utm_source"] == "instagram"
    assert params["current_lp"] == "lp_a"
    assert params["button_position"] == "middle"


def test_explicit_valid_entry_lp_overwrites_direct_or_unknown(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(entry_lp="direct_or_unknown", current_lp="direct_or_unknown"),
        query_params={
            "entry_lp": "lp_d",
            "entry_utm_source": "instagram",
            "entry_utm_medium": "paid_social",
            "entry_utm_campaign": "summer",
            "current_lp": "lp_d",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.update_tracking_session_state_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["entry_utm_source"] == "instagram"
    assert params["current_lp"] == "lp_d"


def test_missing_session_entry_lp_adopts_legacy_utm_content(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(),
        query_params={
            "utm_source": "instagram",
            "utm_medium": "paid_social",
            "utm_campaign": "summer",
            "utm_content": "lp_d",
            "button_position": "top",
        },
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.update_tracking_session_state_from_query()

    assert params["entry_lp"] == "lp_d"
    assert params["current_lp"] == "lp_d"
    assert params["entry_utm_source"] == "instagram"
    assert params["button_position"] == "top"


def test_success_url_includes_tracking_params(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="hero",
            entry_lp="lp_d",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="summer",
            entry_utm_content="lp_d_ad",
            current_lp="lp_a",
            test_mode="owner",
            button_position="top",
            ga4_client_id_received=True,
            ga4_session_id_received=True,
            ga4_client_id_source="wix",
            ga4_session_linkable=True,
            ga4_checkout_request_status="not_attempted",
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
    assert "entry_lp=lp_d" in url
    assert "entry_utm_source=instagram" in url
    assert "entry_utm_medium=paid_social" in url
    assert "entry_utm_campaign=summer" in url
    assert "entry_utm_content=lp_d_ad" in url
    assert "current_lp=lp_a" in url
    assert "test_mode=owner" in url
    assert "button_position=top" in url
    assert "ga4_client_id" not in url
    assert "ga4_session_id" not in url
    assert "ga4_client_id_received" not in url


def test_tracking_params_for_storage_keeps_sample_bottom(monkeypatch):
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="wix",
            utm_medium="lp",
            utm_campaign="sample",
            utm_content="sample_popup",
            entry_lp="lp_e",
            entry_utm_source="wix",
            entry_utm_medium="lp",
            entry_utm_campaign="sample",
            entry_utm_content="sample_popup",
            current_lp="lp_e",
            test_mode="none",
            button_position="sample_bottom",
            ga4_client_id_received=True,
            ga4_session_id_received=True,
            ga4_client_id_source="wix",
            ga4_session_linkable=True,
            ga4_checkout_request_status="not_attempted",
        ),
        query_params={},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    params = app.tracking_params_for_storage("review")

    assert params["button_position"] == "sample_bottom"
    assert params["entry_lp"] == "lp_e"
    assert params["current_lp"] == "lp_e"
    assert params["ga4_client_id_received"] is True
    assert params["ga4_session_linkable"] is True


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
            entry_lp="lp_d",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="summer",
            entry_utm_content="lp_d_ad",
            current_lp="lp_a",
            test_mode="owner",
            button_position="top",
            ga4_client_id="1498719245.1765352125",
            ga4_session_id="1786245136",
            ga4_client_id_received=True,
            ga4_session_id_received=True,
            ga4_client_id_source="wix",
            ga4_session_linkable=True,
            ga4_checkout_request_status="not_attempted",
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
    monkeypatch.setattr(
        app,
        "track_ga4_event_with_status",
        lambda *args, **kwargs: {"sent": True, "status": "request_accepted"},
    )

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
    assert metadata["entry_lp"] == "lp_d"
    assert metadata["entry_utm_source"] == "instagram"
    assert metadata["entry_utm_medium"] == "paid_social"
    assert metadata["entry_utm_campaign"] == "summer"
    assert metadata["entry_utm_content"] == "lp_d_ad"
    assert metadata["current_lp"] == "lp_a"
    assert metadata["test_mode"] == "owner"
    assert metadata["button_position"] == "top"
    assert "ga4_client_id" not in metadata
    assert "ga4_session_id" not in metadata
    assert "ga4_client_id_received" not in metadata
    assert "ga4_checkout_request_status" not in metadata


def test_create_checkout_session_keeps_sample_bottom_in_metadata(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="cs_test_1", url="https://checkout.example/session")

    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="wix",
            utm_medium="lp",
            utm_campaign="sample",
            utm_content="sample_popup",
            entry_lp="lp_e",
            entry_utm_source="wix",
            entry_utm_medium="lp",
            entry_utm_campaign="sample",
            entry_utm_content="sample_popup",
            current_lp="lp_e",
            test_mode="none",
            button_position="sample_bottom",
            ga4_client_id_received=True,
            ga4_session_id_received=True,
            ga4_client_id_source="wix",
            ga4_session_linkable=True,
            ga4_checkout_request_status="not_attempted",
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
    monkeypatch.setattr(
        app,
        "track_ga4_event_with_status",
        lambda *args, **kwargs: {"sent": True, "status": "request_accepted"},
    )

    checkout_url, error = app.create_checkout_session("review", SimpleNamespace(info=lambda *args, **kwargs: None))

    assert error is None
    assert checkout_url == "https://checkout.example/session"
    assert captured["metadata"]["button_position"] == "sample_bottom"
    assert captured["metadata"]["entry_lp"] == "lp_e"
    assert captured["metadata"]["current_lp"] == "lp_e"


def test_checkout_ga4_status_update_failure_does_not_block_checkout(monkeypatch):
    captured = {}
    warnings = []

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="cs_test_1", url="https://checkout.example/session")

    def fake_update_purchase_record(purchase_id, **updates):
        if "ga4_checkout_request_status" in updates:
            raise RuntimeError("firestore unavailable")
        return {}

    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="regular",
            utm_source="",
            utm_medium="",
            utm_campaign="",
            utm_content="lp_e",
            entry_lp="lp_e",
            entry_utm_source="",
            entry_utm_medium="",
            entry_utm_campaign="",
            entry_utm_content="",
            current_lp="lp_e",
            test_mode="none",
            button_position="sample_bottom",
            ga4_client_id="fallback-client",
            ga4_session_id=None,
            ga4_client_id_received=False,
            ga4_session_id_received=False,
            ga4_client_id_source="generated",
            ga4_session_linkable=False,
            ga4_checkout_request_status="not_attempted",
        ),
        query_params={},
    )
    stripe_stub = SimpleNamespace(
        checkout=SimpleNamespace(Session=SimpleNamespace(create=fake_create))
    )
    logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "stripe", stripe_stub)
    monkeypatch.setattr(app, "stripe_client_ready", lambda product_type: True)
    monkeypatch.setattr(app, "get_active_checkout_price", lambda product_type, logger: ("price_regular", 300))
    monkeypatch.setattr(
        app,
        "create_purchase_record",
        lambda price_id, amount_jpy, product_type, price_type: {
            "purchase_id": "p_1",
            "_access_token": "token_1",
        },
    )
    monkeypatch.setattr(app, "update_purchase_record", fake_update_purchase_record)
    monkeypatch.setattr(
        app,
        "track_ga4_event_with_status",
        lambda *args, **kwargs: {"sent": False, "status": "transport_failed"},
    )

    checkout_url, error = app.create_checkout_session("regular", logger)

    assert error is None
    assert checkout_url == "https://checkout.example/session"
    assert captured["metadata"]["button_position"] == "sample_bottom"
    assert streamlit_stub.session_state.ga4_checkout_request_status == "transport_failed"
    assert warnings


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
        return {"sent": True, "status": "request_accepted"}

    monkeypatch.setattr(app, "send_ga4_event_with_status", fake_send_ga4_event)

    sent = app.track_ga4_event("checkout_session_created", SimpleNamespace())

    assert sent is True
    assert captured["client_id"] == "1498719245.1765352125"
    assert captured["session_id"] == "1786245136"
    assert captured["params"]["utm_source"] == "wix"
    assert "cs_test_1" not in captured["params"]["page_location"]
    assert "ga4_client_id" not in captured["params"]["page_location"]
    assert "ga4_session_id" not in captured["params"]["page_location"]


def test_track_ga4_event_keeps_sample_bottom(monkeypatch):
    captured = {}
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="review",
            utm_source="wix",
            utm_medium="lp",
            utm_campaign="sample",
            utm_content="sample_popup",
            test_mode="none",
            button_position="sample_bottom",
            ga4_client_id="1498719245.1765352125",
            ga4_session_id="1786245136",
        ),
        query_params={},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "GA4_ENABLED", True)
    monkeypatch.setattr(app, "GA4_MEASUREMENT_ID", "G-TEST")
    monkeypatch.setattr(app, "GA4_API_SECRET", "secret")

    def fake_send_ga4_event(**kwargs):
        captured.update(kwargs)
        return {"sent": True, "status": "request_accepted"}

    monkeypatch.setattr(app, "send_ga4_event_with_status", fake_send_ga4_event)

    sent = app.track_ga4_event("checkout_session_created", SimpleNamespace())

    assert sent is True
    assert captured["params"]["button_position"] == "sample_bottom"


def test_track_ga4_event_adds_entry_current_and_observation_params(monkeypatch):
    captured = {}
    streamlit_stub = SimpleNamespace(
        session_state=AttrDict(
            service_id="ryujin",
            product_type="regular",
            utm_source="instagram",
            utm_medium="paid_social",
            utm_campaign="summer",
            utm_content="lp_a",
            entry_lp="lp_d",
            entry_utm_source="instagram",
            entry_utm_medium="paid_social",
            entry_utm_campaign="summer",
            entry_utm_content="lp_d_ad",
            current_lp="lp_a",
            test_mode="owner",
            button_position="bottom",
            ga4_client_id="1498719245.1765352125",
            ga4_session_id="1786245136",
            ga4_client_id_received=True,
            ga4_session_id_received=True,
            ga4_client_id_source="wix",
            ga4_session_linkable=True,
            ga4_checkout_request_status="not_attempted",
        ),
        query_params={},
    )
    monkeypatch.setattr(app, "st", streamlit_stub)

    def fake_send_ga4_event(**kwargs):
        captured.update(kwargs)
        return {"sent": True, "status": "request_accepted"}

    monkeypatch.setattr(app, "send_ga4_event_with_status", fake_send_ga4_event)

    result = app.track_ga4_event_with_status("checkout_session_created", SimpleNamespace())

    assert result["status"] == "request_accepted"
    params = captured["params"]
    assert params["entry_lp"] == "lp_d"
    assert params["current_lp"] == "lp_a"
    assert params["button_position"] == "bottom"
    assert params["ga4_client_id_received"] is True
    assert params["ga4_session_id_received"] is True
    assert params["ga4_client_id_source"] == "wix"
    assert params["ga4_session_linkable"] is True
    assert params["ga4_checkout_request_status"] == "not_attempted"
    assert "ga4_client_id" not in params
    assert "ga4_session_id" not in params


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
    assert streamlit_stub.session_state.ga4_client_id_received is True
    assert streamlit_stub.session_state.ga4_session_id_received is True
    assert streamlit_stub.session_state.ga4_client_id_source == "wix"
    assert streamlit_stub.session_state.ga4_session_linkable is True
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
    assert streamlit_stub.session_state.ga4_client_id_received is False
    assert streamlit_stub.session_state.ga4_session_id_received is False
    assert streamlit_stub.session_state.ga4_client_id_source == "generated"
    assert streamlit_stub.session_state.ga4_session_linkable is False


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
