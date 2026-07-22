import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


GA4_ENDPOINT = "https://www.google-analytics.com/mp/collect"
GA4_PARAM_VALUE_MAX_LENGTH = 100


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
    logger: logging.Logger | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    """Send one GA4 Measurement Protocol event without affecting app flow."""
    if not is_ga4_enabled(enabled):
        return False

    if not measurement_id or not api_secret:
        if logger:
            logger.warning("ga4_config_missing")
        return False

    clean_params = _clean_event_params(params or {})
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
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if logger:
            logger.warning("ga4_event_send_failed", extra={"event_name": event_name, "error": str(exc)})
        return False


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