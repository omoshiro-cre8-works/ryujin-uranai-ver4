import streamlit as st

st.set_page_config(page_title="uploader test", page_icon="🔮", layout="centered")

st.title("File uploader 単体テスト")

name = st.text_input("名前", value="テスト")
st.write("名前:", name)

uploaded = st.file_uploader(
    "画像を選択してください",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=False,
)

if uploaded is not None:
    st.success(f"アップロードされたファイル名: {uploaded.name}")
    st.write("ファイルサイズ:", uploaded.size)
