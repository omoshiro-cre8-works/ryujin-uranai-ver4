import streamlit as st

st.set_page_config(page_title="龍神うらない", page_icon="🐉")

st.title("龍神うらない")
st.write("試験公開版です。気になることを入力して、仮の鑑定結果を試せます。")

name = st.text_input("お名前")
theme = st.selectbox(
    "占術を選んでください",
    ["手相風", "四柱推命風", "西洋占星術風"]
)
question = st.text_area("相談内容", placeholder="例：仕事運、恋愛、今後の流れについて知りたいです。")

if st.button("鑑定する"):
    if not name or not question:
        st.warning("お名前と相談内容を入力してください。")
    else:
        st.subheader("鑑定結果")
        st.write(f"{name}さんへの{theme}鑑定結果です。")
        
        if theme == "手相風":
            st.success("今は準備してきた力を少しずつ表に出す時期です。焦らず積み重ねることで運が開いていきます。")
        elif theme == "四柱推命風":
            st.success("流れとしては『土台固め』が大切な時期です。大きく動くより、足元を整えるほど後半に強さが出ます。")
        else:
            st.success("あなたの運気は、これから少しずつ追い風に向かう流れです。特に自分の本音を大切にすることで良い変化が起こりやすくなります。")
