from typing import Any

from config import (
    HAND_SIDE_OPTIONS,
    MAX_IMAGE_FILES,
    MAX_IMAGE_SIZE_MB,
    get_app_passphrase,
    get_gemini_api_key,
)


def normalize_text(value: str) -> str:
    return (value or '').strip()



def get_mime_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith('.png'):
        return 'image/png'
    if lower.endswith('.jpg') or lower.endswith('.jpeg'):
        return 'image/jpeg'
    raise ValueError('未対応の画像形式です。PNG、JPG、JPEG の画像を選んでください。')



def format_birth_time_text(accuracy: str, hour: str | None, minute: str | None) -> str:
    if accuracy == '不明':
        return '不明'
    if not hour or not minute:
        return '未入力'
    if accuracy == 'だいたい分かる':
        return f'だいたい {hour}:{minute} 頃'
    return f'{hour}:{minute}'



def validate_inputs(
    user_name: str,
    birth_place: str,
    categories: list[str],
    concern_detail: str,
    birth_time_accuracy: str,
    birth_hour: str | None,
    birth_minute: str | None,
    uploaded_files: list[Any],
    hand_sides: list[str],
) -> list[str]:
    errors: list[str] = []
    normalized_name = normalize_text(user_name)
    normalized_birth_place = normalize_text(birth_place)
    normalized_detail = normalize_text(concern_detail)

    if not normalized_name:
        errors.append('お名前をご入力ください。')
    if len(normalized_name) > 60:
        errors.append('お名前は60文字以内でご入力ください。')
    if not normalized_birth_place:
        errors.append('出生地をご入力ください。')
    if len(normalized_birth_place) > 100:
        errors.append('出生地は100文字以内でご入力ください。')
    if len(normalized_detail) > 300:
        errors.append('相談内容の補足は300文字以内でご入力ください。')

    if not categories:
        errors.append('相談カテゴリを1つ以上選んでください。')
    if len(categories) > 3:
        errors.append('相談カテゴリは最大3つまでにしてください。')

    if birth_time_accuracy != '不明' and (not birth_hour or not birth_minute):
        errors.append('出生時刻を入力する場合は、時と分の両方を選択してください。')

    if len(uploaded_files) > MAX_IMAGE_FILES:
        errors.append(f'手相画像は {MAX_IMAGE_FILES} 枚までにしてください。')

    if len(hand_sides) != len(uploaded_files):
        errors.append('手相画像の左右情報が不足しています。')

    for index, file in enumerate(uploaded_files):
        size_mb = getattr(file, 'size', 0) / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            errors.append(f'画像サイズが大きすぎます。1枚あたり{MAX_IMAGE_SIZE_MB}MB以下の画像を選んでください。')
        try:
            get_mime_type(file.name)
        except ValueError as exc:
            errors.append(str(exc))
        if index < len(hand_sides):
            selected = hand_sides[index]
            if selected not in HAND_SIDE_OPTIONS[1:]:
                errors.append('手相画像ごとに左手・右手を選択してください。')

    if not get_gemini_api_key():
        errors.append('Gemini APIキーが設定されていません。Cloud Run の環境変数または Secret Manager の設定を確認してください。')

    if not get_app_passphrase():
        errors.append('合言葉が設定されていません。Cloud Run の環境変数または Secret Manager の設定を確認してください。')

    return list(dict.fromkeys(errors))
