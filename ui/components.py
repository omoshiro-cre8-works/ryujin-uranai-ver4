import hmac
import html
from typing import Any

import streamlit as st

from config import HAND_SIDE_OPTIONS, get_app_passphrase


def render_html_box(title: str, body: str) -> None:
    safe_title = html.escape(title)
    safe_body = html.escape(body or "").replace("\n", "<br>")
    st.markdown(
        f'<div class="block-box"><div class="heading-md">{safe_title}</div><div class="result-body">{safe_body}</div></div>',
        unsafe_allow_html=True,
    )


def is_passphrase_ok(value: str) -> bool:
    app_passphrase = get_app_passphrase()
    if not app_passphrase:
        return False
    return hmac.compare_digest(value.encode("utf-8"), app_passphrase.encode("utf-8"))


def render_form_gap(lines: int = 1) -> None:
    height = "1.0rem" if lines <= 1 else "1.7rem"
    st.markdown(f'<div style="height:{height};"></div>', unsafe_allow_html=True)


def build_selected_hand_sides(uploaded_files: list[Any]) -> list[str]:
    hand_sides: list[str] = []
    columns = st.columns(len(uploaded_files))
    for index, (file, col) in enumerate(zip(uploaded_files, columns)):
        with col:
            st.image(file.getvalue(), use_container_width=True)
            chosen = st.selectbox(
                "左右を選択",
                HAND_SIDE_OPTIONS,
                key=f"hand_side_{index}_{file.name}",
            )
            st.caption(f"画像{index + 1}: {file.name}")
        hand_sides.append(chosen)
    return hand_sides
