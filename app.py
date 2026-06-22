
import base64
import datetime
import html
import json
import logging
import os
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
    consume_purchase_transaction,
    create_purchase_record as firestore_create_purchase_record,
    get_firestore_client,
    get_purchase_by_access_token,
)
from services.fortune_service import (
    build_image_parts,
    build_review_context,
    call_gemini_fortune,
    call_gemini_review_fortune,
    call_gemini_review_pdf_summary,
)
from services.ga4_service import send_ga4_event
from services.pdf_service import generate_miko_letter_pdf, generate_review_fortune_pdf
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
WIX_CANCEL_URL = os.getenv(
    "WIX_CANCEL_URL",
    "https://www.omoshiro-cre8works.com/ai-uranai",
)


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
GA4_SENSITIVE_QUERY_PARAMS = {"session_id", "purchase_id", "access_token"}
ASSETS_DIR = BASE_DIR / "assets"
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
    if "ga4_client_id" not in st.session_state:
        st.session_state.ga4_client_id = secrets.token_urlsafe(16)
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


def get_query_param_value(key: str) -> str | None:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def get_utm_params() -> dict[str, str]:
    utm_params = {}
    for key in ["utm_source", "utm_medium", "utm_campaign", "utm_content"]:
        value = get_query_param_value(key)
        if value:
            utm_params[key] = value
    return utm_params


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
        and (product_type or "").strip().lower() == PRODUCT_TYPE_REGULAR
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
    query_parts = [
        "session_id={CHECKOUT_SESSION_ID}",
        urllib.parse.urlencode(
            {
                "purchase_id": purchase_id,
                "access_token": access_token,
                "product_type": normalize_product_type(product_type),
            }
        ),
    ]
    utm_params = get_utm_params()
    if utm_params:
        query_parts.append(urllib.parse.urlencode(utm_params))
    return f"{APP_BASE_URL}/?{'&'.join(query_parts)}"


def track_ga4_event(
    event_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
) -> bool:
    event_params = {
        "page_location": get_page_location(),
        **get_utm_params(),
    }
    if params:
        event_params.update(params)

    return send_ga4_event(
        event_name=event_name,
        client_id=st.session_state.ga4_client_id,
        measurement_id=GA4_MEASUREMENT_ID,
        api_secret=GA4_API_SECRET,
        enabled=GA4_ENABLED,
        params=event_params,
        logger=logger,
    )


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
    return db.collection("purchases").document(purchase_id)


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
    if not STRIPE_ENABLED:
        return False
    if normalize_product_type(product_type) == PRODUCT_TYPE_REVIEW and not STRIPE_PRICE_ID_REVIEW:
        return False
    assert stripe is not None
    stripe.api_key = STRIPE_SECRET_KEY
    return True


def create_checkout_session(product_type: str, logger: logging.Logger) -> tuple[str | None, str | None]:
    product_type = normalize_product_type(product_type)
    if not stripe_client_ready(product_type):
        if product_type == PRODUCT_TYPE_REVIEW:
            return None, "見返し便の決済設定がまだ完了していません。環境変数 STRIPE_REVIEW_PRICE_ID を確認してください。"
        return None, "Stripe の設定が不足しています。環境変数 STRIPE_SECRET_KEY / STRIPE_PRICE_ID_REGULAR を確認してください。"

    active_price_id, active_amount_jpy = get_active_checkout_price(product_type, logger)
    price_type = get_checkout_price_type(product_type, active_price_id)
    record = create_purchase_record(active_price_id, active_amount_jpy, product_type, price_type)
    purchase_id = record["purchase_id"]

    try:
        assert stripe is not None
        session = stripe.checkout.Session.create(
            mode="payment",
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
        track_ga4_event(
            "checkout_session_created",
            logger,
            {
                "product_type": product_type,
                "amount_jpy": active_amount_jpy,
                "price_type": price_type,
            },
        )
        return session.url, None
    except Exception as exc:  # pragma: no cover - 外部API例外
        logger.exception("checkout_session_create_failed")
        return None, f"Stripe Checkout の準備に失敗しました: {exc}"


def retrieve_checkout_session(session_id: str) -> Any | None:
    if not session_id:
        return None
    if not stripe_client_ready(PRODUCT_TYPE_REGULAR) and not stripe_client_ready(PRODUCT_TYPE_REVIEW):
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
    return record


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
    removable_keys = {"session_id", "purchase_id", "access_token", "product_type"}
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


def render_checkout_auto_redirect(checkout_url: str) -> None:
    checkout_url_json = json.dumps(checkout_url)
    components.html(
        f"""
        <script>
            window.setTimeout(function() {{
                try {{
                    window.top.location.href = {checkout_url_json};
                }} catch (error) {{
                    window.location.href = {checkout_url_json};
                }}
            }}, 250);
        </script>
        """,
        height=0,
    )


def render_direct_checkout(logger: logging.Logger) -> None:
    _, active_amount_jpy = get_active_checkout_price(PRODUCT_TYPE_REGULAR, logger)

    if not STRIPE_ENABLED:
        st.error("ただいま決済ページを準備できません。時間をおいてもう一度お試しください。")
        return

    checkout_url = st.session_state.get("checkout_url")
    if checkout_url and st.session_state.get("checkout_product_type") != PRODUCT_TYPE_REGULAR:
        clear_checkout_session_state()
        checkout_url = None

    if not checkout_url:
        checkout_url, error_message = create_checkout_session(PRODUCT_TYPE_REGULAR, logger)
        if error_message:
            st.error("決済ページを準備できませんでした。時間をおいてもう一度お試しください。")
            if SHOW_DEBUG:
                st.caption(error_message)
            return

    st.info("決済ページへ移動しています。自動で移動しない場合は、下のボタンを押してください。")
    render_checkout_link(checkout_url, active_amount_jpy)
    render_checkout_auto_redirect(checkout_url)


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




def render_completion_screen() -> None:
    top_url = WIX_CANCEL_URL or "https://www.omoshiro-cre8works.com/ai-uranai"
    render_form_gap(2)
    left, center, right = st.columns([1, 1.4, 1])
    with center:
        miko_image_bytes = read_image_bytes(MIKO_IMAGE_PATH)
        if miko_image_bytes:
            render_inline_png(miko_image_bytes, alt="巫女画像")

    st.markdown(
        """
        <h2 style="text-align:center; color:#8B4513; margin-top:0.8rem;">
            龍神さまのお告げは完了しました
        </h2>
        <p style="text-align:center; line-height:1.9; margin-top:0.6rem;">
            ご利用ありがとうございました。<br>
            また鑑定をご希望の場合は、あらためて決済のうえ、ご利用をお願いします。
        </p>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="text-align:center; margin-top:1.5rem;">
            <a href="{html.escape(top_url, quote=True)}" target="_self"
               style="display:inline-block; background:#b6552d; color:white; padding:0.8rem 1.4rem;
                      border-radius:999px; text-decoration:none; font-weight:600;">
                『龍神さまのお告げ』トップに戻る
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_header() -> None:
    header_left, header_right = st.columns([1, 4])
    with header_left:
        miko_image_bytes = read_image_bytes(MIKO_IMAGE_PATH)
        if miko_image_bytes:
            render_inline_png(miko_image_bytes, alt="巫女画像", width=96)
        else:
            st.caption("miko画像なし")

    with header_right:
        st.markdown(
            f'<div class="title-main">{html.escape(APP_TITLE)}</div>',
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

    if st.button("🐉 見返し便の鑑定本文を生成する", key="review_submit"):
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

            purchase_id = str(active_purchase.get("purchase_id") or "")
            if not consume_purchase(purchase_id, logger):
                st.error("決済済みかつ未使用の購入情報が確認できませんでした。ページを再読み込みして状態をご確認ください。")
                return
            st.session_state.review_purchase_consumed.add(purchase_id)

            with st.spinner("前回のお告げを要約し、時間の流れを整理しています..."):
                pdf_summary = call_gemini_review_pdf_summary(uploaded_pdf_bytes, pdf_analysis)

            if not pdf_summary.get("summary_success"):
                st.error("前回PDFの要約中にエラーが発生しました。")
                st.error("時間をおいてもう一度お試しください。")
                if SHOW_DEBUG:
                    diagnostics = pdf_summary.get("diagnostics") or {}
                    st.caption(
                        f"failed_step={diagnostics.get('failed_step', '')} / "
                        f"error_type={diagnostics.get('error_type', '')} / "
                        f"model_name={diagnostics.get('model_name', GEMINI_MODEL)} / "
                        f"pdf_size_bytes={diagnostics.get('pdf_size_bytes', len(uploaded_pdf_bytes))} / "
                        f"mime_type={diagnostics.get('mime_type', 'application/pdf')}"
                    )
                return

            review_context = build_review_context(
                pdf_analysis=pdf_analysis,
                previous_summary=pdf_summary.get("previous_summary") or {},
                current_inputs={
                    "birth_time_text": review_birth_time_text,
                    "selected_theme": review_theme,
                    "review_memo_present": bool(normalize_text(review_memo)),
                    "palm_image_count": len(uploaded_files or []),
                },
            )
            st.session_state.review_context = review_context

            with st.spinner("見返し便の鑑定本文を生成しています..."):
                palm_image_count = len(uploaded_files or [])
                review_fortune_result = call_gemini_review_fortune(
                    review_context=review_context,
                    current_private_inputs={
                        "user_name": normalize_text(user_name),
                        "birth_date": birth_date.isoformat() if birth_date else "",
                        "birth_time_text": review_birth_time_text,
                        "selected_theme": review_theme,
                        "review_memo": normalize_text(review_memo),
                        "palm_image_count": palm_image_count,
                        "current_palm_image_status": "attached" if palm_image_count > 0 else "not_attached",
                    },
                    image_parts=image_parts,
                )

            if not review_fortune_result.get("fortune_success"):
                st.error("見返し便の鑑定本文生成中にエラーが発生しました。")
                st.error("時間をおいてもう一度お試しください。")
                if SHOW_DEBUG:
                    diagnostics = review_fortune_result.get("diagnostics") or {}
                    st.caption(
                        f"failed_step={diagnostics.get('failed_step', '')} / "
                        f"error_type={diagnostics.get('error_type', '')} / "
                        f"model_name={diagnostics.get('model_name', GEMINI_MODEL)}"
                    )
                return

            st.session_state.review_fortune = review_fortune_result.get("review_fortune") or {}
            st.session_state.review_fortune_purchase_id = active_purchase.get("purchase_id")

            try:
                st.session_state.review_pdf_bytes = generate_review_fortune_pdf(
                    review_fortune=st.session_state.review_fortune,
                    review_context=review_context,
                )
                st.session_state.review_pdf_generated_purchase_id = active_purchase.get("purchase_id")
            except Exception as exc:
                st.session_state.review_pdf_bytes = None
                st.session_state.review_pdf_generated_purchase_id = None
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
        stored_review_context = st.session_state.get("review_context") or {}
        stored_current_inputs = (
            (stored_review_context.get("review_context") or {}).get("current_inputs") or {}
        )
        try:
            has_current_palm_images = int(stored_current_inputs.get("palm_image_count") or 0) > 0
        except (TypeError, ValueError):
            has_current_palm_images = False
        current_changes_title = (
            "現在の手相と近況から見える変化"
            if has_current_palm_images
            else "現在の近況から見える変化"
        )
        render_form_gap(2)
        st.markdown('<div class="heading-lg">📜 見返し便の鑑定本文</div>', unsafe_allow_html=True)
        raw_review_summary_points = review_fortune.get("review_summary_points")
        review_summary_points = [
            str(point).strip()
            for point in (raw_review_summary_points if isinstance(raw_review_summary_points, list) else [])
            if str(point).strip()
        ]
        if review_summary_points:
            render_html_box("今回の見返しポイント", "\n".join(f"・{point}" for point in review_summary_points))

        review_fortune_sections = [
            ("はじめに", "intro"),
            ("前回のお告げから続いている流れ", "continuing_flow"),
            (current_changes_title, "current_changes"),
            ("今回のテーマについての見返し", "theme_review"),
            ("これから3カ月ほど意識したいこと", "next_3_months"),
            ("1年先に向けて整えていくこと", "one_year_guidance"),
            ("龍神さまからの見返しの言葉", "ryujin_message"),
            ("巫女の助言", "miko_advice"),
            ("心に留めること", "things_to_remember"),
        ]
        for index, (title, key) in enumerate(review_fortune_sections):
            render_html_box(title, str(review_fortune.get(key) or ""))
            if index == 0:
                comparison_blocks = review_fortune.get("comparison_blocks") or []
                comparison_text_blocks = []
                if isinstance(comparison_blocks, list):
                    for block in comparison_blocks:
                        if not isinstance(block, dict):
                            continue
                        theme = str(block.get("theme") or "見返しテーマ").strip()
                        previous_message = str(block.get("previous_message") or "").strip()
                        current_status = str(block.get("current_status") or "").strip()
                        reinterpretation = str(block.get("reinterpretation") or "").strip()
                        if not any([theme, previous_message, current_status, reinterpretation]):
                            continue
                        comparison_text_blocks.append(
                            "\n".join(
                                [
                                    f"■ {theme}",
                                    "前回のお告げ：",
                                    previous_message,
                                    "現在の状況：",
                                    current_status,
                                    "今回の読み直し：",
                                    reinterpretation,
                                ]
                            )
                        )
                if comparison_text_blocks:
                    render_html_box("前回のお告げと現在の照らし合わせ", "\n\n".join(comparison_text_blocks))
            if key == "theme_review":
                raw_action_items = review_fortune.get("next_3_month_action_items")
                action_items = [
                    str(item).strip()
                    for item in (raw_action_items if isinstance(raw_action_items, list) else [])
                    if str(item).strip()
                ]
                if action_items:
                    action_text = "\n".join(
                        [
                            "これから3カ月は、以下のような小さな行動を意識するとよさそうです。",
                            "",
                            *[f"・{item}" for item in action_items],
                        ]
                    )
                    render_html_box("これから3カ月の小さな行動", action_text)

        review_pdf_bytes = st.session_state.get("review_pdf_bytes")
        review_pdf_purchase_id = st.session_state.get("review_pdf_generated_purchase_id")
        if review_pdf_bytes and review_pdf_purchase_id == purchase_id:
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

    if st.button("🐉 龍神さまのお告げを聞く"):
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

                if not consume_purchase(str(active_purchase.get("purchase_id") or ""), logger):
                    st.error("決済済みかつ未使用の購入情報が確認できませんでした。ページを再読み込みして状態をご確認ください。")
                    return

                with st.spinner("龍神さまが降臨されています..."):
                    result = call_gemini_fortune(payload)

                st.session_state.fortune_json = result
                st.session_state.user_name = payload.user_name

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

        try:
            pdf_data = generate_miko_letter_pdf(st.session_state.user_name, data)
            purchase_id = active_purchase.get("purchase_id")
            tracked_purchase_ids = st.session_state.ga4_pdf_generated_purchase_ids
            if purchase_id and purchase_id not in tracked_purchase_ids:
                track_ga4_event("pdf_generated", logger, {"product_type": product_type})
                tracked_purchase_ids.add(purchase_id)
            safe_name = st.session_state.user_name.replace(" ", "_")
            st.download_button(
                label="📜 巫女からの手紙を保存する（PDF）",
                data=pdf_data,
                file_name=f"miko_letter_{safe_name}.pdf",
                mime="application/pdf",
            )
        except Exception as exc:
            st.error("PDF鑑定書の作成に失敗しました。フォントファイル、巫女画像、設定内容を確認してください。")
            if SHOW_DEBUG:
                st.caption(str(exc))

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
        render_direct_checkout(logger)
        return

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()

    render_header()

    active_purchase = render_payment_section(
        display_product_type,
        logger,
        allow_checkout_creation=not purchase_return_requested,
    )
    render_notice_box()
    render_form_gap(2)

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()
    elif active_purchase:
        if get_purchase_product_type(active_purchase) == PRODUCT_TYPE_REVIEW:
            render_review_fortune_form(active_purchase, logger)
        else:
            render_fortune_form(active_purchase, logger)
    else:
        st.info("決済が完了すると、こちらのページに戻り、鑑定フォームが表示されます。")
        st.divider()
        return

    st.divider()


if __name__ == "__main__":
    main()
