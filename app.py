import streamlit as st

st.set_page_config(page_title="columns selectbox test", page_icon="🔮", layout="centered")

st.title("Columns + Selectbox テスト")

name = st.text_input("名前", value="テスト")
st.write("名前:", name)

st.subheader("生年月日")

col1, col2, col3 = st.columns(3)

with col1:
    year = st.selectbox("年", ["年を選択", 2026, 2025, 2024], index=0)

with col2:
    month = st.selectbox("月", ["月を選択", 1, 2, 3, 4, 5], index=0)

with col3:
    day = st.selectbox("日", ["日を選択", 1, 2, 3, 4, 5], index=0)

st.write("選択結果:", year, month, day)
