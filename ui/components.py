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



def build_selected_hand_sides(uploaded_files: list[Any]) -> list[str]:
    selections: list[str] = []
    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        st.markdown(f'**画像{idx}: {html.escape(uploaded_file.name)}**')
        selected = st.radio(
            f'{uploaded_file.name} の左右',
            HAND_SIDE_OPTIONS[1:],
            horizontal=True,
            key=f'hand_side_{idx}_{uploaded_file.name}',
        )
        selections.append(selected)
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
