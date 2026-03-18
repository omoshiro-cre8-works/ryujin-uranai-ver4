import streamlit as st

st.set_page_config(
    page_title="龍神うらない",
    page_icon="🔮",
    layout="centered"
)

st.title("龍神うらない（中間テスト版）")

st.write(
    "これは Cloud Run 上での表示確認用の中間テスト版です。"
)
st.write(
    "この段階では、Streamlit標準機能のみを使って動作確認しています。"
)

st.divider()

st.subheader("合言葉入力テスト")

password = st.text_input("合言葉を入力してください", type="password")

col1, col2 = st.columns(2)

with col1:
    check_clicked = st.button("確認する")

with col2:
    clear_clicked = st.button("クリア")

if clear_clicked:
    st.rerun()

if check_clicked:
    if password.strip() == "":
        st.warning("合言葉が未入力です。")
    else:
        st.success("入力は正常に受け付けられました。")
        st.write(f"入力値の長さ: {len(password)}")

st.divider()

st.caption("この画面で問題が出なければ、次に画像表示や装飾を段階的に戻します。")
