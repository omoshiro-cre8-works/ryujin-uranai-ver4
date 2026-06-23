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
