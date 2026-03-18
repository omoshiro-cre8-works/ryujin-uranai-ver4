import os
import streamlit as st

st.set_page_config(
    page_title="龍神うらない",
    page_icon="🔮",
    layout="centered"
)

st.title("龍神うらない（画像追加テスト版）")

st.write("これは Cloud Run 上での表示確認用の画像追加テスト版です。")
st.write("この段階では、Streamlit標準機能に加えて画像表示のみ確認します。")

st.divider()

st.subheader("画像表示テスト")

image_candidates = [
    "miko.png",
    "images/miko.png",
    "./miko.png",
    "./images/miko.png",
]

found_image = None
for path in image_candidates:
    if os.path.exists(path):
        found_image = path
        break

if found_image:
    st.success(f"画像ファイルを見つけました: {found_image}")
    st.image(found_image, caption="テスト表示画像", use_container_width=True)
else:
    st.warning("画像ファイルが見つかりませんでした。")
    st.write("確認したパス:")
    for path in image_candidates:
        st.write(f"- {path}")

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

st.caption("この画面で問題が出なければ、次に独自CSSやHTMLを段階的に戻します。")
