
import datetime
import html
import logging
import os
import secrets
import sys
import urllib.parse
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

try:
    import stripe
except ImportError:  # pragma: no cover - デプロイ環境で stripe 未導入時の保険
    stripe = None

from config import (
    APP_ENV,
    APP_SUBTITLE,
    APP_TITLE,
    CATEGORY_OPTIONS,
    GEMINI_MODEL,
    GA4_API_SECRET,
    GA4_ENABLED,
    GA4_MEASUREMENT_ID,
    HOUR_OPTIONS,
    LOG_LEVEL,
    MAX_IMAGE_FILES,
    MAX_IMAGE_SIZE_MB,
    MIKO_IMAGE_PATH,
    MINUTE_OPTIONS,
    SHOW_DEBUG,
    TIME_ACCURACY_OPTIONS,
)
from models.schemas import FortuneInput, PalmImageMeta
from services.firestore_service import (
    create_purchase_record as firestore_create_purchase_record,
    get_firestore_client,
)
from services.fortune_service import build_image_parts, call_gemini_fortune
from services.ga4_service import send_ga4_event
from services.pdf_service import generate_miko_letter_pdf
from services.validation_service import (
    format_birth_time_text,
    normalize_text,
    validate_inputs,
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
STRIPE_PRICE_ID_REVIEW = os.getenv("STRIPE_PRICE_ID_REVIEW", "")
STRIPE_PRICE_ID_REVIEW_CAMPAIGN = os.getenv("STRIPE_PRICE_ID_REVIEW_CAMPAIGN", "")
CAMPAIGN_END_AT = os.getenv("CAMPAIGN_END_AT", "").strip()
CAMPAIGN_TIMEZONE = os.getenv("CAMPAIGN_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
REGULAR_AMOUNT_JPY = 300
CAMPAIGN_AMOUNT_JPY = 100
REVIEW_AMOUNT_JPY = get_int_env("REVIEW_AMOUNT_JPY", 980)
REVIEW_CAMPAIGN_AMOUNT_JPY = get_int_env("REVIEW_CAMPAIGN_AMOUNT_JPY", REVIEW_AMOUNT_JPY)
STRIPE_ENABLED = bool(stripe and STRIPE_SECRET_KEY and STRIPE_PRICE_ID_REGULAR)
PRODUCT_TYPE_REGULAR = "regular"
PRODUCT_TYPE_REVIEW = "review"
VALID_PRODUCT_TYPES = {PRODUCT_TYPE_REGULAR, PRODUCT_TYPE_REVIEW}
SAMPLE_PDF_IMAGE_PATHS = [
    os.path.join("assets", "sample_pdf_1.png"),
    os.path.join("assets", "sample_pdf_2.png"),
    os.path.join("assets", "sample_pdf_3.png"),
]


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


def get_page_location() -> str:
    query_params = {}
    for key in st.query_params:
        value = get_query_param_value(key)
        if value is not None:
            query_params[key] = value
    query_string = urllib.parse.urlencode(query_params)
    return f"{APP_BASE_URL}/?{query_string}" if query_string else f"{APP_BASE_URL}/"


def get_checkout_price_type(product_type: str, price_id: str) -> str:
    if product_type == PRODUCT_TYPE_REVIEW:
        if STRIPE_PRICE_ID_REVIEW_CAMPAIGN and price_id == STRIPE_PRICE_ID_REVIEW_CAMPAIGN:
            return "review_campaign"
        return "review_regular"
    if STRIPE_PRICE_ID_CAMPAIGN and price_id == STRIPE_PRICE_ID_CAMPAIGN:
        return "regular_campaign"
    return "regular"


def build_checkout_success_url() -> str:
    query_parts = ["session_id={CHECKOUT_SESSION_ID}"]
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
    return record or {}


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
            return None, "Stripe の設定が不足しています。環境変数 STRIPE_PRICE_ID_REVIEW を確認してください。"
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
            success_url=build_checkout_success_url(),
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
    if not session_id or not stripe_client_ready():
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

    purchase_id = None
    metadata = getattr(session, "metadata", None) or {}
    if isinstance(metadata, dict):
        purchase_id = metadata.get("purchase_id")
    if not purchase_id:
        purchase_id = getattr(session, "client_reference_id", None)

    if not purchase_id:
        return None

    payment_status = getattr(session, "payment_status", None)
    status = getattr(session, "status", None)

    if payment_status != "paid" and status != "complete":
        return get_purchase_record(purchase_id)

    amount_total = getattr(session, "amount_total", None)
    currency = getattr(session, "currency", None)
    metadata = getattr(session, "metadata", None) or {}

    amount_jpy = amount_total if currency == "jpy" and isinstance(amount_total, int) else None
    price_id = metadata.get("price_id") if isinstance(metadata, dict) else None
    existing_record = get_purchase_record(purchase_id) or {}
    product_type = normalize_product_type(
        (metadata.get("product_type") if isinstance(metadata, dict) else None)
        or existing_record.get("product_type")
    )
    price_type = (
        (metadata.get("price_type") if isinstance(metadata, dict) else None)
        or existing_record.get("price_type")
    )

    record = update_purchase_record(
        purchase_id,
        payment_status="paid",
        stripe_checkout_session_id=getattr(session, "id", None),
        product_type=product_type,
        price_type=price_type or get_checkout_price_type(product_type, price_id or ""),
        price_id=price_id,
        amount_jpy=amount_jpy,
        amount_total=amount_total,
        currency=currency,
        checkout_completed_at=utc_now(),
    )
    if record:
        st.session_state.active_purchase_id = purchase_id
        logger.info(
            "checkout_session_paid_synced",
            extra={
                "env": APP_ENV,
                "purchase_id": purchase_id,
                "stripe_checkout_session_id": getattr(session, "id", None),
            },
        )
    return record


def consume_purchase(purchase_id: str, logger: logging.Logger) -> None:
    record = get_purchase_record(purchase_id)
    if not is_purchase_ready(record):
        return
    update_purchase_record(
        purchase_id,
        used_flag=True,
        used_at=utc_now(),
    )
    logger.info(
        "purchase_consumed",
        extra={
            "env": APP_ENV,
            "purchase_id": purchase_id,
        },
    )


def get_current_purchase_record() -> dict[str, Any] | None:
    session_id = st.query_params.get("session_id")
    if session_id:
        return sync_purchase_from_session(str(session_id), logging.getLogger(__name__))
    active_purchase_id = st.session_state.get("active_purchase_id")
    return get_purchase_record(active_purchase_id)


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


def render_pre_payment_intro(product_type: str, active_amount_jpy: int) -> None:
    product_name = html.escape(get_product_display_name(product_type))
    review_note = ""
    if product_type == PRODUCT_TYPE_REVIEW:
        review_note = '<div style="margin-top:0.55rem;">※見返し便フォームは次フェーズで実装予定です。</div>'
    st.markdown(
        f'''
        <div style="border:1px solid #eadfd8; background:#fffdf9; border-radius:14px; padding:16px 18px; margin:0.4rem 0 1rem 0; color:#3b312d; line-height:1.8;">
            <div>ここは、ケモノ町の龍神さまから、今のあなたへひとつ言葉を受け取るためのページです。</div>
            <div style="font-weight:700; margin-top:0.55rem;">商品種別：{product_name}</div>
            <div style="margin-top:0.55rem;">所要時間は3〜5分ほどです。</div>
            <div>1回{active_amount_jpy}円（税込）でご利用いただけます。</div>
            <div>決済完了後、この画面に戻ると入力フォームが表示されます。</div>
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
2. 決済完了後、このページに戻る
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
            if os.path.exists(image_path):
                st.image(
                    image_path,
                    caption=f"PDF見本 {index}ページ目",
                    use_container_width=True,
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


def render_checkout_reassurance(active_amount_jpy: int) -> None:
    st.markdown(
        f'''
        <div style="border:1px solid #eadfd8; background:#fffdf9; border-radius:14px; padding:14px 16px; margin:0.45rem 0 0.7rem 0; color:#3b312d; line-height:1.8;">
            <div>お支払いは1回{active_amount_jpy}円（税込）です。</div>
            <div>月額課金や継続課金ではありません。</div>
            <div style="margin-top:0.55rem;">決済はStripeの決済ページで行われます。</div>
            <div>このページでは、クレジットカード番号を保存しません。</div>
            <div style="margin-top:0.55rem;">決済完了後、このページに戻ると鑑定フォームが表示されます。</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_payment_section(product_type: str, logger: logging.Logger) -> dict[str, Any] | None:
    product_type = normalize_product_type(product_type)
    _, active_amount_jpy = get_active_checkout_price(product_type, logger)
    render_pre_payment_intro(product_type, active_amount_jpy)
    render_usage_flow(active_amount_jpy)
    render_pdf_sample_section()
    render_pdf_contents_summary()

    st.markdown('<div class="heading-lg">💳 ご利用手続き</div>', unsafe_allow_html=True)
    st.markdown(
        f'''
        <div style="border:1px solid #e5d7d1; background:#fffdfa; border-radius:14px; padding:14px 16px; margin:0.3rem 0 1rem 0; color:#3b312d;">
            <div style="font-weight:700; margin-bottom:0.45rem;">有料版のご利用について</div>
            <div style="margin-bottom:0.25rem;">・本サービスは <strong>1回 {active_amount_jpy}円</strong> の単発課金です。</div>
            <div style="margin-bottom:0.25rem;">・決済完了後、この画面に戻ると鑑定フォームが表示されます。</div>
            <div>・1回の購入につき、鑑定の実行は1回のみです。</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

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
        render_checkout_reassurance(active_amount_jpy)
        render_checkout_link(checkout_url, active_amount_jpy)

    return None




def render_completion_screen() -> None:
    top_url = WIX_CANCEL_URL or "https://www.omoshiro-cre8works.com/ai-uranai"
    render_form_gap(2)
    left, center, right = st.columns([1, 1.4, 1])
    with center:
        st.image(str(MIKO_IMAGE_PATH), use_container_width=True)

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
        if os.path.exists(MIKO_IMAGE_PATH):
            try:
                st.image(str(MIKO_IMAGE_PATH), width=96)
            except Exception:
                st.caption("miko画像なし")
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


def render_review_placeholder(active_purchase: dict[str, Any]) -> None:
    st.info("見返し便の入力フォームは次フェーズで実装予定です。今回の更新では、商品種別の決済・計測土台のみを追加しています。")
    if SHOW_DEBUG:
        with st.expander("確認メモ"):
            st.markdown(
                f'- 商品種別: `{get_purchase_product_type(active_purchase)}`\n'
                f'- 購入ID: `{active_purchase.get("purchase_id")}`\n'
                f'- 決済確認: `{active_purchase.get("payment_status")}`'
            )


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

                with st.spinner("龍神さまが降臨されています..."):
                    result = call_gemini_fortune(payload)

                consume_purchase(active_purchase["purchase_id"], logger)

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

    active_purchase = get_current_purchase_record()
    requested_product_type = get_requested_product_type()
    tracking_product_type = (
        get_purchase_product_type(active_purchase)
        if active_purchase and active_purchase.get("payment_status") == "paid"
        else requested_product_type
    )
    track_streamlit_page_view(logger, tracking_product_type)

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()

    render_header()

    active_purchase = render_payment_section(requested_product_type, logger)
    render_notice_box()
    render_form_gap(2)

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()
    elif active_purchase:
        if get_purchase_product_type(active_purchase) == PRODUCT_TYPE_REVIEW:
            render_review_placeholder(active_purchase)
        else:
            render_fortune_form(active_purchase, logger)
    else:
        st.info("決済が完了すると、このページに戻り、鑑定フォームが表示されます。")
        st.divider()
        return

    st.divider()


if __name__ == "__main__":
    main()
