import streamlit as st

st.set_page_config(page_title="test", page_icon="🔮", layout="centered")

st.title("Cloud Run test")
pw = st.text_input("合言葉", type="password")
st.write("入力値の長さ:", len(pw))
