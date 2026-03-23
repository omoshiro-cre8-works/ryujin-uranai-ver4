
import datetime
import html
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any

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
from services.fortune_service import build_image_parts, call_gemini_fortune
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
PURCHASE_STORE_PATH = Path(os.getenv("PURCHASE_STORE_PATH", "/tmp/stripe_purchases.json"))
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_ENABLED = bool(stripe and STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


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


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def token_expires_at_iso(hours: int = 24) -> str:
    return (utc_now() + datetime.timedelta(hours=hours)).isoformat()


def ensure_purchase_store() -> None:
    PURCHASE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PURCHASE_STORE_PATH.exists():
        PURCHASE_STORE_PATH.write_text("{}", encoding="utf-8")


def load_purchase_store() -> dict[str, Any]:
    ensure_purchase_store()
    try:
        return json.loads(PURCHASE_STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_purchase_store(data: dict[str, Any]) -> None:
    ensure_purchase_store()
    PURCHASE_STORE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_purchase_record() -> dict[str, Any]:
    purchase_id = f"p_{utc_now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
    access_token = secrets.token_urlsafe(24)
    record = {
        "purchase_id": purchase_id,
        "stripe_checkout_session_id": None,
        "payment_status": "pending",
        "used_flag": False,
        "used_at": None,
        "access_token": access_token,
        "token_expires_at": token_expires_at_iso(),
        "stripe_event_id": None,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "amount_total": None,
        "currency": "jpy",
        "checkout_completed_at": None,
        "app_version": APP_ENV,
    }
    store = load_purchase_store()
    store[purchase_id] = record
    save_purchase_store(store)
    return record


def get_purchase_record(purchase_id: str | None) -> dict[str, Any] | None:
    if not purchase_id:
        return None
    store = load_purchase_store()
    return store.get(purchase_id)


def update_purchase_record(purchase_id: str, **updates: Any) -> dict[str, Any] | None:
    store = load_purchase_store()
    record = store.get(purchase_id)
    if not record:
        return None
    record.update(updates)
    record["updated_at"] = utc_now_iso()
    store[purchase_id] = record
    save_purchase_store(store)
    return record


def is_token_valid(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    token_expires_at = record.get("token_expires_at")
    if not token_expires_at:
        return False
    try:
        expires_at = datetime.datetime.fromisoformat(token_expires_at)
    except ValueError:
        return False
    return expires_at > utc_now()


def is_purchase_ready(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("payment_status") == "paid"
        and not record.get("used_flag")
        and is_token_valid(record)
    )


def stripe_client_ready() -> bool:
    if not STRIPE_ENABLED:
        return False
    assert stripe is not None
    stripe.api_key = STRIPE_SECRET_KEY
    return True


def create_checkout_session(logger: logging.Logger) -> tuple[str | None, str | None]:
    if not stripe_client_ready():
        return None, "Stripe の設定が不足しています。環境変数 STRIPE_SECRET_KEY / STRIPE_PRICE_ID を確認してください。"

    record = create_purchase_record()
    purchase_id = record["purchase_id"]

    try:
        assert stripe is not None
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
            success_url=f"{APP_BASE_URL}/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=WIX_CANCEL_URL,
            client_reference_id=purchase_id,
            metadata={"purchase_id": purchase_id},
        )
        update_purchase_record(
            purchase_id,
            stripe_checkout_session_id=session.id,
        )
        st.session_state.active_purchase_id = purchase_id
        st.session_state.checkout_url = session.url
        logger.info(
            "checkout_session_created",
            extra={
                "env": APP_ENV,
                "purchase_id": purchase_id,
                "stripe_checkout_session_id": session.id,
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

    record = update_purchase_record(
        purchase_id,
        payment_status="paid",
        stripe_checkout_session_id=getattr(session, "id", None),
        amount_total=amount_total,
        currency=currency,
        checkout_completed_at=utc_now_iso(),
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
        used_at=utc_now_iso(),
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


def render_checkout_link(checkout_url: str) -> None:
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
                Stripe の決済画面へ進む
            </div>
        </a>
        ''',
        unsafe_allow_html=True,
    )


def render_payment_section(logger: logging.Logger) -> dict[str, Any] | None:
    st.markdown('<div class="heading-lg">💳 ご利用手続き</div>', unsafe_allow_html=True)
    st.markdown(
        '''
        <div style="border:1px solid #e5d7d1; background:#fffdfa; border-radius:14px; padding:14px 16px; margin:0.3rem 0 1rem 0; color:#3b312d;">
            <div style="font-weight:700; margin-bottom:0.45rem;">有料版のご利用について</div>
            <div style="margin-bottom:0.25rem;">・本サービスは <strong>1回 300円</strong> の単発課金です。</div>
            <div style="margin-bottom:0.25rem;">・決済完了後、この画面に戻ると鑑定フォームが表示されます。</div>
            <div>・1回の購入につき、鑑定の実行は1回のみです。</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    if not STRIPE_ENABLED:
        st.error("Stripe の設定がまだ反映されていません。Cloud Run の環境変数 STRIPE_SECRET_KEY / STRIPE_PRICE_ID を設定してください。")
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

    if st.button("💳 300円でお告げを受ける"):
        checkout_url, error_message = create_checkout_session(logger)
        if error_message:
            st.error(error_message)
        elif checkout_url:
            st.success("決済ページの準備ができました。下のボタンから Stripe Checkout へ進んでください。")

    if st.session_state.get("checkout_url"):
        render_checkout_link(st.session_state["checkout_url"])

    return None


def render_header() -> None:
    header_left, header_right = st.columns([1, 4])
    with header_left:
        if os.path.exists(MIKO_IMAGE_PATH):
            try:
                with open(MIKO_IMAGE_PATH, "rb") as f:
                    st.image(f.read(), width=96)
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
    st.markdown(
        '''
        <div style="border:1px solid #d98b73; background:#fff7f4; border-radius:14px; padding:14px 16px; margin:0.4rem 0 1rem 0; color:#3b312d;">
            <div style="font-weight:700; color:#b14d2c; margin-bottom:0.45rem;">ご確認いただきたい大切なこと</div>
            <div style="margin-bottom:0.25rem; color:#3b312d;">・本鑑定は参考情報としてお楽しみいただくためのものです。</div>
            <div style="margin-bottom:0.25rem; color:#3b312d;">・医療・法律・投資などの重要な判断には利用せず、必要に応じて専門家へご相談ください。</div>
            <div style="color:#3b312d;">・ご入力内容は鑑定結果の生成とPDF作成のために一時的に使用し、この検証版では履歴保存を行いません。</div>
        </div>
        ''',
        unsafe_allow_html=True,
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
            with st.expander("開発メモ"):
                st.markdown(
                    f'- 使用モデル: `{GEMINI_MODEL}`\n'
                    f'- 手相画像枚数: {len(uploaded_files or [])}\n'
                    f'- 相談カテゴリ: {", ".join(categories) if categories else "なし"}\n'
                    f'- 出生時刻の精度: {birth_time_accuracy}\n'
                    f'- 購入ID: {active_purchase.get("purchase_id")}\n'
                    f'- 決済状態: {active_purchase.get("payment_status")}\n'
                    '- 入力データはセッション内のみで扱い、決済制御用の最小情報のみ /tmp に保存する設計です。'
                )


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)

    st.set_page_config(page_title=f"🐉 {APP_TITLE}", layout="centered")
    render_app_css()
    init_session_state()

    active_purchase = get_current_purchase_record()
    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()

    render_header()
    render_notice_box()
    render_pre_info()

    active_purchase = render_payment_section(logger)
    render_form_gap(2)

    if active_purchase and active_purchase.get("used_flag"):
        render_completion_screen()
        st.stop()
    elif active_purchase:
        render_fortune_form(active_purchase, logger)
    else:
        st.info("まずは上のボタンから決済を完了すると、鑑定フォームが表示されます。")
        st.divider()
        return

    st.divider()


if __name__ == "__main__":
    main()
