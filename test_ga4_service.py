import urllib.error

from services import ga4_service


def test_ga4_disabled_returns_false_without_request(monkeypatch):
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    assert ga4_service.send_ga4_event(
        event_name="streamlit_page_view",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=False,
        params={"service_id": "ryujin"},
    ) is False
    assert called is False


def test_ga4_send_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        ga4_service.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )

    assert ga4_service.send_ga4_event(
        event_name="streamlit_page_view",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
    ) is False


def test_ga4_clean_event_params_truncates_string_values():
    params = ga4_service._clean_event_params({"utm_campaign": "x" * 130, "amount_jpy": 680})

    assert len(params["utm_campaign"]) == ga4_service.GA4_PARAM_VALUE_MAX_LENGTH
    assert params["amount_jpy"] == 680
