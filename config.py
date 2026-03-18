import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


def get_env(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and (value is None or str(value).strip() == ''):
        raise RuntimeError(f'環境変数 {key} が設定されていません。')
    return '' if value is None else str(value)


APP_TITLE = get_env('APP_TITLE', '龍神さまのお告げ')
APP_SUBTITLE = get_env('APP_SUBTITLE', '巫女が龍神さまの声を聞き、あなたの運命を紐解きます。')
APP_ENV = get_env('APP_ENV', 'local')
LOG_LEVEL = get_env('LOG_LEVEL', 'INFO')
GEMINI_MODEL = get_env('GEMINI_MODEL', 'gemini-2.5-flash')
MIKO_IMAGE_PATH = str(BASE_DIR / get_env('MIKO_IMAGE_PATH', 'miko.png'))
MAX_IMAGE_FILES = int(get_env('MAX_IMAGE_FILES', '2'))
MAX_IMAGE_SIZE_MB = int(get_env('MAX_IMAGE_SIZE_MB', '10'))
SHOW_DEBUG = get_env('SHOW_DEBUG', 'false').lower() == 'true'

PDF_FONT_PATHS = [
    str(BASE_DIR / get_env('PDF_FONT_PATH_1', 'NotoSerifJP-Regular.ttf')),
    str(BASE_DIR / get_env('PDF_FONT_PATH_2', 'SawarabiMincho-Regular.ttf')),
]

CATEGORY_OPTIONS = [
    '総合運',
    '仕事運',
    '金運',
    '恋愛運',
    '健康運',
    '人間関係運',
    '事業運',
    '転機・今後の流れ',
]

TIME_ACCURACY_OPTIONS = ['不明', 'だいたい分かる', '正確に分かる']
HAND_SIDE_OPTIONS = ['右手か左手か選んでください', '左手', '右手']
MINUTE_OPTIONS = [f'{m:02d}' for m in range(0, 60, 10)]
HOUR_OPTIONS = [f'{h:02d}' for h in range(24)]


def get_app_passphrase() -> str:
    return get_env('APP_PASSPHRASE', '', required=False)



def get_gemini_api_key() -> str:
    return get_env('GEMINI_API_KEY', '', required=False)
