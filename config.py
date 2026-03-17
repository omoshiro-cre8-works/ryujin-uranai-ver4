import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def get_secret(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)
    except Exception:
        pass
    return os.getenv(key, default)


APP_TITLE = os.getenv("APP_TITLE", "龍神さまのお告げ")
APP_SUBTITLE = os.getenv("APP_SUBTITLE", "巫女が龍神さまの声を聞き、あなたの運命を紐解きます。")

APP_PASSPHRASE = get_secret("APP_PASSPHRASE", "")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY", "")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MIKO_IMAGE_PATH = os.getenv("MIKO_IMAGE_PATH", "miko.png")
MAX_IMAGE_FILES = int(os.getenv("MAX_IMAGE_FILES", "2"))
MAX_IMAGE_SIZE_MB = int(os.getenv("MAX_IMAGE_SIZE_MB", "10"))

PDF_FONT_PATHS = [
    os.getenv("PDF_FONT_PATH_1", "NotoSerifJP-Regular.ttf"),
    os.getenv("PDF_FONT_PATH_2", "SawarabiMincho-Regular.ttf"),
]

SHOW_DEBUG = os.getenv("SHOW_DEBUG", "false").lower() == "true"

CATEGORY_OPTIONS = [
    "総合運",
    "仕事運",
    "金運",
    "恋愛運",
    "健康運",
    "人間関係運",
    "事業運",
    "転機・今後の流れ",
]

TIME_ACCURACY_OPTIONS = ["不明", "だいたい分かる", "正確に分かる"]
HAND_SIDE_OPTIONS = ["右手か左手か選んでください", "左手", "右手"]
MINUTE_OPTIONS = [f"{m:02d}" for m in range(0, 60, 10)]
HOUR_OPTIONS = [f"{h:02d}" for h in range(24)]