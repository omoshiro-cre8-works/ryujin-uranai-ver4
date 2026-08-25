import json
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


def test_ga4_disabled_status_without_request(monkeypatch):
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=False,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "disabled"
    assert called is False


def test_ga4_config_missing_status_without_request(monkeypatch):
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="",
        api_secret="",
        enabled=True,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "config_missing"
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


def test_ga4_send_failure_status(monkeypatch):
    monkeypatch.setattr(
        ga4_service.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "transport_failed"


def test_ga4_clean_event_params_truncates_string_values():
    params = ga4_service._clean_event_params({"utm_campaign": "x" * 130, "amount_jpy": 680})

    assert len(params["utm_campaign"]) == ga4_service.GA4_PARAM_VALUE_MAX_LENGTH
    assert params["amount_jpy"] == 680

def test_ga4_payload_uses_client_id_and_event_session_id(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    assert ga4_service.send_ga4_event(
        event_name="checkout_session_created",
        client_id="1498719245.1765352125",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
        session_id="1786245136",
    ) is True

    assert "measurement_id=G-TEST" in captured["url"]
    assert captured["payload"]["client_id"] == "1498719245.1765352125"
    event = captured["payload"]["events"][0]
    assert event["name"] == "checkout_session_created"
    assert event["params"]["service_id"] == "ryujin"
    assert event["params"]["session_id"] == 1786245136


def test_ga4_status_reports_non_2xx(monkeypatch):
    class FakeResponse:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "transport_failed"
    assert result["http_status"] == 500
    assert result["failure_type"] == "non_2xx"


def test_ga4_status_reports_http_error_4xx_without_sensitive_log(monkeypatch):
    class FakeLogger:
        def __init__(self):
            self.warnings = []

        def warning(self, message, extra=None):
            self.warnings.append((message, extra or {}))

    logger = FakeLogger()

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://www.google-analytics.com/mp/collect",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
        logger=logger,
    )

    assert result["sent"] is False
    assert result["status"] == "transport_failed"
    assert result["http_status"] == 400
    assert result["failure_type"] == "http_error"
    assert logger.warnings == [
        (
            "ga4_event_send_failed",
            {
                "event_name": "checkout_session_created",
                "ga4_http_status": 400,
                "ga4_failure_type": "http_error",
                "error": "HTTPError",
            },
        )
    ]


def test_ga4_status_reports_http_error_5xx(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://www.google-analytics.com/mp/collect",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(ga4_service.urllib.request, "urlopen", fake_urlopen)

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "transport_failed"
    assert result["http_status"] == 503
    assert result["failure_type"] == "http_error"


def test_ga4_status_reports_unexpected_exception(monkeypatch):
    monkeypatch.setattr(
        ga4_service.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = ga4_service.send_ga4_event_with_status(
        event_name="checkout_session_created",
        client_id="cid",
        measurement_id="G-TEST",
        api_secret="secret",
        enabled=True,
        params={"service_id": "ryujin"},
    )

    assert result["sent"] is False
    assert result["status"] == "exception"
    assert result["failure_type"] == "RuntimeError"
