import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


GA4_ENDPOINT = "https://www.google-analytics.com/mp/collect"
GA4_PARAM_VALUE_MAX_LENGTH = 100
GA4_STATUS_NOT_ATTEMPTED = "not_attempted"
GA4_STATUS_REQUEST_ACCEPTED = "request_accepted"
GA4_STATUS_TRANSPORT_FAILED = "transport_failed"
GA4_STATUS_CONFIG_MISSING = "config_missing"
GA4_STATUS_DISABLED = "disabled"
GA4_STATUS_EXCEPTION = "exception"


def is_ga4_enabled(enabled_value: bool | str | None) -> bool:
    if isinstance(enabled_value, bool):
        return enabled_value
    if enabled_value is None:
        return False
    return str(enabled_value).strip().lower() == "true"


def send_ga4_event(
    *,
    event_name: str,
    client_id: str,
    measurement_id: str,
    api_secret: str,
    enabled: bool | str | None,
    params: dict[str, Any] | None = None,
    session_id: str | int | None = None,
    logger: logging.Logger | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    """Send one GA4 Measurement Protocol event without affecting app flow."""
    return send_ga4_event_with_status(
        event_name=event_name,
        client_id=client_id,
        measurement_id=measurement_id,
        api_secret=api_secret,
        enabled=enabled,
        params=params,
        session_id=session_id,
        logger=logger,
        timeout_seconds=timeout_seconds,
    )["sent"]


def send_ga4_event_with_status(
    *,
    event_name: str,
    client_id: str,
    measurement_id: str,
    api_secret: str,
    enabled: bool | str | None,
    params: dict[str, Any] | None = None,
    session_id: str | int | None = None,
    logger: logging.Logger | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Send one GA4 Measurement Protocol event and classify the request result."""
    if not is_ga4_enabled(enabled):
        return {
            "sent": False,
            "status": GA4_STATUS_DISABLED,
            "http_status": None,
            "failure_type": "disabled",
        }

    if not measurement_id or not api_secret:
        if logger:
            logger.warning("ga4_config_missing")
        return {
            "sent": False,
            "status": GA4_STATUS_CONFIG_MISSING,
            "http_status": None,
            "failure_type": "config_missing",
        }

    clean_params = _clean_event_params(params or {})
    clean_session_id = _clean_session_id(session_id)
    if clean_session_id is not None:
        clean_params["session_id"] = clean_session_id
    payload = {
        "client_id": client_id,
        "events": [
            {
                "name": event_name,
                "params": clean_params,
            }
        ],
    }

    query = urllib.parse.urlencode(
        {
            "measurement_id": measurement_id,
            "api_secret": api_secret,
        }
    )
    request = urllib.request.Request(
        f"{GA4_ENDPOINT}?{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            sent = 200 <= response.status < 300
            status = GA4_STATUS_REQUEST_ACCEPTED if sent else GA4_STATUS_TRANSPORT_FAILED
            if logger:
                logger.info(
                    "ga4_event_send_result",
                    extra={
                        "event_name": event_name,
                        "ga4_http_status": response.status,
                        "ga4_failure_type": None if sent else "non_2xx",
                    },
                )
            return {
                "sent": sent,
                "status": status,
                "http_status": response.status,
                "failure_type": None if sent else "non_2xx",
            }
    except urllib.error.HTTPError as exc:
        http_status = getattr(exc, "code", None)
        if logger:
            logger.warning(
                "ga4_event_send_failed",
                extra={
                    "event_name": event_name,
                    "ga4_http_status": http_status,
                    "ga4_failure_type": "http_error",
                    "error": exc.__class__.__name__,
                },
            )
        return {
            "sent": False,
            "status": GA4_STATUS_TRANSPORT_FAILED,
            "http_status": http_status,
            "failure_type": "http_error",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if logger:
            logger.warning("ga4_event_send_failed", extra={"event_name": event_name, "error": str(exc)})
        return {
            "sent": False,
            "status": GA4_STATUS_TRANSPORT_FAILED,
            "http_status": None,
            "failure_type": exc.__class__.__name__,
        }
    except Exception as exc:
        if logger:
            logger.warning(
                "ga4_event_send_exception",
                extra={"event_name": event_name, "error": exc.__class__.__name__},
            )
        return {
            "sent": False,
            "status": GA4_STATUS_EXCEPTION,
            "http_status": None,
            "failure_type": exc.__class__.__name__,
        }


def _clean_event_params(params: dict[str, Any]) -> dict[str, Any]:
    clean_params: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str):
            clean_params[key] = value[:GA4_PARAM_VALUE_MAX_LENGTH]
        elif isinstance(value, (int, float, bool)):
            clean_params[key] = value
        else:
            clean_params[key] = str(value)[:GA4_PARAM_VALUE_MAX_LENGTH]
    return clean_params

def _clean_session_id(session_id: str | int | None) -> int | str | None:
    if session_id is None:
        return None
    cleaned = str(session_id).strip()
    if not cleaned:
        return None
    if cleaned.isdecimal():
        return int(cleaned)
    return cleaned[:GA4_PARAM_VALUE_MAX_LENGTH]
