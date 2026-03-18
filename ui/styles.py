import streamlit as st



def render_app_css() -> None:
    st.markdown(
        '''
        <style>
        .title-main {
            font-size: 1.9rem;
            font-weight: 700;
            color: #8a3d24;
            margin-top: 0.2rem;
            margin-bottom: 0.3rem;
        }
        .heading-lg {
            font-size: 1.2rem;
            font-weight: 700;
            color: #8a3d24;
            margin-top: 1rem;
            margin-bottom: 0.7rem;
        }
        .label-sm {
            font-size: 0.96rem;
            font-weight: 600;
            color: #6d2f1b;
            margin-bottom: 0.3rem;
        }
        .input-help {
            font-size: 0.84rem;
            color: #6a6a6a;
            margin-top: 0.2rem;
            margin-bottom: 0.4rem;
        }
        .result-box {
            border: 1px solid #ead5cb;
            border-radius: 14px;
            padding: 16px 18px;
            background: #fffdfa;
            margin-bottom: 0.9rem;
        }
        .result-title {
            font-size: 1.02rem;
            font-weight: 700;
            color: #8a3d24;
            margin-bottom: 0.55rem;
        }
        .result-body {
            line-height: 1.9;
            color: #2f2f2f;
            font-size: 0.97rem;
            white-space: pre-wrap;
        }
        </style>
        ''',
        unsafe_allow_html=True,
    )
