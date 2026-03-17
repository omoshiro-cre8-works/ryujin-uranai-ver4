import streamlit as st

def render_app_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;500;700&family=Noto+Sans+JP:wght@400;500&display=swap');

:root {
    --bg-main: #fffdf9;
    --bg-soft: #f2f2ef;
    --bg-soft-2: #e7e7e2;
    --text-main: #1f1f1f;
    --text-sub: #787878;
    --accent: #c24a2c;
    --accent-soft: #ffe6ea;
    --btn-pink: #ffe3e8;
    --btn-pink-hover: #ffd6df;
    --btn-pink-border: #e7b5c1;
    --border: #d5d0c8;
}

html, body, [data-testid="stAppViewContainer"], .main, [data-testid="stMarkdownContainer"], p, li, div {
    background-color: var(--bg-main) !important;
    color: var(--text-main) !important;
    font-family: "Noto Serif JP", "Yu Mincho", "Hiragino Mincho ProN", serif !important;
    font-weight: 400;
}

[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 860px;
    padding-top: 1.3rem;
    padding-bottom: 2.5rem;
}

.title-main {
    color: var(--accent) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-size: clamp(2rem, 4.2vw, 3rem);
    font-weight: 700;
    line-height: 1.25;
    margin: 0.15rem 0 0.55rem 0;
}

.heading-lg {
    color: var(--accent) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-size: clamp(1.55rem, 2.8vw, 2rem);
    font-weight: 500;
    line-height: 1.45;
    margin: 1.7rem 0 0.8rem 0;
}

.heading-md {
    color: var(--accent) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-size: clamp(1.1rem, 2vw, 1.32rem);
    font-weight: 500;
    line-height: 1.55;
    margin: 0 0 0.7rem 0;
}

.label-sm {
    color: var(--text-main) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-size: 1rem;
    font-weight: 500;
    line-height: 1.6;
    margin: 0.2rem 0 0.45rem 0;
}

.small-note,
.input-help,
.stCaption,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] *,
.helper-text {
    color: var(--text-sub) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-size: 0.93rem;
    font-weight: 400;
    line-height: 1.75;
}

.result-body, .result-body * {
    color: var(--text-main) !important;
    font-family: "Noto Serif JP", "Yu Mincho", serif !important;
    font-weight: 400;
    line-height: 1.95;
    font-size: 1rem;
}

.block-box {
    background: #fffdfa !important;
    border: 1px solid rgba(194, 74, 44, 0.75);
    border-radius: 14px;
    padding: 18px 20px;
    margin: 0 0 1.35rem 0;
}

/* Streamlitラベルを隠して自前ラベルを使う */
[data-testid="stWidgetLabel"] {
    display: none !important;
}

/* 入力欄・選択欄はゴシック */
.stTextInput input,
.stTextArea textarea,
.stDateInput input,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
.stButton > button,
.stDownloadButton > button,
[data-testid="stFileUploader"] button,
[data-testid="stFileUploader"] section button {
    font-family: "Noto Sans JP", "Yu Gothic", "Hiragino Sans", sans-serif !important;
    font-weight: 400 !important;
}

.stTextInput input,
.stTextArea textarea,
.stDateInput input,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div {
    background-color: var(--bg-soft) !important;
    color: var(--text-main) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}

/* dropdown list */
div[data-baseweb="popover"],
div[data-baseweb="menu"],
ul[role="listbox"],
div[role="listbox"],
li[role="option"],
div[role="option"] {
    background: var(--bg-soft) !important;
    color: var(--text-main) !important;
    font-family: "Noto Sans JP", "Yu Gothic", sans-serif !important;
}
li[role="option"] *,
div[role="option"] *,
div[data-baseweb="popover"] *,
div[data-baseweb="menu"] * {
    color: var(--text-main) !important;
    font-family: "Noto Sans JP", "Yu Gothic", sans-serif !important;
}
li[role="option"][aria-selected="true"],
div[role="option"][aria-selected="true"] {
    background: #f7dfe5 !important;
}
li[role="option"]:hover,
div[role="option"]:hover {
    background: #f8ecef !important;
}

/* placeholder */
input::placeholder,
textarea::placeholder {
    color: var(--text-sub) !important;
    opacity: 1 !important;
}

/* radio */
div[role="radiogroup"] { gap: 0.65rem; margin-bottom: 0.35rem; }
div[role="radiogroup"] label { background: transparent !important; }
div[role="radiogroup"] label p,
div[role="radiogroup"] label span {
    color: var(--text-main) !important;
    font-family: "Noto Sans JP", "Yu Gothic", sans-serif !important;
    font-weight: 400 !important;
}

/* calendar */
div[data-baseweb="calendar"],
div[data-baseweb="calendar"] > div,
div[data-baseweb="calendar"] div[role="grid"],
div[data-baseweb="calendar"] div[role="row"],
div[data-baseweb="calendar"] div[role="gridcell"],
div[data-baseweb="calendar"] div[role="presentation"],
div[data-baseweb="calendar"] header,
div[data-baseweb="calendar"] [class*="Header"],
div[data-baseweb="calendar"] [class*="header"],
div[data-baseweb="calendar"] [class*="Month"],
div[data-baseweb="calendar"] [class*="month"],
div[data-baseweb="calendar"] [class*="Year"],
div[data-baseweb="calendar"] [class*="year"],
div[data-baseweb="calendar"] [class*="DayNames"],
div[data-baseweb="calendar"] [class*="day-names"] {
    background: var(--bg-soft) !important;
    color: var(--text-main) !important;
    font-family: "Noto Sans JP", "Yu Gothic", sans-serif !important;
}
div[data-baseweb="calendar"] *,
div[data-baseweb="calendar"] *::before,
div[data-baseweb="calendar"] *::after {
    color: var(--text-main) !important;
    fill: var(--text-main) !important;
    border-color: var(--border) !important;
    font-family: "Noto Sans JP", "Yu Gothic", sans-serif !important;
}
div[data-baseweb="calendar"] [aria-selected="true"],
div[data-baseweb="calendar"] button[aria-selected="true"] {
    background: #f7dfe5 !important;
    border-radius: 999px !important;
}

/* uploader */
[data-testid="stFileUploader"] section,
[data-testid="stFileUploaderDropzone"] {
    background: var(--bg-soft) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}
[data-testid="stFileUploader"] * {
    color: var(--text-main) !important;
}
[data-testid="stFileUploader"] button,
[data-testid="stFileUploader"] section button {
    background: var(--bg-soft-2) !important;
    color: var(--text-main) !important;
    border: 1px solid #c5c5c5 !important;
}

/* buttons */
.stButton > button,
.stDownloadButton > button {
    background: var(--btn-pink) !important;
    color: var(--text-main) !important;
    border: 1px solid var(--btn-pink-border) !important;
    border-radius: 12px !important;
    padding: 0.6rem 1.1rem !important;
}
.stButton > button:hover,
.stDownloadButton > button:hover {
    background: var(--btn-pink-hover) !important;
    color: var(--text-main) !important;
}

img { border-radius: 10px; }

@media (max-width: 768px) {
    [data-testid="stAppViewContainer"] .main .block-container {
        max-width: 100%;
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .block-box { padding: 16px 16px; margin-bottom: 1.1rem; }
    .result-body, .result-body * { line-height: 1.9; }
}

/* password eye icon visibility */
[data-testid="stTextInput"] button,
[data-testid="stTextInput"] button svg,
[data-testid="stTextInput"] [data-baseweb="button"],
[data-testid="stTextInput"] [data-baseweb="button"] svg {
    color: #8a8173 !important;
    fill: #8a8173 !important;
    opacity: 1 !important;
    stroke: #8a8173 !important;
}

/* selected birth-time option should be red and bold */
[data-testid="stRadio"] label:has(input:checked) p,
[data-testid="stRadio"] label:has(input:checked) div,
[data-testid="stRadio"] label:has(input:checked) span {
    color: var(--accent) !important;
    font-weight: 700 !important;
}

/* remove inner white background from buttons */
.stButton > button,
.stDownloadButton > button {
    box-shadow: none !important;
    background-image: none !important;
}
.stButton > button *,
.stDownloadButton > button *,
.stButton > button div,
.stDownloadButton > button div,
.stButton > button span,
.stDownloadButton > button span,
.stButton > button p,
.stDownloadButton > button p {
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
}

</style>
        """,
        unsafe_allow_html=True,
    )
