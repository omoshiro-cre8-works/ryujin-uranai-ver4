import streamlit as st

st.set_page_config(page_title="selectbox test", page_icon="🔮", layout="centered")

st.title("Selectbox 単体テスト")

name = st.text_input("名前", value="テスト")
st.write("名前:", name)

year = st.selectbox("年", ["年を選択", 2026, 2025, 2024], index=0)
st.write("選択された年:", year)
