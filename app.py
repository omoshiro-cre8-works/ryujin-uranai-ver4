import streamlit as st

st.set_page_config(page_title="radio test", page_icon="🔮", layout="centered")

st.title("Radio 単体テスト")

name = st.text_input("名前", value="テスト")
st.write("名前:", name)

accuracy = st.radio(
    "出生時刻の分かり具合",
    ["不明", "だいたい分かる", "正確に分かる"],
    horizontal=True,
    index=0,
)
st.write("選択:", accuracy)
