import os
import streamlit as st

st.set_page_config(
    page_title="龍神うらない",
    page_icon="🔮",
    layout="centered"
)

# 軽い custom CSS
# 今回は input / button 周辺にだけ最小限触る
st.markdown(
    """
    <style>
    .test-box {
        padding: 12px 16px;
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 12px;
        margin: 8px 0 20px 0;
        background: rgba(255,255,255,0.03);
    }

    .test-note {
        font-size: 0.95rem;
        line-height: 1.6;
    }

    /* input まわりに軽く干渉 */
    div[data-baseweb="input"] > div {
        border-radius: 12px;
    }

    /* button に軽く干渉 */
    .stButton > button {
        border-radius: 12px;
        padding: 0.4rem 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("龍神うらない（input/button軽干渉テスト版）")

st.write("この段階では、input と button 周辺への軽い CSS 干渉を確認します。")

st.markdown(
    """
    <div class="test-box">
        <div class="test-note">
            この版では input / button にだけ軽く CSS を当てています。<br>
            色変更や position 指定などの強い干渉はまだ入れていません。
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

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

st.caption("この画面で問題が出なければ、次により強いフォームCSSか複雑なHTML構造を疑います。")
