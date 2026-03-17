import datetime
import html
import os
from typing import Any

import streamlit as st

from config import (
    APP_PASSPHRASE,
    APP_SUBTITLE,
    APP_TITLE,
    CATEGORY_OPTIONS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    HOUR_OPTIONS,
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
    is_passphrase_ok,
    render_form_gap,
    render_html_box,
)
from ui.styles import render_app_css


def main() -> None:
    st.set_page_config(page_title=f"🐉 {APP_TITLE}", layout="centered")
    render_app_css()

    if "fortune_json" not in st.session_state:
        st.session_state.fortune_json = None
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""

    header_left, header_right = st.columns([1, 4])
    with header_left:
        if os.path.exists(MIKO_IMAGE_PATH):
            st.image(MIKO_IMAGE_PATH, width=96)
    with header_right:
        st.markdown(f'<div class="title-main">{html.escape(APP_TITLE)}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-body" style="margin-bottom:1.2rem;">{html.escape(APP_SUBTITLE)}</div>',
            unsafe_allow_html=True,
        )

    # 一時的なデバッグ表示
    st.write("DEBUG")
    st.write("APP_PASSPHRASE loaded:", bool(APP_PASSPHRASE))
    st.write("GEMINI_API_KEY loaded:", bool(GEMINI_API_KEY))

    if not APP_PASSPHRASE:
        st.error("合言葉が設定されていません。.env または Streamlit Secrets の APP_PASSPHRASE を確認してください。")
        st.stop()

    st.markdown('<div class="label-sm">合言葉を仰ってください</div>', unsafe_allow_html=True)
    passphrase = st.text_input("", type="password", placeholder="合言葉を仰ってください", label_visibility="collapsed")
    if not is_passphrase_ok(passphrase):
        st.stop()

    render_form_gap(1)
    st.markdown(
        """
        <div style="
            border:1px solid #d98b73;
            background:#fff7f4;
            border-radius:14px;
            padding:14px 16px;
            margin:0.4rem 0 1rem 0;
        ">
            <div style="font-weight:700; color:#b14d2c; margin-bottom:0.45rem;">ご確認いただきたい大切なこと</div>
            <div style="margin-bottom:0.25rem;">・本鑑定は参考情報としてお楽しみいただくためのものです。</div>
            <div style="margin-bottom:0.25rem;">・医療・法律・投資などの重要な判断には利用せず、必要に応じて専門家へご相談ください。</div>
            <div>・ご入力内容は鑑定結果の生成とPDF作成のために一時的に使用し、このアプリでは履歴保存を行いません。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("ご利用前のご案内", expanded=False):
        st.markdown(
            """**この鑑定について**  
本アプリの鑑定結果は、参考情報としてお楽しみいただくためのものです。結果の正確性や、未来の出来事の実現を保証するものではありません。

**免責事項**  
本アプリの鑑定結果は、医療・法律・税務・投資その他の専門的助言に代わるものではありません。重要な判断は、ご自身の責任で行い、必要に応じて専門家へご相談ください。鑑定結果の利用によって生じたいかなる損害等についても、当方は責任を負いかねます。

**個人情報の取り扱い**  
ご入力いただいた氏名、生年月日、出生地、手相画像などの情報は、鑑定結果の生成とPDF作成のために一時的に使用します。このアプリでは鑑定履歴の恒久保存は行いません。

**使い方**  
1. 合言葉を入力してお進みください。  
2. 必要事項を入力し、相談カテゴリを1〜3個お選びください。  
3. 必要に応じて手相画像をアップロードし、左右を選択してください。  
4. 「龍神さまのお告げを聞く」を押すと、鑑定結果とPDF保存ボタンが表示されます。  
5. 詳細なご案内や販売条件は、紹介ページ・特商法表記をご確認ください。"""
        )

    st.caption("本アプリの鑑定は参考情報としてお楽しみください。重要な判断はご自身の責任で行い、必要に応じて専門家へご相談ください。")
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
    if birth_year != "年を選択" and birth_month != "月を選択" and birth_day_candidate != "日を選択":
        try:
            birth_date = datetime.date(int(birth_year), int(birth_month), int(birth_day_candidate))
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
    birth_hour: str | None = None
    birth_minute: str | None = None
    if birth_time_accuracy != "不明":
        time_col1, time_col2 = st.columns(2)
        with time_col1:
            birth_hour = st.selectbox("時", HOUR_OPTIONS, index=12)
        with time_col2:
            birth_minute = st.selectbox("分", MINUTE_OPTIONS, index=0)
    st.caption("出生時刻が不明な場合は、四柱推命・西洋占星術は参考レベルの読みとして扱います。")
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
    categories: list[str] = []
    for cat in raw_categories:
        if cat != "（未選択）" and cat not in categories:
            categories.append(cat)

    render_form_gap(1)
    st.markdown('<div class="label-sm">特に重視したいことの補足</div>', unsafe_allow_html=True)
    st.caption("特に重視したいことがあればご記入ください。例：仕事の流れ、収入の安定、人間関係の整え方。")
    concern_detail = st.text_area(
        "特に重視したいことの補足",
        placeholder="例: 個人事業主として今後どう進めるべきか、今後1年の流れを重視して見てほしい、など",
        height=110,
    )
    render_form_gap(2)

    st.markdown('<div class="label-sm">手相の写真</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="input-help">手のひら全体が見える、明るくぶれの少ない写真をお選びください。画像は最大2枚までです。</div>',
        unsafe_allow_html=True,
    )
    uploaded_files = st.file_uploader(
        f"手相の写真（最大 {MAX_IMAGE_FILES} 枚 / 1枚 {MAX_IMAGE_SIZE_MB}MBまで）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    hand_sides: list[str] = []
    if uploaded_files:
        st.markdown('<div class="input-help">手相の読みの精度を上げるため、各画像の左右を選んでください。</div>', unsafe_allow_html=True)
        hand_sides = build_selected_hand_sides(uploaded_files)

    st.caption("入力内容は鑑定のためだけに使い、このアプリでは履歴保存を行いません。")
    st.markdown(
        '<div style="font-size:0.92rem; font-weight:600; color:#8a3d24; margin-top:0.2rem;">重要な判断には利用せず、必要に応じて専門家へご相談ください。</div>',
        unsafe_allow_html=True,
    )
    render_form_gap(1)

    if st.button("🐉 龍神さまのお告げを聞く"):

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
            unique_errors = list(dict.fromkeys(errors))
            for err in unique_errors:
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
                    birth_time_text=format_birth_time_text(birth_time_accuracy, birth_hour, birth_minute),
                    image_parts=image_parts,
                    image_meta=image_meta,
                    image_count=len(image_parts),
                )
                with st.spinner("龍神さまが降臨されています..."):
                    result = call_gemini_fortune(payload)
                st.session_state.fortune_json = result
                st.session_state.user_name = payload.user_name
                st.success("お告げを授かりました。")
            except Exception as exc:
                st.error(f"鑑定中に支障が生じました: {exc}")

    data = st.session_state.fortune_json
    if not data:
        return

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
                f"開運アイテム: {advice.get('item', '')}",
                f"開運スポット: {advice.get('spot', '')}",
                f"開運カラー: {advice.get('color', '')}",
                f"運気を上げる行動: {advice.get('luck_action', '')}",
            ]
        ),
    )

    cautions = data.get("cautions", []) or []
    if cautions:
        render_html_box("心に留めること", "\n".join([f"・{x}" for x in cautions]))

    render_html_box("結び", data.get("miko_closing", ""))

    try:
        pdf_data = generate_miko_letter_pdf(st.session_state.user_name, data)
        st.download_button(
            label="📜 巫女からの手紙を保存する（PDF）",
            data=pdf_data,
            file_name=f"miko_letter_{st.session_state.user_name}.pdf",
            mime="application/pdf",
        )
    except Exception as exc:
        st.error("PDF鑑定書の作成に失敗しました。フォントファイル、巫女画像、設定内容を確認してください。")
        if SHOW_DEBUG:
            st.caption(str(exc))

    if SHOW_DEBUG:
        with st.expander("開発メモ"):
            st.markdown(
                f"- 使用モデル: `{GEMINI_MODEL}`\n"
                f"- 手相画像枚数: {len(uploaded_files or [])}\n"
                f"- 相談カテゴリ: {', '.join(categories) if categories else 'なし'}\n"
                f"- 出生時刻の精度: {birth_time_accuracy}\n"
                "- 入力データはセッション内のみで扱い、履歴保存は行わない設計です。"
            )


if __name__ == "__main__":
    main()
