import streamlit as st


def render_app_css() -> None:
    st.markdown(
        """
        <style>
        /* ===== 全体テーマ ===== */
        html, body, [class*="css"] {
            font-family: "Yu Mincho", "Hiragino Mincho ProN", "Hiragino Mincho Pro",
                         "YuMincho", "MS PMincho", Georgia, serif;
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {
            background: #ffffff;
            color: #1f1f1f;
        }

        [data-testid="stHeader"] {
            background: rgba(255, 255, 255, 0.92);
        }

        [data-testid="stToolbar"] {
            background: transparent;
        }

        [data-testid="stDecoration"] {
            background: transparent;
        }

        [data-testid="stSidebar"] {
            background: #ffffff;
        }

        [data-testid="stMainBlockContainer"] {
            max-width: 760px;
            padding-top: 1.4rem;
            padding-bottom: 3rem;
        }

        p, li, div, label, span {
            color: #1f1f1f;
        }

        a {
            color: #8a3d24;
        }

        hr {
            border-color: #eadfd8;
        }

        /* ===== 見出し・ラベル ===== */
        .title-main {
            font-size: 1.95rem;
            font-weight: 700;
            color: #8a3d24;
            margin-top: 0.15rem;
            margin-bottom: 0.3rem;
            line-height: 1.35;
            letter-spacing: 0.02em;
        }

        .heading-lg {
            font-size: 1.22rem;
            font-weight: 700;
            color: #8a3d24;
            margin-top: 1rem;
            margin-bottom: 0.7rem;
            line-height: 1.5;
        }

        .label-sm {
            font-size: 0.97rem;
            font-weight: 700;
            color: #8a3d24;
            margin-bottom: 0.35rem;
            line-height: 1.5;
        }

        .input-help {
            font-size: 0.84rem;
            color: #666666;
            margin-top: 0.22rem;
            margin-bottom: 0.45rem;
            line-height: 1.7;
        }

        /* app.py でサブタイトルに result-body を流用しているため補正 */
        .title-main + .result-body {
            color: #5f5f5f;
        }

        /* ===== テキスト入力・各種入力 ===== */
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        div[data-baseweb="select"] > div,
        div[data-baseweb="base-input"] > div {
            background: #ffffff !important;
            color: #1f1f1f !important;
            border: 1px solid #d9c9c1 !important;
            border-radius: 10px !important;
        }

        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder {
            color: #8b8b8b !important;
        }

        .stTextInput input:focus,
        .stTextArea textarea:focus,
        .stNumberInput input:focus {
            border-color: #c26b4a !important;
            box-shadow: 0 0 0 1px #c26b4a !important;
        }

        /* selectbox 表示部 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] div {
            color: #1f1f1f !important;
        }

        /* radio / checkbox */
        .stRadio label,
        .stCheckbox label {
            color: #1f1f1f !important;
        }

        /* file uploader */
        [data-testid="stFileUploader"] section {
            background: #fffdfa;
            border: 1px dashed #d9c9c1;
            border-radius: 12px;
        }

        [data-testid="stFileUploader"] small,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] div {
            color: #444444;
        }

        /* ===== ボタン ===== */
        .stButton > button {
            background: #8a3d24;
            color: #ffffff;
            border: 1px solid #8a3d24;
            border-radius: 999px;
            padding: 0.6rem 1.1rem;
            font-weight: 700;
            transition: all 0.2s ease;
        }

        .stButton > button:hover {
            background: #9a4a2f;
            border-color: #9a4a2f;
            color: #ffffff;
        }

        .stButton > button:focus:not(:active) {
            border-color: #9a4a2f;
            box-shadow: 0 0 0 0.2rem rgba(154, 74, 47, 0.18);
            color: #ffffff;
        }

        /* download button */
        .stDownloadButton > button {
            background: #fff7f4;
            color: #8a3d24;
            border: 1px solid #d9b3a2;
            border-radius: 999px;
            padding: 0.58rem 1rem;
            font-weight: 700;
        }

        .stDownloadButton > button:hover {
            background: #fceee8;
            color: #8a3d24;
            border-color: #c9927a;
        }

        /* ===== Expander ===== */
        .streamlit-expanderHeader,
        [data-testid="stExpander"] summary {
            background: #fffdfa;
            color: #8a3d24 !important;
            border-radius: 10px;
            font-weight: 700;
        }

        [data-testid="stExpander"] {
            border: 1px solid #ead5cb;
            border-radius: 12px;
            overflow: hidden;
            background: #ffffff;
        }

        [data-testid="stExpanderDetails"] {
            background: #ffffff;
        }

        [data-testid="stExpanderDetails"] p,
        [data-testid="stExpanderDetails"] li,
        [data-testid="stExpanderDetails"] div {
            color: #1f1f1f !important;
            line-height: 1.85;
        }

        /* ===== メッセージ ===== */
        [data-testid="stAlert"] {
            border-radius: 12px;
        }

        .stCaption,
        [data-testid="stCaptionContainer"] {
            color: #6c6c6c !important;
        }

        /* ===== 結果カード ===== */
        .result-box {
            border: 1px solid #ead5cb;
            border-radius: 14px;
            padding: 16px 18px;
            background: #fffdfa;
            margin-bottom: 0.9rem;
            box-shadow: 0 1px 0 rgba(0, 0, 0, 0.02);
        }

        .result-title {
            font-size: 1.03rem;
            font-weight: 700;
            color: #8a3d24;
            margin-bottom: 0.55rem;
            line-height: 1.6;
        }

        .result-body {
            line-height: 1.9;
            color: #2f2f2f;
            font-size: 0.98rem;
            white-space: pre-wrap;
        }

        /* ===== 区切り・余白 ===== */
        .block-container {
            padding-top: 1.2rem;
        }

        .element-container {
            margin-bottom: 0.15rem;
        }

        /* ===== スマホ幅 ===== */
        @media (max-width: 640px) {
            [data-testid="stMainBlockContainer"] {
                padding-top: 1rem;
                padding-left: 1rem;
                padding-right: 1rem;
                padding-bottom: 2.4rem;
            }

            .title-main {
                font-size: 1.6rem;
            }

            .heading-lg {
                font-size: 1.08rem;
            }

            .result-box {
                padding: 14px 14px;
            }

            .result-body {
                font-size: 0.95rem;
                line-height: 1.85;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
