import streamlit as st


def render_app_css() -> None:
    st.markdown(
        '''
        <style>
        /* ===== 全体テーマ ===== */
        body,
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {
            background: #ffffff !important;
            color: #1f1f1f !important;
        }

        /* ヘッダーは白 */
        [data-testid="stHeader"] {
            background: rgba(255, 255, 255, 0.98) !important;
            box-shadow: none !important;
            border-bottom: 1px solid #f2e7e2 !important;
        }

        [data-testid="stToolbar"] {
            background: transparent !important;
        }

        [data-testid="stDecoration"] {
            background: transparent !important;
        }

        [data-testid="stSidebar"] {
            background: #ffffff !important;
        }

        /* ここをさらに増やして、タイトルと巫女画像を下げる */
        [data-testid="stMainBlockContainer"] {
            max-width: 760px;
            padding-top: 3.1rem !important;
            padding-bottom: 3rem;
        }

        /* 最初のブロックに少しだけ追加余白 */
        [data-testid="stMainBlockContainer"] > div:first-child {
            margin-top: 0.4rem !important;
        }

        /* ===== フォント適用 ===== */
        .title-main,
        .heading-lg,
        .label-sm,
        .input-help,
        p, li, label,
        .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown div,
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stSelectbox label,
        .stRadio label,
        .stCheckbox label,
        .stButton > button,
        .stDownloadButton > button,
        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] input,
        div[data-baseweb="base-input"] > div {
            font-family: "Hiragino Mincho ProN", "Hiragino Mincho Pro",
                         "Yu Mincho", "YuMincho", "Noto Serif JP",
                         "MS PMincho", Georgia, serif !important;
            -webkit-font-smoothing: antialiased;
            text-rendering: optimizeLegibility;
        }

        .material-symbols-rounded,
        .material-symbols-outlined,
        .material-icons,
        [class*="material-symbols"],
        [class*="material-icons"] {
            font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
            font-weight: normal !important;
            font-style: normal !important;
            letter-spacing: normal !important;
            text-transform: none !important;
            white-space: nowrap !important;
            word-wrap: normal !important;
            direction: ltr !important;
        }

        p, li, div, label, span {
            color: #1f1f1f;
        }

        .stMarkdown p,
        .stMarkdown li,
        .stMarkdown div {
            color: #222222 !important;
            font-weight: 500;
            line-height: 1.85;
        }

        a {
            color: #8a3d24;
        }

        hr {
            border-color: #eadfd8;
        }

        /* ===== 見出し・ラベル ===== */
        .stMarkdown div.title-main,
        div.title-main {
            font-size: 1.95rem !important;
            font-weight: 700 !important;
            color: #8a3d24 !important;
            margin-top: 0.1rem !important;
            margin-bottom: 0.3rem !important;
            line-height: 1.35 !important;
            letter-spacing: 0.02em !important;
        }

        .stMarkdown div.heading-lg,
        div.heading-lg {
            font-size: 1.22rem !important;
            font-weight: 700 !important;
            color: #8a3d24 !important;
            margin-top: 1rem !important;
            margin-bottom: 0.7rem !important;
            line-height: 1.5 !important;
        }

        .stMarkdown div.label-sm,
        div.label-sm {
            font-size: 0.97rem !important;
            font-weight: 700 !important;
            color: #8a3d24 !important;
            margin-bottom: 0.35rem !important;
            line-height: 1.5 !important;
        }

        .stMarkdown div.input-help,
        div.input-help {
            font-size: 0.84rem !important;
            color: #666666 !important;
            margin-top: 0.22rem !important;
            margin-bottom: 0.45rem !important;
            line-height: 1.7 !important;
            font-weight: 500 !important;
        }

        .title-main + .result-body {
            color: #5f5f5f !important;
            font-weight: 500;
        }

        /* ===== 入力系 ===== */
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

        div[data-baseweb="select"] span,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] div {
            color: #1f1f1f !important;
            font-weight: 500;
        }

        div[role="listbox"],
        ul[role="listbox"] {
            background: #f2f2f2 !important;
            border: 1px solid #d6d6d6 !important;
            color: #1f1f1f !important;
        }

        div[role="option"],
        li[role="option"] {
            background: #f2f2f2 !important;
            color: #1f1f1f !important;
            font-weight: 500 !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover {
            background: #e7e7e7 !important;
            color: #1f1f1f !important;
        }

        div[aria-selected="true"],
        li[aria-selected="true"] {
            background: #dddddd !important;
            color: #1f1f1f !important;
        }

        body [data-baseweb="popover"],
        body [data-baseweb="menu"] {
            background: #f2f2f2 !important;
            color: #1f1f1f !important;
        }

        body [data-baseweb="popover"] *,
        body [data-baseweb="menu"] * {
            color: #1f1f1f !important;
        }

        .stRadio label,
        .stCheckbox label {
            color: #1f1f1f !important;
            font-weight: 500;
        }

        /* ===== file uploader ===== */
        [data-testid="stFileUploader"] section {
            background: #fffdfa;
            border: 1px dashed #d9c9c1;
            border-radius: 12px;
        }

        [data-testid="stFileUploader"] small,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] div {
            color: #444444;
            font-weight: 500;
        }

        [data-testid="stFileUploader"] button {
            background: #efefef !important;
            color: #333333 !important;
            border: 1px solid #d2d2d2 !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
        }

        [data-testid="stFileUploader"] button:hover {
            background: #e4e4e4 !important;
            color: #222222 !important;
            border-color: #c8c8c8 !important;
        }

        /* ===== ボタン ===== */
        .stButton > button {
            background: #f3d6de;
            color: #7a3248;
            border: 1px solid #e2b8c4;
            border-radius: 999px;
            padding: 0.6rem 1.1rem;
            font-weight: 700;
            transition: all 0.2s ease;
        }

        .stButton > button:hover {
            background: #ecc9d4;
            border-color: #d8a8b8;
            color: #6e2940;
        }

        .stButton > button:focus:not(:active) {
            border-color: #d8a8b8;
            box-shadow: 0 0 0 0.2rem rgba(216, 168, 184, 0.28);
            color: #6e2940;
        }

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
        .streamlit-expanderHeader *,
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary * {
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
            font-weight: 500;
        }

        /* ===== キャプション ===== */
        .stCaption,
        [data-testid="stCaptionContainer"] {
            color: #6c6c6c !important;
            font-weight: 500;
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

        .stMarkdown .result-box .result-title,
        .stMarkdown .result-box .result-title *,
        .result-box .result-title,
        .result-box .result-title * {
            font-size: 1.03rem !important;
            font-weight: 700 !important;
            color: #8a3d24 !important;
            margin-bottom: 0.55rem !important;
            line-height: 1.6 !important;
        }

        .stMarkdown .result-box .result-body,
        .stMarkdown .result-box .result-body *,
        .result-box .result-body,
        .result-box .result-body * {
            line-height: 1.9 !important;
            color: #2f2f2f !important;
            font-size: 0.98rem !important;
            white-space: pre-wrap !important;
            font-weight: 500 !important;
        }

        .block-container {
            padding-top: 1rem;
        }

        .element-container {
            margin-bottom: 0.15rem;
        }

        @media (max-width: 640px) {
            [data-testid="stMainBlockContainer"] {
                padding-top: 2.35rem !important;
                padding-left: 1rem;
                padding-right: 1rem;
                padding-bottom: 2.4rem;
            }

            [data-testid="stMainBlockContainer"] > div:first-child {
                margin-top: 0.25rem !important;
            }

            .stMarkdown div.title-main,
            div.title-main {
                font-size: 1.6rem !important;
            }

            .stMarkdown div.heading-lg,
            div.heading-lg {
                font-size: 1.08rem !important;
            }

            .result-box {
                padding: 14px 14px;
            }

            .stMarkdown .result-box .result-body,
            .result-box .result-body {
                font-size: 0.95rem !important;
                line-height: 1.85 !important;
            }
        }
        </style>
        ''',
        unsafe_allow_html=True,
    )
