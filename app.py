
import base64
import datetime
import hashlib
import html
import logging
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

try:
    import stripe
except ImportError:  # pragma: no cover - デプロイ環境で stripe 未導入時の保険
    stripe = None

from config import (
    APP_ENV,
    APP_SUBTITLE,
    APP_TITLE,
    BASE_DIR,
    CATEGORY_OPTIONS,
    GEMINI_MODEL,
    GA4_API_SECRET,
    GA4_ENABLED,
    GA4_MEASUREMENT_ID,
    HOUR_OPTIONS,
    LOG_LEVEL,
    MAX_IMAGE_FILES,
    MAX_IMAGE_SIZE_MB,
    MAX_REVIEW_MEMO_LENGTH,
    MAX_REVIEW_PDF_SIZE_MB,
    MIKO_IMAGE_PATH,
    MINUTE_OPTIONS,
    SHOW_DEBUG,
    TIME_ACCURACY_OPTIONS,
)
from models.schemas import FortuneInput, PalmImageMeta
from services.firestore_service import (
    GENERATION_CLAIMED,
    GENERATION_CLAIM_PROCESSING,
    claim_generation_transaction,
    consume_purchase_transaction,
    create_purchase_record as firestore_create_purchase_record,
    get_firestore_client,
    get_purchase_collection,
    get_purchase_by_access_token,
    is_ga4_event_sent,
    mark_ga4_event_sent_if_unset,
    release_generation_claim_transaction,
)
from stripe_webhook.environment_config import EnvironmentConfigError, get_stripe_settings
from services.fortune_service import (
    build_image_parts,
    build_review_context,
    call_gemini_fortune,
    call_gemini_review_fortune,
    call_gemini_review_pdf_summary,
)
from services.ga4_service import send_ga4_event
from services.ga4_service import send_ga4_event_with_status
from services.pdf_service import (
    format_review_comparison_blocks,
    generate_miko_letter_pdf,
    generate_review_fortune_pdf,
)
from services.validation_service import (
    format_birth_time_text,
    normalize_text,
    validate_inputs,
    validate_review_inputs,
    validate_review_pdf_content,
)
from ui.components import (
    build_selected_hand_sides,
    render_form_gap,
    render_html_box,
)
from ui.styles import render_app_css

APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    "https://ai-uranai-h1-155905710900.asia-northeast2.run.app",
).rstrip("/")
WIX_REGULAR_LP_URL = "https://www.omoshiro-cre8works.com/ai-uranai"
WIX_SITE_TOP_URL = "https://www.omoshiro-cre8works.com/"
WIX_REVIEW_LP_URL = "https://www.omoshiro-cre8works.com/ai-uranai/mikaeshibin"
WIX_CANCEL_URL = os.getenv(
    "WIX_CANCEL_URL",
    WIX_REGULAR_LP_URL,
)
_CONFIGURED_REGULAR_TOP_URL = os.getenv("REGULAR_TOP_URL", "").strip()
REGULAR_TOP_URL = (
    _CONFIGURED_REGULAR_TOP_URL
    if _CONFIGURED_REGULAR_TOP_URL and _CONFIGURED_REGULAR_TOP_URL.rstrip("/") != APP_BASE_URL
    else WIX_REGULAR_LP_URL
)
REVIEW_LP_URL = os.getenv("REVIEW_LP_URL", WIX_REVIEW_LP_URL).strip() or WIX_REVIEW_LP_URL


def get_int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID_REGULAR = os.getenv("STRIPE_PRICE_ID_REGULAR", os.getenv("STRIPE_PRICE_ID", ""))
STRIPE_PRICE_ID_CAMPAIGN = os.getenv("STRIPE_PRICE_ID_CAMPAIGN", "")
STRIPE_REVIEW_PRICE_ID = os.getenv("STRIPE_REVIEW_PRICE_ID", os.getenv("STRIPE_PRICE_ID_REVIEW", ""))
STRIPE_PRICE_ID_REVIEW = STRIPE_REVIEW_PRICE_ID
STRIPE_PRICE_ID_REVIEW_CAMPAIGN = os.getenv("STRIPE_PRICE_ID_REVIEW_CAMPAIGN", "")
CAMPAIGN_END_AT = os.getenv("CAMPAIGN_END_AT", "").strip()
CAMPAIGN_TIMEZONE = os.getenv("CAMPAIGN_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
REGULAR_AMOUNT_JPY = 300
CAMPAIGN_AMOUNT_JPY = 100
REVIEW_PLANNED_AMOUNT_JPY = get_int_env("REVIEW_PLANNED_AMOUNT_JPY", 780)
REVIEW_AMOUNT_JPY = get_int_env("REVIEW_AMOUNT_JPY", 680)
REVIEW_CAMPAIGN_AMOUNT_JPY = get_int_env("REVIEW_CAMPAIGN_AMOUNT_JPY", REVIEW_AMOUNT_JPY)
STRIPE_ENABLED = bool(stripe and STRIPE_SECRET_KEY and STRIPE_PRICE_ID_REGULAR)
PRODUCT_TYPE_REGULAR = "regular"
PRODUCT_TYPE_REVIEW = "review"
VALID_PRODUCT_TYPES = {PRODUCT_TYPE_REGULAR, PRODUCT_TYPE_REVIEW}
SERVICE_ID = "ryujin"
TRACKING_VALUE_MAX_LENGTH = 100
LP_VALUE_MAX_LENGTH = 32
LP_FALLBACK_VALUE = "direct_or_unknown"
TRACKING_PARAM_KEYS = (
    "service_id",
    "product_type",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "entry_lp",
    "entry_utm_source",
    "entry_utm_medium",
    "entry_utm_campaign",
    "entry_utm_content",
    "current_lp",
    "test_mode",
    "button_position",
)
UTM_PARAM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
ENTRY_UTM_PARAM_KEYS = (
    "entry_utm_source",
    "entry_utm_medium",
    "entry_utm_campaign",
    "entry_utm_content",
)
LP_PARAM_KEYS = ("entry_lp", "current_lp")
STRIPE_METADATA_TRACKING_KEYS = (
    "service_id",
    "product_type",
    *UTM_PARAM_KEYS,
    *ENTRY_UTM_PARAM_KEYS,
    *LP_PARAM_KEYS,
    "test_mode",
    "button_position",
)
SUCCESS_URL_TRACKING_KEYS = (
    *UTM_PARAM_KEYS,
    *ENTRY_UTM_PARAM_KEYS,
    *LP_PARAM_KEYS,
    "test_mode",
    "button_position",
)
VALID_TEST_MODES = {"owner", "none"}
VALID_BUTTON_POSITIONS = {"top", "middle", "bottom", "sample_bottom", "unknown"}
BUTTON_POSITION_ALIASES = {
    "first_view": "top",
    "hero": "top",
    "top": "top",
    "sample_after": "middle",
    "sumple_after": "middle",
    "middle": "middle",
    "bottom": "bottom",
    "sample_bottom": "sample_bottom",
}
GA4_SENSITIVE_QUERY_PARAMS = {"session_id", "purchase_id", "access_token"}
GA4_IDENTIFIER_QUERY_PARAMS = {"ga4_client_id", "ga4_session_id"}
VALID_GA4_CHECKOUT_REQUEST_STATUSES = {
    "not_attempted",
    "request_accepted",
    "transport_failed",
    "config_missing",
    "disabled",
    "exception",
}
ASSETS_DIR = BASE_DIR / "assets"
REGULAR_COMPLETION_ILLUSTRATION = os.getenv(
    "REGULAR_COMPLETION_ILLUSTRATION",
    str(ASSETS_DIR / "miko_pdf.png"),
).strip()
REVIEW_COMPLETION_ILLUSTRATION = os.getenv(
    "REVIEW_COMPLETION_ILLUSTRATION",
    str(ASSETS_DIR / "nico_pdf.png"),
).strip()
SAMPLE_PDF_IMAGE_PATHS = [
    ASSETS_DIR / "sample_pdf_1.png",
    ASSETS_DIR / "sample_pdf_2.png",
    ASSETS_DIR / "sample_pdf_3.png",
]


def read_image_bytes(image_path: str | Path) -> bytes | None:
    path = Path(image_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        if path.exists() and path.is_file():
            return path.read_bytes()
    except OSError:
        return None
    return None


def render_inline_png(
    image_bytes: bytes,
    *,
    alt: str,
    width: int | None = None,
    caption: str | None = None,
) -> None:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    safe_alt = html.escape(alt, quote=True)
    width_style = f"width:{width}px;" if width else "width:100%;"
    caption_html = (
        f'<figcaption style="margin-top:0.35rem; color:#666666; font-size:0.85rem;">'
        f"{html.escape(caption)}</figcaption>"
        if caption
        else ""
    )
    st.html(
        f'''
        <figure style="margin:0; text-align:center;">
            <img
                src="data:image/png;base64,{encoded}"
                alt="{safe_alt}"
                style="{width_style} max-width:100%; height:auto; display:block; margin:0 auto;"
            >
            {caption_html}
        </figure>
        '''
    )


def scroll_completion_screen_to_top() -> None:
    components.html(
        '''
        <script>
        const scrollCompletionToTop = () => {
            try {
                const parentDocument = window.parent.document;
                const scrollTargets = [
                    window.parent,
                    parentDocument.documentElement,
                    parentDocument.body,
                    parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
                    parentDocument.querySelector('[data-testid="stMain"]')
                ];
                scrollTargets.forEach((target) => {
                    if (!target) return;
                    if (typeof target.scrollTo === 'function') {
                        target.scrollTo({ top: 0, left: 0, behavior: 'auto' });
                    } else {
                        target.scrollTop = 0;
                        target.scrollLeft = 0;
                    }
                });
            } catch (error) {
                window.parent.scrollTo(0, 0);
            }
        };
        scrollCompletionToTop();
        window.requestAnimationFrame(scrollCompletionToTop);
        window.setTimeout(scrollCompletionToTop, 80);
        window.setTimeout(scrollCompletionToTop, 300);
        </script>
        ''',
        height=0,
        width=0,
    )


def render_completion_miko_image(image_bytes: bytes) -> None:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    st.html(
        f'''
        <figure class="completion-miko-figure">
            <img
                src="data:image/png;base64,{encoded}"
                alt="巫女画像"
            >
        </figure>
        '''
    )


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


def init_session_state() -> None:
    if "fortune_json" not in st.session_state:
        st.session_state.fortune_json = None
    if "fortune_pdf_bytes" not in st.session_state:
        st.session_state.fortune_pdf_bytes = None
    if "fortune_pdf_purchase_id" not in st.session_state:
        st.session_state.fortune_pdf_purchase_id = None
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""
    if "active_purchase_id" not in st.session_state:
        st.session_state.active_purchase_id = None
    if "active_access_token" not in st.session_state:
        st.session_state.active_access_token = None
    if "checkout_url" not in st.session_state:
        st.session_state.checkout_url = None
    if "checkout_product_type" not in st.session_state:
        st.session_state.checkout_product_type = None
    ga4_client_id_from_query = clean_ga4_identifier(get_query_param_value("ga4_client_id"))
    ga4_session_id_from_query = clean_ga4_identifier(get_query_param_value("ga4_session_id"))
    set_ga4_observation_state(
        client_id_received=bool(ga4_client_id_from_query),
        session_id_received=bool(ga4_session_id_from_query),
    )
    if "ga4_client_id" not in st.session_state:
        st.session_state.ga4_client_id = secrets.token_urlsafe(16)
    if "ga4_session_id" not in st.session_state:
        st.session_state.ga4_session_id = None
    if "ga4_checkout_request_status" not in st.session_state:
        st.session_state.ga4_checkout_request_status = "not_attempted"
    if "ga4_page_view_locations" not in st.session_state:
        st.session_state.ga4_page_view_locations = set()
    if "ga4_form_displayed_purchase_ids" not in st.session_state:
        st.session_state.ga4_form_displayed_purchase_ids = set()
    if "ga4_pdf_generated_purchase_ids" not in st.session_state:
        st.session_state.ga4_pdf_generated_purchase_ids = set()
    if "review_context" not in st.session_state:
        st.session_state.review_context = None
    if "review_fortune" not in st.session_state:
        st.session_state.review_fortune = None
    if "review_fortune_purchase_id" not in st.session_state:
        st.session_state.review_fortune_purchase_id = None
    if "review_pdf_bytes" not in st.session_state:
        st.session_state.review_pdf_bytes = None
    if "review_pdf_generated_purchase_id" not in st.session_state:
        st.session_state.review_pdf_generated_purchase_id = None
    if "review_purchase_consumed" not in st.session_state:
        st.session_state.review_purchase_consumed = set()
    if "generation_claim_status" not in st.session_state:
        st.session_state.generation_claim_status = None
    for key, value in get_default_tracking_params().items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_query_param_value(key: str) -> str | None:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def clean_tracking_value(value: Any, max_length: int = TRACKING_VALUE_MAX_LENGTH) -> str:
    raw_value = "" if value is None else str(value)
    stripped_value = raw_value.strip()
    safe_value = "".join(
        character
        for character in stripped_value
        if character.isprintable() and character not in {"\x7f"}
    )
    return safe_value[:max_length]


def normalize_lp_value(value: str | None) -> str:
    normalized = clean_tracking_value(value, TRACKING_VALUE_MAX_LENGTH).lower()
    if len(normalized) > LP_VALUE_MAX_LENGTH:
        return LP_FALLBACK_VALUE
    if normalized == LP_FALLBACK_VALUE:
        return LP_FALLBACK_VALUE
    if re.fullmatch(r"lp_[a-z0-9_]{1,29}", normalized):
        return normalized
    return LP_FALLBACK_VALUE


def is_specific_lp(value: str | None) -> bool:
    return normalize_lp_value(value) != LP_FALLBACK_VALUE


def legacy_lp_from_utm_content(value: str | None) -> str:
    normalized = normalize_lp_value(value)
    return normalized if normalized != LP_FALLBACK_VALUE else LP_FALLBACK_VALUE


def normalize_test_mode(value: str | None) -> str:
    normalized = clean_tracking_value(value).lower()
    if normalized in VALID_TEST_MODES:
        return normalized
    return "none"


def normalize_button_position(*values: str | None) -> str:
    for value in values:
        normalized = clean_tracking_value(value).lower()
        if not normalized:
            continue
        mapped = BUTTON_POSITION_ALIASES.get(normalized)
        if mapped in VALID_BUTTON_POSITIONS:
            return mapped
    return "unknown"


def get_default_tracking_params(product_type: str | None = None) -> dict[str, str]:
    return {
        "service_id": SERVICE_ID,
        "product_type": normalize_product_type(product_type),
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "utm_content": "",
        "entry_lp": LP_FALLBACK_VALUE,
        "entry_utm_source": "",
        "entry_utm_medium": "",
        "entry_utm_campaign": "",
        "entry_utm_content": "",
        "current_lp": LP_FALLBACK_VALUE,
        "test_mode": "none",
        "button_position": "unknown",
    }


def get_tracking_params_from_query() -> dict[str, str]:
    params: dict[str, str] = {"service_id": SERVICE_ID}
    product_type = get_query_param_value("product_type")
    if product_type is not None:
        params["product_type"] = normalize_product_type(product_type)

    for key in UTM_PARAM_KEYS:
        value = clean_tracking_value(get_query_param_value(key))
        if value:
            params[key] = value

    for key in ENTRY_UTM_PARAM_KEYS:
        value = clean_tracking_value(get_query_param_value(key))
        if value:
            params[key] = value

    utm_content = get_query_param_value("utm_content")
    entry_lp = get_query_param_value("entry_lp")
    if entry_lp is not None:
        params["entry_lp"] = normalize_lp_value(entry_lp)
    else:
        params["entry_lp"] = legacy_lp_from_utm_content(utm_content)

    current_lp = get_query_param_value("current_lp")
    if current_lp is not None:
        params["current_lp"] = normalize_lp_value(current_lp)
    else:
        params["current_lp"] = legacy_lp_from_utm_content(utm_content)

    for old_key, entry_key in zip(UTM_PARAM_KEYS, ENTRY_UTM_PARAM_KEYS, strict=True):
        if entry_key not in params and old_key in params:
            params[entry_key] = params[old_key]

    test_mode = get_query_param_value("test_mode")
    if test_mode is not None:
        params["test_mode"] = normalize_test_mode(test_mode)

    button_position = get_query_param_value("button_position")
    button = get_query_param_value("button")
    if button_position is not None or button is not None or utm_content is not None:
        params["button_position"] = normalize_button_position(
            button_position,
            button,
            utm_content,
        )
    return params


def clean_ga4_identifier(value: str | None) -> str:
    return clean_tracking_value(value)


def set_ga4_observation_state(*, client_id_received: bool, session_id_received: bool) -> None:
    st.session_state.ga4_client_id_received = bool(client_id_received)
    st.session_state.ga4_session_id_received = bool(session_id_received)
    st.session_state.ga4_client_id_source = "wix" if client_id_received else "generated"
    st.session_state.ga4_session_linkable = bool(client_id_received and session_id_received)


def update_ga4_identifiers_from_query() -> None:
    ga4_client_id = clean_ga4_identifier(get_query_param_value("ga4_client_id"))
    ga4_session_id = clean_ga4_identifier(get_query_param_value("ga4_session_id"))
    set_ga4_observation_state(
        client_id_received=bool(ga4_client_id),
        session_id_received=bool(ga4_session_id),
    )
    if ga4_client_id:
        st.session_state.ga4_client_id = ga4_client_id

    if ga4_session_id:
        st.session_state.ga4_session_id = ga4_session_id

def get_tracking_params_from_session() -> dict[str, str]:
    params = get_default_tracking_params(st.session_state.get("product_type"))
    for key in TRACKING_PARAM_KEYS:
        value = st.session_state.get(key)
        if key == "service_id":
            params[key] = SERVICE_ID
        elif key == "product_type":
            params[key] = normalize_product_type(str(value or ""))
        elif key == "test_mode":
            params[key] = normalize_test_mode(str(value or ""))
        elif key == "button_position":
            params[key] = normalize_button_position(str(value or ""))
        elif key in LP_PARAM_KEYS:
            params[key] = normalize_lp_value(str(value or ""))
        else:
            params[key] = clean_tracking_value(value)
    return params


def get_tracking_params_from_record(record: dict[str, Any] | None) -> dict[str, str]:
    if not record:
        return {}

    params: dict[str, str] = {}
    for key in TRACKING_PARAM_KEYS:
        if key not in record:
            continue
        if key == "service_id":
            params[key] = clean_tracking_value(record.get(key) or SERVICE_ID) or SERVICE_ID
        elif key == "product_type":
            params[key] = get_purchase_product_type(record)
        elif key == "test_mode":
            params[key] = normalize_test_mode(str(record.get(key) or ""))
        elif key == "button_position":
            params[key] = normalize_button_position(str(record.get(key) or ""))
        elif key in LP_PARAM_KEYS:
            params[key] = normalize_lp_value(str(record.get(key) or ""))
        else:
            params[key] = clean_tracking_value(record.get(key))
    return params

def merge_tracking_params_by_priority(
    *sources: dict[str, Any] | None,
    product_type: str | None = None,
) -> dict[str, str]:
    merged = get_default_tracking_params(product_type)
    for source in reversed([source or {} for source in sources]):
        for key in TRACKING_PARAM_KEYS:
            if key not in source:
                continue
            value = source.get(key)
            if key == "service_id":
                cleaned = clean_tracking_value(value) or SERVICE_ID
            elif key == "product_type":
                cleaned = normalize_product_type(str(value or ""))
            elif key == "test_mode":
                cleaned = normalize_test_mode(str(value or ""))
            elif key == "button_position":
                cleaned = normalize_button_position(str(value or ""))
            elif key in LP_PARAM_KEYS:
                cleaned = normalize_lp_value(str(value or ""))
            else:
                cleaned = clean_tracking_value(value)
            if cleaned or key in {"service_id", "product_type", "test_mode", "button_position"}:
                merged[key] = cleaned
    merged["service_id"] = SERVICE_ID
    merged["product_type"] = normalize_product_type(merged.get("product_type"))
    merged["test_mode"] = normalize_test_mode(merged.get("test_mode"))
    merged["button_position"] = normalize_button_position(merged.get("button_position"))
    merged["entry_lp"] = normalize_lp_value(merged.get("entry_lp"))
    merged["current_lp"] = normalize_lp_value(merged.get("current_lp"))
    return merged


def update_tracking_session_state(params: dict[str, Any] | None, *, overwrite_empty: bool = False) -> dict[str, str]:
    current = get_tracking_params_from_session()
    incoming = merge_tracking_params_by_priority(params, current)
    for key, value in incoming.items():
        if (
            key == "entry_lp"
            and not overwrite_empty
            and current.get("entry_lp") != LP_FALLBACK_VALUE
            and value == LP_FALLBACK_VALUE
        ):
            continue
        if overwrite_empty or value or key in {"service_id", "product_type", "test_mode", "button_position"}:
            st.session_state[key] = value
    return get_tracking_params_from_session()


def update_tracking_session_state_from_query() -> dict[str, str]:
    query_params = get_tracking_params_from_query()
    current = get_tracking_params_from_session()
    raw_entry_lp = get_query_param_value("entry_lp")
    keep_existing_entry = (
        current.get("entry_lp") != LP_FALLBACK_VALUE
        and (raw_entry_lp is None or normalize_lp_value(raw_entry_lp) == LP_FALLBACK_VALUE)
    )
    if keep_existing_entry:
        query_params["entry_lp"] = current["entry_lp"]
        for key in ENTRY_UTM_PARAM_KEYS:
            if get_query_param_value(key) is None:
                query_params[key] = current.get(key, "")
    return update_tracking_session_state(query_params, overwrite_empty=False)


def normalize_ga4_checkout_request_status(value: str | None) -> str:
    normalized = clean_tracking_value(value).lower()
    if normalized in VALID_GA4_CHECKOUT_REQUEST_STATUSES:
        return normalized
    return "not_attempted"


def get_ga4_observation_params() -> dict[str, bool | str]:
    client_id_received = bool(st.session_state.get("ga4_client_id_received"))
    session_id_received = bool(st.session_state.get("ga4_session_id_received"))
    return {
        "ga4_client_id_received": client_id_received,
        "ga4_session_id_received": session_id_received,
        "ga4_client_id_source": "wix" if client_id_received else "generated",
        "ga4_session_linkable": bool(client_id_received and session_id_received),
        "ga4_checkout_request_status": normalize_ga4_checkout_request_status(
            str(st.session_state.get("ga4_checkout_request_status") or "not_attempted")
        ),
    }


def tracking_params_for_storage(product_type: str | None = None) -> dict[str, str]:
    params = get_tracking_params_from_session()
    params["product_type"] = normalize_product_type(product_type or params.get("product_type"))
    params["service_id"] = SERVICE_ID
    return {**params, **get_ga4_observation_params()}


def tracking_params_for_stripe_metadata(product_type: str | None = None) -> dict[str, str]:
    params = get_tracking_params_from_session()
    params["product_type"] = normalize_product_type(product_type or params.get("product_type"))
    params["service_id"] = SERVICE_ID
    return {key: str(params[key]) for key in STRIPE_METADATA_TRACKING_KEYS if key in params}


def get_utm_params() -> dict[str, str]:
    params = get_tracking_params_from_session()
    return {key: params[key] for key in UTM_PARAM_KEYS if params.get(key)}

def has_purchase_return_query_params() -> bool:
    return any(
        get_query_param_value(key)
        for key in ("session_id", "purchase_id", "access_token")
    )


def should_use_direct_checkout(
    action: str | None,
    product_type: str | None,
    purchase_return_requested: bool,
) -> bool:
    return bool(
        not purchase_return_requested
        and (action or "").strip().lower() == "checkout"
        and (product_type or "").strip().lower() in VALID_PRODUCT_TYPES
    )


def is_direct_checkout_request() -> bool:
    return should_use_direct_checkout(
        action=get_query_param_value("action"),
        product_type=get_query_param_value("product_type"),
        purchase_return_requested=has_purchase_return_query_params(),
    )


def normalize_product_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in VALID_PRODUCT_TYPES:
        return normalized
    return PRODUCT_TYPE_REGULAR


def get_requested_product_type() -> str:
    return normalize_product_type(get_query_param_value("product_type"))


def get_purchase_product_type(record: dict[str, Any] | None) -> str:
    if not record:
        return PRODUCT_TYPE_REGULAR
    return normalize_product_type(str(record.get("product_type") or ""))


def get_product_display_name(product_type: str) -> str:
    if product_type == PRODUCT_TYPE_REVIEW:
        return "龍神さまのお告げ 見返し便"
    return APP_TITLE


def format_iso_date_japanese(value: str) -> str:
    try:
        parsed = datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return value or ""
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def sanitize_page_location_for_ga4(
    query_params: dict[str, str] | None = None,
) -> str:
    if query_params is None:
        query_params = {}
        for key in st.query_params:
            value = get_query_param_value(key)
            if value is not None:
                query_params[key] = value

    safe_query_params = {
        key: value
        for key, value in query_params.items()
        if key not in GA4_SENSITIVE_QUERY_PARAMS
        and key not in GA4_IDENTIFIER_QUERY_PARAMS
    }
    query_string = urllib.parse.urlencode(safe_query_params)
    return f"{APP_BASE_URL}/?{query_string}" if query_string else f"{APP_BASE_URL}/"


def get_page_location() -> str:
    return sanitize_page_location_for_ga4()


def get_checkout_price_type(product_type: str, price_id: str) -> str:
    if product_type == PRODUCT_TYPE_REVIEW:
        if STRIPE_PRICE_ID_REVIEW_CAMPAIGN and price_id == STRIPE_PRICE_ID_REVIEW_CAMPAIGN:
            return "review_campaign"
        return "review_regular"
    if STRIPE_PRICE_ID_CAMPAIGN and price_id == STRIPE_PRICE_ID_CAMPAIGN:
        return "regular_campaign"
    return "regular"


def build_checkout_success_url(purchase_id: str, access_token: str, product_type: str) -> str:
    tracking_params = tracking_params_for_storage(product_type)
    query_params = {
        "purchase_id": purchase_id,
        "access_token": access_token,
        "product_type": normalize_product_type(product_type),
        **{
            key: value
            for key, value in tracking_params.items()
            if key in SUCCESS_URL_TRACKING_KEYS and value
        },
    }
    ga4_client_id = clean_tracking_value(st.session_state.get("ga4_client_id"))
    if ga4_client_id:
        query_params["ga4_client_id"] = ga4_client_id
    ga4_session_id = clean_tracking_value(st.session_state.get("ga4_session_id"))
    if ga4_session_id:
        query_params["ga4_session_id"] = ga4_session_id
    query_parts = [
        "session_id={CHECKOUT_SESSION_ID}",
        urllib.parse.urlencode(query_params),
    ]
    return f"{APP_BASE_URL}/?{'&'.join(query_parts)}"

def track_ga4_event(
    event_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
) -> bool:
    return track_ga4_event_with_status(event_name, logger, params)["sent"]


def track_ga4_event_with_status(
    event_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tracking_params = get_tracking_params_from_session()
    event_params = {
        "page_location": get_page_location(),
        **tracking_params,
        **get_ga4_observation_params(),
    }
    if params:
        event_params.update(params)
    event_params["service_id"] = SERVICE_ID
    event_params["product_type"] = normalize_product_type(event_params.get("product_type"))
    event_params["test_mode"] = normalize_test_mode(str(event_params.get("test_mode") or ""))
    event_params["button_position"] = normalize_button_position(
        str(event_params.get("button_position") or "")
    )
    event_params["entry_lp"] = normalize_lp_value(str(event_params.get("entry_lp") or ""))
    event_params["current_lp"] = normalize_lp_value(str(event_params.get("current_lp") or ""))

    return send_ga4_event_with_status(
        event_name=event_name,
        client_id=st.session_state.ga4_client_id,
        measurement_id=GA4_MEASUREMENT_ID,
        api_secret=GA4_API_SECRET,
        enabled=GA4_ENABLED,
        params=event_params,
        session_id=st.session_state.get("ga4_session_id"),
        logger=logger,
    )

def track_purchase_ga4_event_once(
    event_name: str,
    purchase_id: str | None,
    product_type: str,
    logger: logging.Logger,
) -> bool:
    """Send a GA4 purchase-scoped event once, using Firestore as the durable sent flag."""
    if not purchase_id:
        return False

    try:
        if is_ga4_event_sent(purchase_id, event_name):
            return True
    except Exception:
        logger.warning("ga4_event_sent_check_failed", extra={"event_name": event_name})
        return False

    sent = track_ga4_event(event_name, logger, {"product_type": product_type})
    if not sent:
        return False

    try:
        mark_ga4_event_sent_if_unset(purchase_id, event_name)
    except Exception:
        logger.warning("ga4_event_sent_mark_failed", extra={"event_name": event_name})
    return True

def track_streamlit_page_view(logger: logging.Logger, product_type: str) -> None:
    page_location = get_page_location()
    tracked_key = f"{page_location}|{product_type}"
    tracked_locations = st.session_state.ga4_page_view_locations
    if tracked_key in tracked_locations:
        return

    track_ga4_event(
        "streamlit_page_view",
        logger,
        {
            "page_location": page_location,
            "page_title": APP_TITLE,
            "product_type": product_type,
        },
    )
    tracked_locations.add(tracked_key)


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def build_correlation_ref(purchase_id: str | None) -> str:
    if not purchase_id:
        return ""
    return hashlib.sha256(str(purchase_id).encode("utf-8")).hexdigest()[:12]


def token_expires_at_datetime(hours: int = 24) -> datetime.datetime:
    return utc_now() + datetime.timedelta(hours=hours)


def parse_campaign_end_at(logger: logging.Logger | None = None) -> datetime.datetime | None:
    if not CAMPAIGN_END_AT:
        return None

    normalized_value = CAMPAIGN_END_AT.replace("Z", "+00:00")
    try:
        campaign_end_at = datetime.datetime.fromisoformat(normalized_value)
    except ValueError:
        if logger:
            logger.warning("campaign_end_at_invalid_format")
        return None

    if campaign_end_at.tzinfo is not None:
        return campaign_end_at

    try:
        campaign_tz = ZoneInfo(CAMPAIGN_TIMEZONE)
    except Exception:
        if logger:
            logger.warning("campaign_timezone_invalid")
        return None

    return campaign_end_at.replace(tzinfo=campaign_tz)


def get_active_checkout_price(product_type: str, logger: logging.Logger | None = None) -> tuple[str, int]:
    product_type = normalize_product_type(product_type)
    if product_type == PRODUCT_TYPE_REVIEW:
        if STRIPE_PRICE_ID_REVIEW_CAMPAIGN and CAMPAIGN_END_AT:
            campaign_end_at = parse_campaign_end_at(logger)
            if campaign_end_at and utc_now() < campaign_end_at.astimezone(datetime.timezone.utc):
                return STRIPE_PRICE_ID_REVIEW_CAMPAIGN, REVIEW_CAMPAIGN_AMOUNT_JPY
        return STRIPE_PRICE_ID_REVIEW, REVIEW_AMOUNT_JPY

    if not STRIPE_PRICE_ID_CAMPAIGN or not CAMPAIGN_END_AT:
        return STRIPE_PRICE_ID_REGULAR, REGULAR_AMOUNT_JPY

    campaign_end_at = parse_campaign_end_at(logger)
    if campaign_end_at is None:
        return STRIPE_PRICE_ID_REGULAR, REGULAR_AMOUNT_JPY

    if utc_now() < campaign_end_at.astimezone(datetime.timezone.utc):
        return STRIPE_PRICE_ID_CAMPAIGN, CAMPAIGN_AMOUNT_JPY

    return STRIPE_PRICE_ID_REGULAR, REGULAR_AMOUNT_JPY


def clear_checkout_session_state() -> None:
    st.session_state.checkout_url = None
    st.session_state.checkout_product_type = None


def _purchase_doc_ref(purchase_id: str):
    db = get_firestore_client()
    return get_purchase_collection(db).document(purchase_id)


def create_purchase_record(
    price_id: str,
    amount_jpy: int,
    product_type: str,
    price_type: str,
) -> dict[str, Any]:
    purchase_id = f"p_{utc_now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
    access_token = secrets.token_urlsafe(24)
    token_expires_at = token_expires_at_datetime()
    product_type = normalize_product_type(product_type)
    tracking_params = tracking_params_for_storage(product_type)

    firestore_create_purchase_record(
        purchase_id=purchase_id,
        stripe_checkout_session_id="pending_checkout_session",
        access_token=access_token,
        token_expires_at=token_expires_at,
        product_type=product_type,
        price_type=price_type,
        price_id=price_id,
        amount_jpy=amount_jpy,
        currency="jpy",
        source="wix_lp",
        tracking_params=tracking_params,
    )

    record = update_purchase_record(
        purchase_id,
        stripe_checkout_session_id=None,
        amount_total=None,
        checkout_completed_at=None,
        app_version=APP_ENV,
    )
    record = record or {}
    record["_access_token"] = access_token
    return record

def get_purchase_record(purchase_id: str | None) -> dict[str, Any] | None:
    if not purchase_id:
        return None

    snapshot = _purchase_doc_ref(purchase_id).get()
    if not snapshot.exists:
        return None

    return snapshot.to_dict() or {}


def update_purchase_record(purchase_id: str, **updates: Any) -> dict[str, Any] | None:
    snapshot = _purchase_doc_ref(purchase_id).get()
    if not snapshot.exists:
        return None

    updates["updated_at"] = utc_now()
    _purchase_doc_ref(purchase_id).update(updates)

    refreshed = _purchase_doc_ref(purchase_id).get()
    return refreshed.to_dict() if refreshed.exists else None


def update_checkout_ga4_status(
    purchase_id: str,
    status: str,
    logger: logging.Logger,
) -> None:
    normalized_status = normalize_ga4_checkout_request_status(status)
    st.session_state.ga4_checkout_request_status = normalized_status
    try:
        update_purchase_record(
            purchase_id,
            ga4_checkout_request_status=normalized_status,
        )
    except Exception:
        logger.warning(
            "ga4_checkout_status_update_failed",
            extra={"correlation_ref": build_correlation_ref(purchase_id)},
        )


def get_tracking_params_from_metadata(metadata: Any | None) -> dict[str, str]:
    if not metadata or not hasattr(metadata, "get"):
        return {}
    return {
        key: metadata.get(key)
        for key in TRACKING_PARAM_KEYS
        if metadata.get(key) is not None
    }


def get_tracking_params_from_current_url() -> dict[str, str]:
    params = get_tracking_params_from_query()
    return {
        key: value
        for key, value in params.items()
        if value or key in {"service_id", "product_type", "test_mode", "button_position"}
    }


def restore_tracking_params(
    record: dict[str, Any] | None,
    metadata: Any | None = None,
) -> dict[str, str]:
    record_params = get_tracking_params_from_record(record)
    metadata_params = get_tracking_params_from_metadata(metadata)
    url_params = get_tracking_params_from_current_url()
    session_params = get_tracking_params_from_session()
    restored = merge_tracking_params_by_priority(
        record_params,
        metadata_params,
        url_params,
        session_params,
        product_type=get_purchase_product_type(record),
    )
    update_tracking_session_state(restored, overwrite_empty=True)
    return restored


def with_restored_tracking_params(
    record: dict[str, Any] | None,
    metadata: Any | None = None,
) -> dict[str, Any] | None:
    if not record:
        return None
    restored = restore_tracking_params(record, metadata)
    merged_record = dict(record)
    for key, value in restored.items():
        merged_record.setdefault(key, value)
    return merged_record

def is_token_valid(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    token_expires_at = record.get("token_expires_at")
    if not token_expires_at:
        return False

    if isinstance(token_expires_at, str):
        try:
            expires_at = datetime.datetime.fromisoformat(token_expires_at)
        except ValueError:
            return False
    else:
        expires_at = token_expires_at

    if getattr(expires_at, "tzinfo", None) is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)

    return expires_at > utc_now()


def is_purchase_ready(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("payment_status") == "paid"
        and not record.get("used_flag")
        and is_token_valid(record)
    )


def stripe_client_ready(product_type: str = PRODUCT_TYPE_REGULAR) -> bool:
    if not stripe or not STRIPE_SECRET_KEY:
        return False
    get_stripe_settings(secret_key=STRIPE_SECRET_KEY)
    normalized_product_type = normalize_product_type(product_type)
    if normalized_product_type == PRODUCT_TYPE_REVIEW:
        if not STRIPE_PRICE_ID_REVIEW:
            return False
    elif not STRIPE_PRICE_ID_REGULAR:
        return False
    stripe.api_key = STRIPE_SECRET_KEY
    return True


def create_checkout_session(product_type: str, logger: logging.Logger) -> tuple[str | None, str | None]:
    product_type = normalize_product_type(product_type)
    try:
        is_stripe_ready = stripe_client_ready(product_type)
    except EnvironmentConfigError as exc:
        logger.error("stripe_environment_config_error", extra={"reason": str(exc)})
        return None, str(exc)

    if not is_stripe_ready:
        if product_type == PRODUCT_TYPE_REVIEW:
            return None, "見返し便の決済設定がまだ完了していません。環境変数 STRIPE_REVIEW_PRICE_ID を確認してください。"
        return None, "Stripe の設定が不足しています。環境変数 STRIPE_SECRET_KEY / STRIPE_PRICE_ID_REGULAR を確認してください。"

    active_price_id, active_amount_jpy = get_active_checkout_price(product_type, logger)
    price_type = get_checkout_price_type(product_type, active_price_id)
    record = create_purchase_record(active_price_id, active_amount_jpy, product_type, price_type)
    purchase_id = record["purchase_id"]
    tracking_params = tracking_params_for_stripe_metadata(product_type)

    try:
        assert stripe is not None
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price": active_price_id,
                    "quantity": 1,
                }
            ],
            success_url=build_checkout_success_url(
                purchase_id=purchase_id,
                access_token=str(record.get("_access_token") or ""),
                product_type=product_type,
            ),
            cancel_url=WIX_CANCEL_URL,
            client_reference_id=purchase_id,
            metadata={
                "purchase_id": purchase_id,
                "product_type": product_type,
                "price_type": price_type,
                "price_id": active_price_id,
                "amount_jpy": str(active_amount_jpy),
                **{key: str(value) for key, value in tracking_params.items()},
            },
        )
        update_purchase_record(
            purchase_id,
            stripe_checkout_session_id=session.id,
        )
        st.session_state.active_purchase_id = purchase_id
        st.session_state.active_access_token = record.get("_access_token")
        st.session_state.checkout_url = session.url
        st.session_state.checkout_product_type = product_type
        logger.info(
            "checkout_session_created",
            extra={
                "env": APP_ENV,
                "purchase_id": purchase_id,
                "product_type": product_type,
                "stripe_checkout_session_id": session.id,
            },
        )
        ga4_result = track_ga4_event_with_status(
            "checkout_session_created",
            logger,
            {
                "product_type": product_type,
                "amount_jpy": active_amount_jpy,
                "price_type": price_type,
            },
        )
        update_checkout_ga4_status(
            purchase_id,
            str(ga4_result.get("status") or "exception"),
            logger,
        )
        return session.url, None
    except Exception as exc:  # pragma: no cover - 外部API例外
        logger.exception("checkout_session_create_failed")
        return None, f"Stripe Checkout の準備に失敗しました: {exc}"


def retrieve_checkout_session(session_id: str) -> Any | None:
    if not session_id:
        return None
    try:
        stripe_ready = stripe_client_ready(PRODUCT_TYPE_REGULAR) or stripe_client_ready(PRODUCT_TYPE_REVIEW)
    except EnvironmentConfigError:
        return None
    if not stripe_ready:
        return None
    try:
        assert stripe is not None
        return stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return None


def sync_purchase_from_session(session_id: str, logger: logging.Logger) -> dict[str, Any] | None:
    session = retrieve_checkout_session(session_id)
    if not session:
        return None

    metadata = getattr(session, "metadata", None) or {}
    metadata_purchase_id = metadata.get("purchase_id") if hasattr(metadata, "get") else None
    client_reference_id = getattr(session, "client_reference_id", None)
    purchase_id = metadata_purchase_id or client_reference_id

    if not purchase_id:
        return None

    if metadata_purchase_id and client_reference_id and metadata_purchase_id != client_reference_id:
        logger.warning("checkout_session_purchase_id_mismatch")
        return None

    record = get_purchase_record(purchase_id)
    if not record:
        return None

    stored_session_id = record.get("stripe_checkout_session_id")
    retrieved_session_id = getattr(session, "id", None)
    if not stored_session_id or stored_session_id != retrieved_session_id:
        logger.warning(
            "checkout_session_record_mismatch",
            extra={"purchase_id": purchase_id},
        )
        return None

    if record.get("payment_status") != "paid":
        logger.info(
            "checkout_session_waiting_for_webhook",
            extra={
                "purchase_id": purchase_id,
                "payment_status": getattr(session, "payment_status", None),
            },
        )
    return with_restored_tracking_params(record, metadata)


def consume_purchase(purchase_id: str, logger: logging.Logger) -> bool:
    try:
        consumed = consume_purchase_transaction(
            purchase_id,
            str(st.session_state.get("active_access_token") or ""),
        )
    except Exception:
        logger.exception(
            "purchase_consume_failed",
            extra={"purchase_id": purchase_id},
        )
        return False
    if not consumed:
        return False
    logger.info(
        "purchase_consumed",
        extra={
            "env": APP_ENV,
            "purchase_id": purchase_id,
        },
    )
    return True


def claim_purchase_generation(purchase_id: str, logger: logging.Logger) -> str:
    try:
        status = claim_generation_transaction(
            purchase_id,
            str(st.session_state.get("active_access_token") or ""),
        )
    except Exception:
        logger.exception(
            "purchase_generation_claim_failed",
            extra={"purchase_id": purchase_id},
        )
        st.session_state.generation_claim_status = "error"
        return "error"

    if status == GENERATION_CLAIMED:
        logger.info(
            "purchase_generation_claimed",
            extra={"env": APP_ENV, "purchase_id": purchase_id},
        )
    elif status == GENERATION_CLAIM_PROCESSING:
        logger.info(
            "purchase_generation_already_processing",
            extra={"env": APP_ENV, "purchase_id": purchase_id},
        )
    else:
        logger.warning(
            "purchase_generation_claim_rejected",
            extra={"env": APP_ENV, "purchase_id": purchase_id, "claim_status": status},
        )
    st.session_state.generation_claim_status = status
    return status


def release_purchase_generation_claim(purchase_id: str, logger: logging.Logger) -> None:
    try:
        released = release_generation_claim_transaction(
            purchase_id,
            str(st.session_state.get("active_access_token") or ""),
        )
    except Exception:
        logger.exception(
            "purchase_generation_claim_release_failed",
            extra={"purchase_id": purchase_id},
        )
        return

    if released:
        logger.info(
            "purchase_generation_claim_released",
            extra={"env": APP_ENV, "purchase_id": purchase_id},
        )


def generate_regular_fortune_pdf_and_consume(
    payload: FortuneInput,
    purchase_id: str,
    logger: logging.Logger,
) -> tuple[dict[str, Any], bytes] | None:
    claim_status = claim_purchase_generation(purchase_id, logger)
    if claim_status != GENERATION_CLAIMED:
        return None

    try:
        result = call_gemini_fortune(payload)
        pdf_data = generate_miko_letter_pdf(payload.user_name, result)
    except Exception:
        release_purchase_generation_claim(purchase_id, logger)
        raise

    if not consume_purchase(purchase_id, logger):
        release_purchase_generation_claim(purchase_id, logger)
        return None
    return result, pdf_data


def generate_review_fortune_pdf_and_consume(
    uploaded_pdf_bytes: bytes,
    pdf_analysis: dict[str, Any],
    current_inputs: dict[str, Any],
    current_private_inputs: dict[str, Any],
    image_parts: list[Any],
    purchase_id: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    claim_status = claim_purchase_generation(purchase_id, logger)
    if claim_status != GENERATION_CLAIMED:
        return {"status": "claim_failed", "claim_status": claim_status}

    try:
        pdf_summary = call_gemini_review_pdf_summary(uploaded_pdf_bytes, pdf_analysis)
        if not pdf_summary.get("summary_success"):
            release_purchase_generation_claim(purchase_id, logger)
            return {
                "status": "summary_failed",
                "pdf_summary": pdf_summary,
            }

        review_context = build_review_context(
            pdf_analysis=pdf_analysis,
            previous_summary=pdf_summary.get("previous_summary") or {},
            current_inputs=current_inputs,
        )
        review_fortune_result = call_gemini_review_fortune(
            review_context=review_context,
            current_private_inputs=current_private_inputs,
            image_parts=image_parts,
        )
        if not review_fortune_result.get("fortune_success"):
            release_purchase_generation_claim(purchase_id, logger)
            return {
                "status": "fortune_failed",
                "review_fortune_result": review_fortune_result,
            }

        review_fortune = review_fortune_result.get("review_fortune") or {}
        pdf_data = generate_review_fortune_pdf(
            review_fortune=review_fortune,
            review_context=review_context,
        )
    except Exception:
        release_purchase_generation_claim(purchase_id, logger)
        raise

    if not consume_purchase(purchase_id, logger):
        release_purchase_generation_claim(purchase_id, logger)
        return {"status": "consume_failed"}

    return {
        "status": "success",
        "review_context": review_context,
        "review_fortune": review_fortune,
        "pdf_data": pdf_data,
    }


def get_current_purchase_record() -> dict[str, Any] | None:
    session_id = st.query_params.get("session_id")
    access_token = get_query_param_value("access_token")
    purchase_id = get_query_param_value("purchase_id")
    should_clean_purchase_query = False
    if session_id:
        synced_record = sync_purchase_from_session(str(session_id), logging.getLogger(__name__))
        if synced_record:
            if access_token:
                token_record = get_purchase_by_access_token(access_token)
                if (
                    token_record
                    and token_record.get("purchase_id") == synced_record.get("purchase_id")
                ):
                    st.session_state.active_access_token = access_token
            should_clean_purchase_query = bool(access_token or purchase_id or get_query_param_value("product_type"))
            if should_clean_purchase_query:
                st.session_state.active_purchase_id = synced_record.get("purchase_id")
                clean_purchase_query_params()
            return synced_record
    if access_token:
        token_record = get_purchase_by_access_token(access_token)
        if token_record and (not purchase_id or str(token_record.get("purchase_id") or "") == purchase_id):
            st.session_state.active_purchase_id = token_record.get("purchase_id")
            st.session_state.active_access_token = access_token
            clean_purchase_query_params()
            return token_record
    active_purchase_id = st.session_state.get("active_purchase_id")
    return get_purchase_record(active_purchase_id)


def clean_purchase_query_params() -> None:
    # Keep purchase_id/access_token/product_type so a paid, unused purchase can be restored after reloads.
    removable_keys = {"session_id"}
    remaining_params: dict[str, str] = {}
    for key in st.query_params:
        if key in removable_keys:
            continue
        value = get_query_param_value(key)
        if value is not None:
            remaining_params[key] = value
    st.query_params.clear()
    for key, value in remaining_params.items():
        st.query_params[key] = value


def render_checkout_link(checkout_url: str, amount_jpy: int) -> None:
    st.markdown(
        f'''
        <a href="{html.escape(checkout_url, quote=True)}" target="_self" style="text-decoration:none;">
            <div style="
                display:inline-block;
                padding:0.85rem 1.25rem;
                border-radius:999px;
                background:#b14d2c;
                color:#ffffff;
                font-weight:700;
                text-align:center;
                margin-top:0.5rem;
                margin-bottom:0.2rem;
            ">
                Stripe決済ページへ進む（{amount_jpy}円・1回のみ）
            </div>
        </a>
        ''',
        unsafe_allow_html=True,
    )



def render_direct_checkout(product_type: str, logger: logging.Logger) -> None:
    product_type = normalize_product_type(product_type)
    _, active_amount_jpy = get_active_checkout_price(product_type, logger)

    try:
        is_stripe_ready = stripe_client_ready(product_type)
    except EnvironmentConfigError as exc:
        logger.error("stripe_environment_config_error", extra={"reason": str(exc)})
        st.error("ただいま決済ページを準備できません。時間をおいてもう一度お試しください。")
        if SHOW_DEBUG:
            st.caption(str(exc))
        return

    if not is_stripe_ready:
        st.error("ただいま決済ページを準備できません。時間をおいてもう一度お試しください。")
        return

    checkout_url = st.session_state.get("checkout_url")
    if checkout_url and st.session_state.get("checkout_product_type") != product_type:
        clear_checkout_session_state()
        checkout_url = None

    if not checkout_url:
        checkout_url, error_message = create_checkout_session(product_type, logger)
        if error_message:
            st.error("決済ページを準備できませんでした。時間をおいてもう一度お試しください。")
            if SHOW_DEBUG:
                st.caption(error_message)
            return

    if product_type == PRODUCT_TYPE_REVIEW:
        st.markdown("## 龍神さまのお告げ 見返し便")
        st.markdown(
            "前回の鑑定PDFをもとに、現在の手相画像・近況・見返したいテーマを重ねて、"
            "今のあなたに向けたお告げをお届けします。"
        )
        st.markdown(
            f"**ご利用料金：{active_amount_jpy}円（税込）**  "
            "\n1回の購入につき、鑑定の実行は1回のみです。  "
            "\n決済完了後、入力フォームが表示されます。"
        )
    else:
        st.markdown("## 龍神さまのお告げ")
        st.markdown(
            f"**ご利用料金：{active_amount_jpy}円（税込）**  "
            "\n1回の購入につき、鑑定の実行は1回のみです。  "
            "\n決済完了後、入力フォームが表示されます。"
        )
        st.info("下のボタンを押すと、Stripeの決済ページへ移動します。")

    render_checkout_link(checkout_url, active_amount_jpy)

    if product_type == PRODUCT_TYPE_REVIEW:
        st.info("決済が完了すると、このページに戻り、見返し便フォームが表示されます。")


def render_pre_payment_intro(product_type: str, active_amount_jpy: int) -> None:
    product_name = html.escape(get_product_display_name(product_type))
    review_note = ""
    price_note = f"1回{active_amount_jpy}円（税込）でご利用いただけます。"
    if product_type == PRODUCT_TYPE_REVIEW:
        price_note = (
            f"販売予定価格は{REVIEW_PLANNED_AMOUNT_JPY}円（税込）です。<br>"
            f'<span class="review-start-price">現在は、はじめての見返し便として、しばらくの間はスタート記念価格{active_amount_jpy}円（税込）でご案内しています。</span>'
        )
        review_note = (
            '<div style="margin-top:0.55rem;">'
            "前回のお告げPDFをもとに、今の手相画像・近況・見返したいテーマを重ねて、運勢の流れをあらためて読み直します。"
            "</div>"
        )
    st.markdown(
        f'''
        <div style="border:1px solid #eadfd8; background:#fffdf9; border-radius:14px; padding:16px 18px; margin:0.4rem 0 1rem 0; color:#3b312d; line-height:1.8;">
            <div>ここは、ケモノ町の龍神さまから、今のあなたへひとつ言葉を受け取るためのページです。</div>
            <div style="font-weight:700; margin-top:0.55rem;">商品種別：{product_name}</div>
            <div style="margin-top:0.55rem;">所要時間は3〜5分ほどです。</div>
            <div>{price_note}</div>
            <div>決済完了後、こちらのページに戻ると入力フォームが表示されます。</div>
            {review_note}
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_usage_flow(active_amount_jpy: int) -> None:
    st.markdown('<div class="heading-lg">ご利用の流れ</div>', unsafe_allow_html=True)
    st.markdown(
        f'''
1. {active_amount_jpy}円の決済ページへ進む
2. 決済完了後、こちらのページに戻る
3. 入力フォームに記入する
4. お告げPDFを受け取る
'''
    )


def render_pdf_sample_section() -> None:
    st.markdown('<div class="heading-lg">お届けするPDFの見本</div>', unsafe_allow_html=True)
    st.markdown(
        '''
決済後は、このようなPDF形式のお告げを受け取れます。
内容の雰囲気を知りたい方は、下の見本をご覧ください。

※画像はサンプルです。
'''
    )

    columns = st.columns(3)
    for index, image_path in enumerate(SAMPLE_PDF_IMAGE_PATHS, start=1):
        with columns[index - 1]:
            image_bytes = read_image_bytes(image_path)
            if image_bytes:
                render_inline_png(
                    image_bytes,
                    alt=f"PDF見本 {index}ページ目",
                    caption=f"PDF見本 {index}ページ目",
                )
            else:
                st.caption(f"PDF見本 {index}ページ目の画像を準備中です。")


def render_pdf_contents_summary() -> None:
    st.markdown('<div class="heading-lg">PDFに含まれる主な内容</div>', unsafe_allow_html=True)
    st.markdown(
        '''
お告げPDFには、今のあなたに向けた言葉として、次のような内容が含まれます。

・直近：これから3カ月以内の運勢  
・展望：これから1年先の運勢  
・未来：2〜3年後の運勢  
・巫女の助言：開運アイテム、開運スポット、開運カラーなど  
・心に留めること

占いや診断の結果を断定するものではなく、今の気分を少し整えるための読みものとしてお楽しみください。
'''
    )


def render_checkout_reassurance(product_type: str, active_amount_jpy: int) -> None:
    form_label = "見返し便フォーム" if product_type == PRODUCT_TYPE_REVIEW else "鑑定フォーム"
    usage_notes = [
        f'<div style="margin-bottom:0.25rem;">・本サービスは1回{active_amount_jpy}円（税込）の単発課金です。</div>',
        '<div style="margin-bottom:0.25rem;">・月額課金や継続課金ではありません。</div>',
        '<div style="margin-bottom:0.25rem;">・お支払いはStripeの安全な決済ページで行います。</div>',
        '<div style="margin-bottom:0.25rem;">・クレジットカードのほか、ご利用環境によってはApple Pay、Google Pay、Linkなどの決済方法を選べる場合があります。</div>',
        '<div style="margin-bottom:0.25rem;">・こちらのページでは、クレジットカード番号を保存しません。</div>',
        f'<div style="margin-bottom:0.25rem;">・決済完了後、こちらのページに戻ると{form_label}が表示されます。</div>',
    ]
    if product_type == PRODUCT_TYPE_REVIEW:
        usage_notes.append(
            '<div style="margin-bottom:0.25rem;">・見返し便では、前回の鑑定PDFと現在の手相画像をご用意ください。</div>'
        )
    usage_notes.append('<div>・1回の購入につき、鑑定の実行は1回のみです。</div>')
    usage_notes_html = "\n".join(usage_notes)
    st.markdown(
        f'''
        <div style="border:1px solid #e5d7d1; background:#fffdfa; border-radius:14px; padding:14px 16px; margin:0.3rem 0 0.7rem 0; color:#3b312d; line-height:1.8;">
            <div style="font-weight:700; margin-bottom:0.45rem;">有料版のご利用について</div>
            {usage_notes_html}
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_payment_section(
    product_type: str,
    logger: logging.Logger,
    allow_checkout_creation: bool = True,
) -> dict[str, Any] | None:
    product_type = normalize_product_type(product_type)
    _, active_amount_jpy = get_active_checkout_price(product_type, logger)
    render_pre_payment_intro(product_type, active_amount_jpy)
    render_usage_flow(active_amount_jpy)
    render_pdf_sample_section()
    render_pdf_contents_summary()

    st.markdown('<div class="heading-lg">💳 ご利用手続き</div>', unsafe_allow_html=True)

    if not STRIPE_ENABLED:
        st.error("ただいま決済ページを準備できません。時間をおいてもう一度お試しください。")
        if SHOW_DEBUG:
            st.caption(f"APP_BASE_URL={APP_BASE_URL} / WIX_CANCEL_URL={WIX_CANCEL_URL}")
        return None

    record = get_current_purchase_record()

    if is_purchase_ready(record):
        st.success("決済確認が完了しました。鑑定フォームをご利用いただけます。")
        return record

    session_id = st.query_params.get("session_id")
    if session_id and record and record.get("payment_status") != "paid":
        st.info("決済結果を確認中です。数秒後に再読み込みしてください。")

    if record and record.get("used_flag"):
        st.warning("この購入分はすでに使用済みです。再度ご利用の際は、新しくご購入ください。")

    if not allow_checkout_creation:
        st.info("決済結果を確認中です。数秒後に再読み込みしてください。")
        return None

    checkout_url = st.session_state.get("checkout_url")
    if checkout_url and st.session_state.get("checkout_product_type") != product_type:
        clear_checkout_session_state()
        checkout_url = None

    if not checkout_url:
        checkout_url, error_message = create_checkout_session(product_type, logger)
        if error_message:
            st.error("決済ページを準備できませんでした。時間をおいてもう一度お試しください。")
            if SHOW_DEBUG:
                st.caption(error_message)
            return None

    if checkout_url:
        render_checkout_reassurance(product_type, active_amount_jpy)
        render_checkout_link(checkout_url, active_amount_jpy)

    return None




def get_completion_screen_content(product_type: str) -> dict[str, str]:
    product_type = normalize_product_type(product_type)
    if product_type == PRODUCT_TYPE_REVIEW:
        return {
            "heading": "見返し便のお告げは完了しました",
            "thanks_body": (
                "ご利用ありがとうございました。\n\n"
                "今回の見返し便PDFも、あとから読み返せるように保存しておくことをおすすめします。\n"
                "この画面を閉じる前に、PDFの保存をご確認ください。"
            ),
            "guide_heading": "前回と今回のお告げを、これからの流れに活かしたい方へ",
            "guide_body": (
                "前回のお告げと今回のお告げを見比べることで、\n"
                "今の流れや、少しずつ変わってきたことに気づきやすくなります。\n\n"
                "また季節が変わったときや、\n"
                "気持ちや状況に変化があったときには、\n"
                "今回のPDFをもとに、あらためて見返し便をご利用いただけます。"
            ),
            "primary_label": "見返し便ページに戻る",
            "primary_url": REVIEW_LP_URL,
            "secondary_label": "OMOSHIRO CRE8 WORKS トップに戻る",
            "secondary_url": WIX_SITE_TOP_URL,
            "illustration_path": REVIEW_COMPLETION_ILLUSTRATION,
            "illustration_alt": "NICOがお告げPDFを読んでいるイラスト",
        }

    return {
        "heading": "龍神さまのお告げは完了しました",
        "thanks_body": (
            "ご利用ありがとうございました。\n\n"
            "お告げPDFは、あとから見返せるように保存しておくことをおすすめします。\n"
            "この画面を閉じる前に、PDFの保存をご確認ください。"
        ),
        "guide_heading": "龍神さまのお告げ『見返し便』のご紹介",
        "guide_body": (
            "今回のお告げを少し時間をおいて読み返すことで、\n"
            "違った気づきが見えてくることもあります。\n\n"
            "しばらく経ってから『見返し便』をご利用いただくことで、\n"
            "そのときの手相や近況、お手元のお告げPDFをもとに、\n"
            "前のお告げから流れがどのように変化してきたかを\n"
            "あらためて見直すことができます。"
        ),
        "primary_label": "見返し便をくわしく見る",
        "primary_url": REVIEW_LP_URL,
        "secondary_label": "OMOSHIRO CRE8 WORKS トップに戻る",
        "secondary_url": WIX_SITE_TOP_URL,
        "illustration_path": REGULAR_COMPLETION_ILLUSTRATION,
        "illustration_alt": "巫女が鑑定書を2つ持っているイラスト",
    }


def normalize_url_for_comparison(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def should_show_review_completion_cta(url: str | None) -> bool:
    normalized_url = normalize_url_for_comparison(url)
    if not normalized_url:
        return False
    blocked_urls = {
        normalize_url_for_comparison(APP_BASE_URL),
        normalize_url_for_comparison(REGULAR_TOP_URL),
    }
    return normalized_url not in blocked_urls


def render_completion_link_button(
    *,
    label: str,
    url: str,
    primary: bool,
    margin_top_rem: float,
) -> None:
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label)
    if primary:
        style = (
            "background:#b6552d; color:white; padding:0.8rem 1.25rem; "
            "border-radius:999px; text-decoration:none; font-weight:700; line-height:1.5;"
        )
    else:
        style = (
            "background:#fff7f4; color:#8a3d24; padding:0.72rem 1.1rem; "
            "border:1px solid #d9b3a2; border-radius:999px; text-decoration:none; "
            "font-weight:700; line-height:1.5;"
        )
    st.html(
        f'''
        <div style="text-align:center; margin-top:{margin_top_rem:.2f}rem;">
            <a href="{safe_url}" target="_self"
               style="display:inline-block; width:min(100%, 320px); box-sizing:border-box; text-align:center; {style}">
                {safe_label}
            </a>
        </div>
        '''
    )


def render_completion_guide_block(content: dict[str, str], guide_body_html: str) -> None:
    illustration_path = (content.get("illustration_path") or "").strip()
    illustration_html = ""
    if illustration_path:
        illustration_bytes = read_image_bytes(illustration_path)
        if illustration_bytes:
            encoded = base64.b64encode(illustration_bytes).decode("ascii")
            safe_alt = html.escape(content.get("illustration_alt") or "完了画面補助イラスト", quote=True)
            illustration_html = f'''
            <figure style="flex:0 1 220px; min-width:160px; margin:0; text-align:center;">
                <img
                    src="data:image/png;base64,{encoded}"
                    alt="{safe_alt}"
                    style="width:min(100%, 220px); max-height:260px; height:auto; object-fit:contain; display:block; margin:0 auto;"
                >
            </figure>
            '''

    st.html(
        f'''
        <div style="border:1px solid #ead5cb; border-radius:14px; padding:16px 18px;
                    background:#fffdfa; margin-top:1.1rem; margin-bottom:0.9rem;
                    box-shadow:0 1px 0 rgba(0, 0, 0, 0.02);">
            <div style="font-size:1.35rem; font-weight:700; color:#8a3d24;
                        margin-bottom:0.8rem; line-height:1.6;">
                {html.escape(content["guide_heading"])}
            </div>
            <div style="display:flex; align-items:center; justify-content:space-between;
                        gap:1.1rem 1.4rem; flex-wrap:wrap;">
                <div style="line-height:1.9; color:#2f2f2f; font-size:0.98rem;
                            text-align:left; font-weight:500; flex:1 1 250px; min-width:0;">
                    {guide_body_html}
                </div>
                {illustration_html}
            </div>
        </div>
        '''
    )


def render_completion_screen(product_type: str | None = None) -> None:
    content = get_completion_screen_content(normalize_product_type(product_type))
    scroll_completion_screen_to_top()
    render_form_gap(2)
    left, center, right = st.columns([1, 1.4, 1])
    with center:
        miko_image_bytes = read_image_bytes(MIKO_IMAGE_PATH)
        if miko_image_bytes:
            render_completion_miko_image(miko_image_bytes)

    thanks_html = "<br>".join(html.escape(line) for line in content["thanks_body"].split("\n"))
    guide_body_html = "<br>".join(html.escape(line.strip()) for line in content["guide_body"].split("\n"))

    st.markdown(
        f"""
        <h2 style="text-align:center; color:#8B4513; margin-top:0.8rem; line-height:1.55;">
            {html.escape(content["heading"])}
        </h2>
        <p style="text-align:center; line-height:1.9; margin-top:0.6rem;">
            {thanks_html}
        </p>
        """,
        unsafe_allow_html=True,
    )

    render_completion_guide_block(content, guide_body_html)


    has_primary_button = should_show_review_completion_cta(content.get("primary_url"))
    if has_primary_button:
        render_completion_link_button(
            label=content["primary_label"],
            url=content["primary_url"],
            primary=True,
            margin_top_rem=1.35,
        )

    render_completion_link_button(
        label=content["secondary_label"],
        url=content["secondary_url"] or REGULAR_TOP_URL,
        primary=False,
        margin_top_rem=0.75 if has_primary_button else 1.35,
    )


def render_header(title_top_gap_rem: float = 0.1, header_top_gap_rem: float = 0.0) -> None:
    if header_top_gap_rem > 0:
        st.markdown(
            f'<div style="height:{header_top_gap_rem:.2f}rem"></div>',
            unsafe_allow_html=True,
        )
    header_left, header_right = st.columns([1, 4])
    with header_left:
        miko_image_bytes = read_image_bytes(MIKO_IMAGE_PATH)
        if miko_image_bytes:
            st.html('<div style="height:0.6rem"></div>')
            render_inline_png(miko_image_bytes, alt="巫女画像", width=96)
        else:
            st.caption("miko画像なし")

    with header_right:
        title_style = f"margin-top:{title_top_gap_rem:.2f}rem !important;"
        st.markdown(
            f'<div class="title-main" style="{title_style}">{html.escape(APP_TITLE)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="result-body" style="margin-bottom:1.2rem;">{html.escape(APP_SUBTITLE)}</div>',
            unsafe_allow_html=True,
        )


def render_notice_box() -> None:
    with st.expander("ご利用前にご確認ください", expanded=False):
        st.markdown(
            '''本サービスは、参考情報としてお楽しみいただくためのものです。

医療・法律・投資などの重要な判断には利用しないでください。

入力内容は、鑑定結果の生成とPDF作成のために使用します。

決済確認に必要な最小限の情報を、一時的に保存します。
'''
        )


def render_review_fortune_form(active_purchase: dict[str, Any], logger: logging.Logger) -> None:
    purchase_id = active_purchase.get("purchase_id")
    product_type = get_purchase_product_type(active_purchase)
    tracked_purchase_ids = st.session_state.ga4_form_displayed_purchase_ids
    if purchase_id and purchase_id not in tracked_purchase_ids:
        track_ga4_event("form_displayed", logger, {"product_type": product_type})
        tracked_purchase_ids.add(purchase_id)

    st.caption("見返し便は、前回のお告げと今の状態を照らし合わせるための入力フォームです。")

    render_form_gap(2)
    st.markdown('<div class="heading-lg">📋 見返し便の準備</div>', unsafe_allow_html=True)

    st.markdown('<div class="label-sm">前回鑑定PDF</div>', unsafe_allow_html=True)
    st.markdown(
        f'''
前回お届けした「龍神さまのお告げ」の鑑定PDFをアップロードしてください。

別のPDFや、内容を確認できないPDFをアップロードされた場合は、見返し便を作成できないことがあります。

このアプリでは、{MAX_REVIEW_PDF_SIZE_MB}MB以内のPDFを使用してください。
''',
    )
    uploaded_pdf = st.file_uploader(
        f"前回鑑定PDF（PDF形式 / {MAX_REVIEW_PDF_SIZE_MB}MBまで）",
        type=["pdf"],
        accept_multiple_files=False,
        key="review_previous_pdf",
    )

    render_form_gap(2)

    st.markdown('<div class="label-sm">氏名（漢字）</div>', unsafe_allow_html=True)
    last_col, first_col = st.columns(2)
    with last_col:
        last_name = st.text_input("姓", placeholder="山田", key="review_last_name")
    with first_col:
        first_name = st.text_input("名", placeholder="太郎", key="review_first_name")
    user_name = normalize_text(f"{last_name} {first_name}".strip())

    render_form_gap(2)

    st.markdown('<div class="label-sm">生年月日</div>', unsafe_allow_html=True)
    today = datetime.date.today()
    year_options = ["年を選択"] + list(range(today.year, 1899, -1))
    month_options = ["月を選択"] + list(range(1, 13))
    day_options = ["日を選択"] + list(range(1, 32))
    date_col1, date_col2, date_col3 = st.columns(3)
    with date_col1:
        birth_year = st.selectbox("年", year_options, index=0, key="review_birth_year")
    with date_col2:
        birth_month = st.selectbox("月", month_options, index=0, key="review_birth_month")
    with date_col3:
        birth_day_candidate = st.selectbox("日", day_options, index=0, key="review_birth_day")

    birth_date = None
    if (
        birth_year != "年を選択"
        and birth_month != "月を選択"
        and birth_day_candidate != "日を選択"
    ):
        try:
            birth_date = datetime.date(
                int(birth_year), int(birth_month), int(birth_day_candidate)
            )
        except ValueError:
            st.error("存在しない日付です。生年月日を確認してください。")
            birth_date = None

    render_form_gap(2)

    st.markdown('<div class="label-sm">出生時間（任意・わかる範囲で）</div>', unsafe_allow_html=True)
    st.caption("出生時間が分かる場合は選択してください。不明でもお申し込みいただけます。")
    review_birth_time_accuracy = st.radio(
        "出生時間の分かり具合",
        TIME_ACCURACY_OPTIONS,
        horizontal=True,
        index=0,
        key="review_birth_time_accuracy",
    )
    st.markdown(
        f'<div class="input-help">選択中：{html.escape(review_birth_time_accuracy)}</div>',
        unsafe_allow_html=True,
    )

    review_birth_hour = None
    review_birth_minute = None
    if review_birth_time_accuracy != "不明":
        time_col1, time_col2 = st.columns(2)
        with time_col1:
            review_birth_hour = st.selectbox("時", HOUR_OPTIONS, index=12, key="review_birth_hour")
        with time_col2:
            review_birth_minute = st.selectbox("分", MINUTE_OPTIONS, index=0, key="review_birth_minute")

    review_birth_time_text = format_birth_time_text(
        review_birth_time_accuracy,
        review_birth_hour,
        review_birth_minute,
    )

    render_form_gap(2)

    st.markdown('<div class="label-sm">出生地</div>', unsafe_allow_html=True)
    review_birth_place = st.text_input("出生地", placeholder="東京都", key="review_birth_place")

    render_form_gap(2)

    st.markdown('<div class="label-sm">現在の手相画像</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="input-help">現在の手相画像をアップロードしてください。前回からの変化を見るため、できるだけ最近撮影した画像をお使いください。画像は最大{MAX_IMAGE_FILES}枚までです。</div>',
        unsafe_allow_html=True,
    )
    uploaded_files = st.file_uploader(
        f"現在の手相画像（最大 {MAX_IMAGE_FILES} 枚 / 1枚 {MAX_IMAGE_SIZE_MB}MBまで）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="review_palm_images",
    )

    hand_sides = []
    if uploaded_files:
        st.markdown('<div class="input-help">各画像の左右を選んでください。</div>', unsafe_allow_html=True)
        hand_sides = build_selected_hand_sides(uploaded_files)

    render_form_gap(2)

    st.markdown('<div class="label-sm">今回とくに見返したいテーマ</div>', unsafe_allow_html=True)
    review_theme_options = ["（未選択）"] + CATEGORY_OPTIONS
    selected_review_theme = st.selectbox(
        "今回とくに見返したいテーマ",
        review_theme_options,
        index=0,
        key="review_theme",
    )
    review_theme = "" if selected_review_theme == "（未選択）" else selected_review_theme

    render_form_gap(2)

    st.markdown('<div class="label-sm">近況メモ</div>', unsafe_allow_html=True)
    st.caption(f"前回のお告げを受け取ってから、変化したこと、今気になっていること、選択したテーマに関する現在の状況を{MAX_REVIEW_MEMO_LENGTH}字以内で書いてください。")
    review_memo = st.text_area(
        "近況メモ",
        placeholder="例: 前回のお告げから3カ月ほど経ち、仕事の進め方や人間関係に変化がありました。最近特に気になっていることは...",
        height=160,
        max_chars=MAX_REVIEW_MEMO_LENGTH,
        key="review_memo",
    )

    render_form_gap(2)

    purchase_id = active_purchase.get("purchase_id")
    review_fortune_generated = (
        bool(st.session_state.get("review_fortune"))
        and st.session_state.get("review_fortune_purchase_id") == purchase_id
    )
    review_pdf_generated = (
        bool(st.session_state.get("review_pdf_bytes"))
        and st.session_state.get("review_pdf_generated_purchase_id") == purchase_id
    )
    review_generation_completed = review_fortune_generated or review_pdf_generated
    review_submit_placeholder = st.empty()
    review_submit_clicked = False
    if not review_generation_completed:
        with review_submit_placeholder:
            review_submit_clicked = st.button("🐉 見返し便の鑑定本文を生成する", key="review_submit")

    if review_submit_clicked:
        st.session_state.review_context = None
        st.session_state.review_fortune = None
        st.session_state.review_fortune_purchase_id = None
        st.session_state.review_pdf_bytes = None
        st.session_state.review_pdf_generated_purchase_id = None
        record = get_purchase_record(active_purchase.get("purchase_id"))
        if get_purchase_product_type(record) != PRODUCT_TYPE_REVIEW:
            st.error("見返し便の購入情報を確認できませんでした。ページを再読み込みして状態をご確認ください。")
            st.stop()
        if not is_purchase_ready(record):
            st.error("決済済みかつ未使用の購入情報が確認できませんでした。ページを再読み込みして状態をご確認ください。")
            st.stop()

        errors = validate_review_inputs(
            user_name=user_name,
            birth_date_selected=birth_date is not None,
            birth_place=review_birth_place,
            review_theme=review_theme,
            uploaded_pdf=uploaded_pdf,
            uploaded_files=uploaded_files or [],
            hand_sides=hand_sides,
            review_memo=review_memo,
        )

        if errors:
            st.error("入力内容に確認事項があります。")
            for err in list(dict.fromkeys(errors)):
                st.error(err)
        else:
            uploaded_pdf_bytes = uploaded_pdf.getvalue()
            with st.spinner("前回PDFを確認しています..."):
                pdf_analysis = validate_review_pdf_content(uploaded_pdf_bytes)

            if not pdf_analysis.get("is_valid_previous_pdf"):
                st.error("アップロードされたPDFから、前回の「龍神さまのお告げ」鑑定PDFであることを十分に確認できませんでした。")
                st.error("前回お届けした鑑定PDFをご確認のうえ、再アップロードしてください。")
                if SHOW_DEBUG:
                    st.caption(str(pdf_analysis.get("reason") or "判定理由を取得できませんでした。"))
                return

            previous_reading_date = str(pdf_analysis.get("previous_reading_date") or "")
            if not previous_reading_date:
                st.error("アップロードされたPDFから、前回鑑定日を確認できませんでした。")
                st.error("前回お届けした「龍神さまのお告げ」の鑑定PDFかどうかをご確認のうえ、再アップロードしてください。")
                return

            try:
                image_parts = build_image_parts(uploaded_files or [])
            except Exception as exc:
                st.error("現在の手相画像の読み込み中にエラーが発生しました。")
                if SHOW_DEBUG:
                    st.caption(f"error_type={type(exc).__name__} / failed_step=build_image_parts")
                return

            palm_image_count = len(uploaded_files or [])
            current_inputs = {
                "birth_place": normalize_text(review_birth_place),
                "birth_time_accuracy": review_birth_time_accuracy,
                "birth_time_text": review_birth_time_text,
                "selected_theme": review_theme,
                "review_theme": review_theme,
                "review_memo_present": bool(normalize_text(review_memo)),
                "palm_image_count": palm_image_count,
            }
            current_private_inputs = {
                "user_name": normalize_text(user_name),
                "birth_date": birth_date.isoformat() if birth_date else "",
                "birth_place": normalize_text(review_birth_place),
                "birth_time_accuracy": review_birth_time_accuracy,
                "birth_time_text": review_birth_time_text,
                "selected_theme": review_theme,
                "review_theme": review_theme,
                "review_memo": normalize_text(review_memo),
                "recent_note": normalize_text(review_memo),
                "palm_image_count": palm_image_count,
                "current_palm_image_status": "attached" if palm_image_count > 0 else "not_attached",
                "palm_image_information": {
                    "image_count": palm_image_count,
                    "status": "attached" if palm_image_count > 0 else "not_attached",
                },
            }
            purchase_id = str(active_purchase.get("purchase_id") or "")
            try:
                with st.spinner("前回のお告げを要約し、見返し便の鑑定とPDFを生成しています..."):
                    track_purchase_ga4_event_once(
                        "reading_started",
                        purchase_id,
                        product_type,
                        logger,
                    )
                    completed = generate_review_fortune_pdf_and_consume(
                        uploaded_pdf_bytes=uploaded_pdf_bytes,
                        pdf_analysis=pdf_analysis,
                        current_inputs=current_inputs,
                        current_private_inputs=current_private_inputs,
                        image_parts=image_parts,
                        purchase_id=purchase_id,
                        logger=logger,
                    )
            except Exception as exc:
                st.error("見返し便PDFの生成中にエラーが発生しました。")
                st.error("ページを再読み込みせず、時間をおいてもう一度お試しください。")
                if SHOW_DEBUG:
                    st.caption(
                        f"error_type={type(exc).__name__} / "
                        f"failed_step=generate_review_fortune_pdf / "
                        f"purchase_id={active_purchase.get('purchase_id')} / "
                        f"product_type={product_type}"
                    )
                return

            if completed.get("status") == "claim_failed":
                if completed.get("claim_status") == GENERATION_CLAIM_PROCESSING:
                    st.info("現在処理中です。完了までお待ちください。")
                else:
                    st.error("購入権の確認に失敗しました。")
                    st.error("ページを更新せず、時間をおいて再度お試しください。")
                    st.error("解消しない場合は、お問い合わせください。")
                return

            if completed.get("status") == "summary_failed":
                st.error("前回PDFの要約中にエラーが発生しました。")
                st.error("時間をおいてもう一度お試しください。")
                if SHOW_DEBUG:
                    pdf_summary = completed.get("pdf_summary") or {}
                    diagnostics = pdf_summary.get("diagnostics") or {}
                    st.caption(
                        f"failed_step={diagnostics.get('failed_step', '')} / "
                        f"error_type={diagnostics.get('error_type', '')} / "
                        f"model_name={diagnostics.get('model_name', GEMINI_MODEL)} / "
                        f"pdf_size_bytes={diagnostics.get('pdf_size_bytes', len(uploaded_pdf_bytes))} / "
                        f"mime_type={diagnostics.get('mime_type', 'application/pdf')}"
                    )
                return

            if completed.get("status") == "fortune_failed":
                st.error("見返し便の鑑定本文生成中にエラーが発生しました。")
                st.error("時間をおいてもう一度お試しください。")
                if SHOW_DEBUG:
                    review_fortune_result = completed.get("review_fortune_result") or {}
                    diagnostics = review_fortune_result.get("diagnostics") or {}
                    st.caption(
                        f"failed_step={diagnostics.get('failed_step', '')} / "
                        f"error_type={diagnostics.get('error_type', '')} / "
                        f"model_name={diagnostics.get('model_name', GEMINI_MODEL)}"
                    )
                return

            if completed.get("status") == "consume_failed":
                st.error("購入権の確認に失敗しました。")
                st.error("ページを更新せず、時間をおいて再度お試しください。")
                st.error("解消しない場合は、お問い合わせください。")
                return

            review_context = completed.get("review_context") or {}
            st.session_state.review_context = review_context
            st.session_state.review_fortune = completed.get("review_fortune") or {}
            st.session_state.review_fortune_purchase_id = active_purchase.get("purchase_id")
            st.session_state.review_pdf_bytes = completed.get("pdf_data")
            st.session_state.review_pdf_generated_purchase_id = active_purchase.get("purchase_id")
            st.session_state.review_purchase_consumed.add(purchase_id)
            review_submit_placeholder.empty()

            previous_reading_date_label = format_iso_date_japanese(previous_reading_date)
            current_reference_text = (
                "現在の手相・近況・見返したいテーマ"
                if len(uploaded_files or []) > 0
                else "現在の近況・見返したいテーマ"
            )
            st.success("前回PDFの確認と要約が完了しました。")
            st.info(
                f"添付いただいた前回の鑑定は、{previous_reading_date_label}のお告げとして読み取れました。\n\n"
                "前回のお告げから現在までの流れを整理しました。\n\n"
                f"今回の見返し便では、前回のお告げを当たり外れで判断するのではなく、{current_reference_text}と重ねて、今あらためて見えてくる流れを読み直します。\n\n"
                "見返し便の鑑定本文とPDFを生成しました。内容をご確認ください。"
            )
            if SHOW_DEBUG:
                timeline = review_context.get("review_context", {}).get("timeline_reinterpretation", {})
                st.caption(
                    f"review_pdf_uploaded={uploaded_pdf is not None} / "
                    f"review_pdf_size_bytes={len(uploaded_pdf_bytes)} / "
                    f"review_image_count={len(uploaded_files or [])} / "
                    f"review_birth_time_present={review_birth_time_text != '不明'} / "
                    f"previous_reading_date_confidence={pdf_analysis.get('previous_reading_date_confidence')} / "
                    f"days_since_previous_reading={pdf_analysis.get('days_since_previous_reading')} / "
                    f"recent_3_months_status={timeline.get('recent_3_months_status')} / "
                    f"one_year_status={timeline.get('one_year_status')} / "
                    f"two_to_three_years_status={timeline.get('two_to_three_years_status')}"
                )

    review_fortune = st.session_state.get("review_fortune")
    purchase_id = active_purchase.get("purchase_id")
    if review_fortune and st.session_state.get("review_fortune_purchase_id") == purchase_id:
        render_form_gap(2)
        st.markdown('<div class="heading-lg">📜 見返し便の鑑定本文</div>', unsafe_allow_html=True)
        raw_review_summary_points = review_fortune.get("review_summary_points")
        review_summary_points = [
            str(point).strip()
            for point in (raw_review_summary_points if isinstance(raw_review_summary_points, list) else [])
            if str(point).strip()
        ]
        summary_text = "\n".join(f"・{point}" for point in review_summary_points)

        comparison_text = format_review_comparison_blocks(review_fortune)

        raw_action_items = review_fortune.get("next_3_month_action_items")
        action_items = [
            str(item).strip()
            for item in (raw_action_items if isinstance(raw_action_items, list) else [])
            if str(item).strip()
        ]
        action_text = "\n".join(
            [
                "これから3カ月は、以下のような小さな行動を意識するとよさそうです。",
                "",
                *[f"・{item}" for item in action_items],
            ]
        ) if action_items else ""

        def join_review_parts(parts):
            return "\n\n".join(part for part in (str(value or "").strip() for value in parts) if part)

        review_fortune_sections = [
            ("前回のお告げの振り返り", str(review_fortune.get("intro") or "").strip() or summary_text),
            (
                "前回のお告げと現在の状況との照らし合わせ",
                join_review_parts([
                    comparison_text,
                    review_fortune.get("current_changes"),
                    review_fortune.get("theme_review"),
                ]),
            ),
            (
                "これから3カ月ほど意識したいことや小さな行動",
                join_review_parts([review_fortune.get("next_3_months"), action_text]),
            ),
            ("1年先に向けて整えていくこと", review_fortune.get("one_year_guidance")),
            ("龍神さまからの見返しのことば", review_fortune.get("ryujin_message")),
            ("巫女の助言", review_fortune.get("miko_advice")),
            ("結び", review_fortune.get("things_to_remember")),
        ]
        for title, text in review_fortune_sections:
            render_html_box(title, str(text or ""))
        review_pdf_bytes = st.session_state.get("review_pdf_bytes")
        review_pdf_purchase_id = st.session_state.get("review_pdf_generated_purchase_id")
        if review_pdf_bytes and review_pdf_purchase_id == purchase_id:
            tracked_purchase_ids = st.session_state.ga4_pdf_generated_purchase_ids
            if purchase_id and purchase_id not in tracked_purchase_ids:
                if track_purchase_ga4_event_once("pdf_generated", purchase_id, product_type, logger):
                    tracked_purchase_ids.add(purchase_id)
            today_text = datetime.date.today().strftime("%Y%m%d")
            st.download_button(
                label="見返し便PDFをダウンロードする",
                data=review_pdf_bytes,
                file_name=f"ryujin_review_fortune_{today_text}.pdf",
                mime="application/pdf",
                key=f"review_pdf_download_{purchase_id}",
            )

            consumed_purchase_ids = st.session_state.review_purchase_consumed
            if purchase_id and purchase_id in consumed_purchase_ids:
                st.success("PDFの準備が完了しました。今回の購入分は使用済みになりました。")
        else:
            st.warning("見返し便PDFの準備がまだ完了していません。もう一度生成をお試しください。")


def render_pre_info() -> None:
    with st.expander("ご利用前のご案内", expanded=False):
        st.markdown(
            '''**この鑑定について**  
本アプリの鑑定結果は、参考情報としてお楽しみいただくためのものです。結果の正確性や、未来の出来事の実現を保証するものではありません。

**免責事項**  
本アプリの鑑定結果は、医療・法律・税務・投資その他の専門的助言に代わるものではありません。重要な判断は、ご自身の責任で行い、必要に応じて専門家へご相談ください。

**個人情報の取り扱い**  
ご入力いただいた氏名、生年月日、出生地、手相画像などの情報は、鑑定結果の生成確認のために一時的に使用します。
'''
        )


def render_fortune_form(active_purchase: dict[str, Any], logger: logging.Logger) -> None:
    purchase_id = active_purchase.get("purchase_id")
    product_type = get_purchase_product_type(active_purchase)
    tracked_purchase_ids = st.session_state.ga4_form_displayed_purchase_ids
    if purchase_id and purchase_id not in tracked_purchase_ids:
        track_ga4_event("form_displayed", logger, {"product_type": product_type})
        tracked_purchase_ids.add(purchase_id)

    st.caption("本アプリの鑑定は参考情報としてお楽しみください。")

    render_form_gap(2)
    st.markdown('<div class="heading-lg">📋 鑑定の準備</div>', unsafe_allow_html=True)

    st.markdown('<div class="label-sm">氏名（漢字）</div>', unsafe_allow_html=True)
    last_col, first_col = st.columns(2)
    with last_col:
        last_name = st.text_input("姓", placeholder="山田")
    with first_col:
        first_name = st.text_input("名", placeholder="太郎")
    user_name = normalize_text(f"{last_name} {first_name}".strip())

    render_form_gap(2)

    st.markdown('<div class="label-sm">生年月日</div>', unsafe_allow_html=True)
    today = datetime.date.today()
    year_options = ["年を選択"] + list(range(today.year, 1899, -1))
    month_options = ["月を選択"] + list(range(1, 13))
    day_options = ["日を選択"] + list(range(1, 32))
    date_col1, date_col2, date_col3 = st.columns(3)
    with date_col1:
        birth_year = st.selectbox("年", year_options, index=0)
    with date_col2:
        birth_month = st.selectbox("月", month_options, index=0)
    with date_col3:
        birth_day_candidate = st.selectbox("日", day_options, index=0)

    birth_date = None
    if (
        birth_year != "年を選択"
        and birth_month != "月を選択"
        and birth_day_candidate != "日を選択"
    ):
        try:
            birth_date = datetime.date(
                int(birth_year), int(birth_month), int(birth_day_candidate)
            )
        except ValueError:
            st.error("存在しない日付です。生年月日を確認してください。")
            birth_date = None

    render_form_gap(2)

    st.markdown('<div class="label-sm">出生時刻</div>', unsafe_allow_html=True)
    st.caption("出生時刻が不明でも鑑定できます。分かる範囲に応じてお選びください。")
    birth_time_accuracy = st.radio(
        "出生時刻の分かり具合",
        TIME_ACCURACY_OPTIONS,
        horizontal=True,
        index=0,
    )
    st.markdown(
        f'<div class="input-help">選択中：{html.escape(birth_time_accuracy)}</div>',
        unsafe_allow_html=True,
    )

    birth_hour = None
    birth_minute = None
    if birth_time_accuracy != "不明":
        time_col1, time_col2 = st.columns(2)
        with time_col1:
            birth_hour = st.selectbox("時", HOUR_OPTIONS, index=12)
        with time_col2:
            birth_minute = st.selectbox("分", MINUTE_OPTIONS, index=0)

    render_form_gap(2)

    st.markdown('<div class="label-sm">出生地</div>', unsafe_allow_html=True)
    birth_place = st.text_input("出生地", placeholder="東京都")

    render_form_gap(2)

    st.markdown('<div class="label-sm">相談カテゴリ</div>', unsafe_allow_html=True)
    st.caption("今いちばん知りたいことを中心に、1〜3個お選びください。")
    category_options_with_blank = ["（未選択）"] + CATEGORY_OPTIONS

    cat_col1, cat_col2, cat_col3 = st.columns(3)
    with cat_col1:
        category_1 = st.selectbox("相談カテゴリ1", category_options_with_blank, index=0)
    with cat_col2:
        category_2 = st.selectbox("相談カテゴリ2", category_options_with_blank, index=0)
    with cat_col3:
        category_3 = st.selectbox("相談カテゴリ3", category_options_with_blank, index=0)

    raw_categories = [category_1, category_2, category_3]
    categories = []
    for cat in raw_categories:
        if cat != "（未選択）" and cat not in categories:
            categories.append(cat)

    render_form_gap(1)

    st.markdown('<div class="label-sm">特に重視したいことの補足</div>', unsafe_allow_html=True)
    concern_detail = st.text_area(
        "特に重視したいことの補足",
        placeholder="例: 個人事業主として今後どう進めるべきか、今後1年の流れを重視して見てほしい、など",
        height=110,
    )

    render_form_gap(2)

    st.markdown('<div class="label-sm">手相の写真</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="input-help">手のひら全体が見える、明るくぶれの少ない写真をお選びください。画像は最大{MAX_IMAGE_FILES}枚までです。</div>',
        unsafe_allow_html=True,
    )

    uploaded_files = st.file_uploader(
        f"手相の写真（最大 {MAX_IMAGE_FILES} 枚 / 1枚 {MAX_IMAGE_SIZE_MB}MBまで）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    hand_sides = []
    if uploaded_files:
        st.markdown('<div class="input-help">各画像の左右を選んでください。</div>', unsafe_allow_html=True)
        hand_sides = build_selected_hand_sides(uploaded_files)

    render_form_gap(2)

    regular_pdf_generated = (
        bool(st.session_state.get("fortune_pdf_bytes"))
        and st.session_state.get("fortune_pdf_purchase_id") == purchase_id
    )
    regular_fortune_generated = (
        bool(st.session_state.get("fortune_json"))
        and st.session_state.get("fortune_pdf_purchase_id") == purchase_id
    )
    regular_generation_completed = regular_fortune_generated or regular_pdf_generated
    regular_submit_placeholder = st.empty()
    regular_submit_clicked = False
    if not regular_generation_completed:
        with regular_submit_placeholder:
            regular_submit_clicked = st.button("🐉 龍神さまのお告げを聞く")

    if regular_submit_clicked:
        st.session_state.fortune_json = None
        st.session_state.fortune_pdf_bytes = None
        st.session_state.fortune_pdf_purchase_id = None
        record = get_purchase_record(active_purchase.get("purchase_id"))
        if not is_purchase_ready(record):
            st.error("決済済みかつ未使用の購入情報が確認できませんでした。ページを再読み込みして状態をご確認ください。")
            st.stop()

        errors = validate_inputs(
            user_name=user_name,
            birth_place=birth_place,
            categories=categories,
            concern_detail=concern_detail,
            birth_time_accuracy=birth_time_accuracy,
            birth_hour=birth_hour,
            birth_minute=birth_minute,
            uploaded_files=uploaded_files or [],
            hand_sides=hand_sides,
        )

        if birth_date is None:
            errors.append("生年月日を選択してください。")

        if errors:
            st.error("入力内容に確認事項があります。")
            for err in list(dict.fromkeys(errors)):
                st.error(err)
        else:
            try:
                image_parts = build_image_parts(uploaded_files or [])
                image_meta = [
                    PalmImageMeta(filename=file.name, hand_side=hand_sides[idx])
                    for idx, file in enumerate(uploaded_files or [])
                ]

                payload = FortuneInput(
                    user_name=normalize_text(user_name),
                    birth_date=birth_date,
                    birth_place=normalize_text(birth_place),
                    categories=categories,
                    concern_detail=normalize_text(concern_detail),
                    birth_time_accuracy=birth_time_accuracy,
                    birth_time_text=format_birth_time_text(
                        birth_time_accuracy, birth_hour, birth_minute
                    ),
                    image_parts=image_parts,
                    image_meta=image_meta,
                    image_count=len(image_parts),
                )

                with st.spinner("龍神さまが降臨されています..."):
                    purchase_id = str(active_purchase.get("purchase_id") or "")
                    track_purchase_ga4_event_once(
                        "reading_started",
                        purchase_id,
                        product_type,
                        logger,
                    )
                    completed = generate_regular_fortune_pdf_and_consume(
                        payload,
                        purchase_id,
                        logger,
                    )

                if completed is None:
                    if st.session_state.get("generation_claim_status") == GENERATION_CLAIM_PROCESSING:
                        st.info("現在処理中です。完了までお待ちください。")
                    else:
                        st.error("購入権の確認に失敗しました。ページを更新せず、時間をおいて再度お試しください。")
                        st.error("解消しない場合は、お問い合わせください。")
                    return

                result, pdf_data = completed
                st.session_state.fortune_json = result
                st.session_state.fortune_pdf_bytes = pdf_data
                st.session_state.fortune_pdf_purchase_id = purchase_id
                st.session_state.user_name = payload.user_name
                regular_submit_placeholder.empty()

                st.success("お告げを授かりました。今回の購入分は使用済みになりました。")
                logger.info(
                    "fortune_completed",
                    extra={
                        "env": APP_ENV,
                        "purchase_id": active_purchase["purchase_id"],
                        "category_count": len(categories),
                        "image_count": len(image_parts),
                    },
                )

            except Exception as exc:
                logger.exception("fortune_failed")
                st.error(f"鑑定中に支障が生じました: {exc}")

    data = st.session_state.fortune_json
    if data:
        render_form_gap(2)
        render_html_box("龍神さまよりの挨拶", data.get("miko_intro", ""))
        render_html_box("今回の鑑定のまとめ", data.get("method_summary", ""))

        st.markdown('<div class="heading-lg">各占術から見た流れ</div>', unsafe_allow_html=True)
        render_html_box("手相術", data.get("palm_details", ""))
        render_html_box("姓名判断", data.get("name_reading", ""))
        render_html_box("四柱推命", data.get("shichusuimei", ""))
        render_html_box("西洋占星術", data.get("western_astrology", ""))

        st.markdown('<div class="heading-lg">時の波</div>', unsafe_allow_html=True)
        render_html_box("直近：これから3カ月以内の運勢", data.get("fortune_3months", ""))
        render_html_box("展望：これから1年先の運勢", data.get("fortune_1year", ""))
        render_html_box("未来：2〜3年後の運勢", data.get("fortune_3years", ""))

        advice = data.get("advice", {}) or {}
        render_html_box(
            "巫女の助言",
            "\n\n".join(
                [
                    f'開運アイテム: {advice.get("item", "")}',
                    f'開運スポット: {advice.get("spot", "")}',
                    f'開運カラー: {advice.get("color", "")}',
                    f'運気を上げる行動: {advice.get("luck_action", "")}',
                ]
            ),
        )

        cautions = data.get("cautions", []) or []
        if cautions:
            render_html_box("心に留めること", "\n".join([f"・{x}" for x in cautions]))

        render_html_box("結び", data.get("miko_closing", ""))

        pdf_data = st.session_state.get("fortune_pdf_bytes")
        purchase_id = active_purchase.get("purchase_id")
        if pdf_data and st.session_state.get("fortune_pdf_purchase_id") == purchase_id:
            tracked_purchase_ids = st.session_state.ga4_pdf_generated_purchase_ids
            if purchase_id and purchase_id not in tracked_purchase_ids:
                if track_purchase_ga4_event_once("pdf_generated", purchase_id, product_type, logger):
                    tracked_purchase_ids.add(purchase_id)
            safe_name = st.session_state.user_name.replace(" ", "_")
            st.download_button(
                label="📜 巫女からの手紙を保存する（PDF）",
                data=pdf_data,
                file_name=f"miko_letter_{safe_name}.pdf",
                mime="application/pdf",
            )

        if SHOW_DEBUG:
            with st.expander("確認メモ"):
                st.markdown(
                    f'- 使用モデル: `{GEMINI_MODEL}`\n'
                    f'- 手相画像枚数: {len(uploaded_files or [])}\n'
                    f'- 相談カテゴリ: {", ".join(categories) if categories else "なし"}\n'
                    f'- 出生時刻の精度: {birth_time_accuracy}\n'
                    f'- 購入ID: {active_purchase.get("purchase_id")}\n'
                    f'- 決済確認: {active_purchase.get("payment_status")}\n'
                    '- 入力内容は鑑定結果の生成とPDF作成のために使用します。'
                )


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)

    st.set_page_config(page_title=f"🐉 {APP_TITLE}", layout="centered")
    render_app_css()
    init_session_state()
    update_ga4_identifiers_from_query()
    update_tracking_session_state_from_query()

    purchase_return_requested = has_purchase_return_query_params()
    direct_checkout_requested = is_direct_checkout_request()
    active_purchase = get_current_purchase_record()
    requested_product_type = get_requested_product_type()
    display_product_type = (
        get_purchase_product_type(active_purchase)
        if active_purchase
        else requested_product_type
    )
    track_streamlit_page_view(logger, display_product_type)

    if direct_checkout_requested:
        render_direct_checkout(requested_product_type, logger)
        return

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen(get_purchase_product_type(active_purchase))
        st.stop()

    if active_purchase:
        if is_purchase_ready(active_purchase):
            render_header(title_top_gap_rem=0.6, header_top_gap_rem=1.1)
            if get_purchase_product_type(active_purchase) == PRODUCT_TYPE_REVIEW:
                render_review_fortune_form(active_purchase, logger)
            else:
                render_fortune_form(active_purchase, logger)
            st.divider()
            return

        if active_purchase.get("payment_status") != "paid":
            st.info("決済結果を確認中です。数秒後に再読み込みしてください。")
            return

        st.warning("この購入情報は現在ご利用いただけません。再度ご購入の際は、新しくお手続きください。")
        return

    render_header()

    render_payment_section(
        display_product_type,
        logger,
        allow_checkout_creation=False,
    )
    render_notice_box()
    render_form_gap(2)

    st.info("決済が完了すると、こちらのページに戻り、鑑定フォームが表示されます。")
    st.divider()
    return


if __name__ == "__main__":
    main()
