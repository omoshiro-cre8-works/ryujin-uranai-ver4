import html
from typing import Any

import streamlit as st

from config import HAND_SIDE_OPTIONS, get_app_passphrase


def render_form_gap(size: int = 1) -> None:
    for _ in range(max(size, 0)):
        st.markdown('<div style="height:0.35rem"></div>', unsafe_allow_html=True)


def is_passphrase_ok(passphrase: str) -> bool:
    actual = get_app_passphrase()
    if not actual:
        return False
    if not passphrase:
        return False
    if passphrase.strip() != actual.strip():
        st.warning('合言葉を正しく入力してください。')
        return False
    return True


def _safe_file_bytes(uploaded_file: Any) -> bytes:
    """UploadedFile を安全に bytes 化して返す。"""
    if uploaded_file is None:
        return b""

    try:
        data = uploaded_file.getvalue()
        if data:
            return data
    except Exception:
        pass

    try:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        if data:
            return data
    except Exception:
        pass

    return b""


def build_selected_hand_sides(uploaded_files: list[Any]) -> list[str]:
    selections: list[str] = []

    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        raw_name = getattr(uploaded_file, "name", f"image_{idx}")
        file_name = html.escape(raw_name)
        image_bytes = _safe_file_bytes(uploaded_file)

        st.markdown(f'**画像{idx}: {file_name}**')

        if image_bytes:
            st.image(image_bytes, caption=raw_name, width=260)
        else:
            st.warning(f"{file_name} のプレビュー表示に失敗しました。")

        selected = st.radio(
            f'{raw_name} の左右',
            HAND_SIDE_OPTIONS[1:],
            horizontal=True,
            key=f'hand_side_{idx}_{raw_name}',
        )
        selections.append(selected)

        try:
            uploaded_file.seek(0)
        except Exception:
            pass

        if idx != len(uploaded_files):
            st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    return selections


def render_html_box(title: str, body: str) -> None:
    safe_title = html.escape(title)
    paragraphs = [html.escape(line) for line in (body or '').split('\n')]
    content = '<br><br>'.join([p for p in paragraphs if p])
    st.markdown(
        f'''
        <div class="result-box">
            <div class="result-title">{safe_title}</div>
            <div class="result-body">{content}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )
