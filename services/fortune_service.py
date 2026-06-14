import json
import logging
import re
from datetime import date, datetime
from typing import Any

from google import genai
from google.genai import types

from config import GEMINI_MODEL, get_gemini_api_key
from models.schemas import AppConfigError, FORTUNE_RESPONSE_JSON_SCHEMA, FortuneInput
from services.formatter_service import normalize_fortune_result
from services.prompt_service import build_system_instruction, build_user_prompt
from services.validation_service import get_mime_type

logger = logging.getLogger(__name__)
_client: genai.Client | None = None
_client_api_key: str | None = None


REVIEW_PDF_ANALYSIS_RESPONSE_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'is_valid_previous_pdf': {'type': 'boolean'},
        'confidence': {'type': 'string'},
        'previous_reading_date': {'type': 'string'},
        'previous_reading_date_original': {'type': 'string'},
        'previous_reading_date_confidence': {'type': 'string'},
        'detected_customer_name': {'type': 'string'},
        'detected_sections': {
            'type': 'array',
            'items': {'type': 'string'},
        },
        'missing_sections': {
            'type': 'array',
            'items': {'type': 'string'},
        },
        'reason': {'type': 'string'},
    },
    'required': [
        'is_valid_previous_pdf',
        'confidence',
        'previous_reading_date',
        'previous_reading_date_original',
        'previous_reading_date_confidence',
        'detected_customer_name',
        'detected_sections',
        'missing_sections',
        'reason',
    ],
}

REVIEW_REQUIRED_SECTIONS = [
    '龍神さまのお告げ',
    '龍神さまの鑑定書',
    '鑑定のまとめ',
    '手相の導き',
    '姓名判断',
    '四柱推命',
    '西洋占星術',
    '直近：これから3カ月以内の運勢',
    '展望：これから1年先の運勢',
    '未来：2〜3年後の運勢',
    '巫女の助言',
    '心に留めること',
    '結び',
]



def get_gemini_client(api_key: str) -> genai.Client:
    global _client, _client_api_key
    if not api_key:
        raise AppConfigError('Gemini APIキーが設定されていません。Cloud Run の環境変数または Secret Manager の設定を確認してください。')
    if _client is None or _client_api_key != api_key:
        _client = genai.Client(api_key=api_key)
        _client_api_key = api_key
    return _client



def build_image_parts(uploaded_files: list[Any]) -> list[Any]:
    parts: list[Any] = []
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        mime_type = get_mime_type(uploaded_file.name)
        parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    return parts


def build_review_pdf_analysis_prompt(current_reading_date: date | None = None) -> str:
    current_date = current_reading_date or date.today()
    sections_text = '\n'.join([f'- {section}' for section in REVIEW_REQUIRED_SECTIONS])
    return f"""
アップロードされたPDFが、AIうらない「龍神さまのお告げ」の前回鑑定PDFらしいかを確認してください。

今回鑑定日: {current_date.isoformat()}

PDFから以下を読み取り、必ずJSONのみで返してください。
- 前回鑑定日
- 前回鑑定日の元表記
- 西暦変換した前回鑑定日（YYYY-MM-DD）
- 鑑定対象者名
- 「龍神さまのお告げ」PDFらしさ
- 検出できた章
- 不足している章
- 判定理由

日付表記の例:
- 令和 8年 5月 30日
- 令和8年5月30日
- 2026年5月30日

和暦が出た場合は西暦へ変換してください。例: 令和8年5月30日 → 2026-05-30。

期待する章:
{sections_text}

特に重要な要素:
- 鑑定日
- 直近：これから3カ月以内の運勢
- 展望：これから1年先の運勢
- 未来：2〜3年後の運勢
- 巫女の助言

判定方針:
- すべての章が完全一致しなくても、龍神さまのお告げの鑑定PDFとして十分に読める場合は valid としてよい。
- 前回のお告げを「当たり」「外れ」と評価しない。
- 姓名や生年月日から見る本質的傾向は、前回から大きく変わるものとして扱わない。
- 時期運、現在の手相、近況、相談テーマは、今回時点で再解釈する対象として扱う。

confidence と previous_reading_date_confidence は high / medium / low のいずれかにしてください。
previous_reading_date が読み取れない場合は空文字にしてください。
""".strip()


def _safe_error_message(exc: Exception, limit: int = 180) -> str:
    message = str(exc).replace('\n', ' ').replace('\r', ' ').strip()
    message = re.sub(r'AIza[0-9A-Za-z_\-]{20,}', '[redacted-api-key]', message)
    message = re.sub(r'key=[^&\s]+', 'key=[redacted]', message)
    if len(message) > limit:
        return message[:limit] + '...'
    return message


def _empty_review_pdf_analysis(
    reason: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_reading_date = date.today()
    result = {
        'is_valid_previous_pdf': False,
        'confidence': 'low',
        'previous_reading_date': '',
        'previous_reading_date_original': '',
        'previous_reading_date_confidence': 'low',
        'detected_customer_name': '',
        'detected_sections': [],
        'missing_sections': REVIEW_REQUIRED_SECTIONS.copy(),
        'reason': reason,
        'current_reading_date': current_reading_date.isoformat(),
        'days_since_previous_reading': None,
        'months_since_previous_reading': None,
    }
    if diagnostics:
        result['diagnostics'] = diagnostics
    return result


def normalize_review_reading_date(value: str, original_value: str = '') -> str:
    candidate = (value or original_value or '').strip()
    if not candidate:
        return ''

    western_match = re.search(r'(20\d{2})[-/年]\s*(\d{1,2})[-/月]\s*(\d{1,2})', candidate)
    if western_match:
        year, month, day = [int(part) for part in western_match.groups()]
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return ''

    reiwa_match = re.search(r'令和\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', candidate)
    if reiwa_match:
        era_year_text, month_text, day_text = reiwa_match.groups()
        era_year = 1 if era_year_text == '元' else int(era_year_text)
        year = 2018 + era_year
        try:
            return date(year, int(month_text), int(day_text)).isoformat()
        except ValueError:
            return ''

    return ''


def add_review_pdf_date_deltas(result: dict[str, Any], current_reading_date: date | None = None) -> dict[str, Any]:
    current_date = current_reading_date or date.today()
    result['current_reading_date'] = current_date.isoformat()
    previous_date_text = normalize_review_reading_date(
        str(result.get('previous_reading_date', '')),
        str(result.get('previous_reading_date_original', '')),
    )
    result['previous_reading_date'] = previous_date_text

    if not previous_date_text:
        result['days_since_previous_reading'] = None
        result['months_since_previous_reading'] = None
        return result

    try:
        previous_date = datetime.strptime(previous_date_text, '%Y-%m-%d').date()
    except ValueError:
        result['days_since_previous_reading'] = None
        result['months_since_previous_reading'] = None
        return result

    result['days_since_previous_reading'] = (current_date - previous_date).days
    months = (current_date.year - previous_date.year) * 12 + (current_date.month - previous_date.month)
    if current_date.day < previous_date.day:
        months -= 1
    result['months_since_previous_reading'] = months
    return result


def parse_review_pdf_analysis_result(raw_text: str) -> dict[str, Any]:
    text = (raw_text or '').strip()
    if not text:
        return _empty_review_pdf_analysis('GeminiからPDF判定結果が返ってきませんでした。')

    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _empty_review_pdf_analysis('GeminiのPDF判定結果をJSONとして解析できませんでした。')

    if not isinstance(parsed, dict):
        return _empty_review_pdf_analysis('GeminiのPDF判定結果の形式が想定と異なります。')

    result = _empty_review_pdf_analysis(str(parsed.get('reason') or 'PDF判定結果を整理しました。'))
    result.update(
        {
            'is_valid_previous_pdf': bool(parsed.get('is_valid_previous_pdf')),
            'confidence': str(parsed.get('confidence') or 'low'),
            'previous_reading_date': str(parsed.get('previous_reading_date') or ''),
            'previous_reading_date_original': str(parsed.get('previous_reading_date_original') or ''),
            'previous_reading_date_confidence': str(parsed.get('previous_reading_date_confidence') or 'low'),
            'detected_customer_name': str(parsed.get('detected_customer_name') or ''),
            'detected_sections': [str(x) for x in (parsed.get('detected_sections') or [])],
            'missing_sections': [str(x) for x in (parsed.get('missing_sections') or [])],
            'reason': str(parsed.get('reason') or ''),
        }
    )
    return add_review_pdf_date_deltas(result)


def call_gemini_review_pdf_analysis(uploaded_pdf_bytes: bytes) -> dict[str, Any]:
    current_reading_date = date.today()
    mime_type = 'application/pdf'
    pdf_size_bytes = len(uploaded_pdf_bytes)
    failed_step = 'build_contents'
    diagnostics_base = {
        'model_name': GEMINI_MODEL,
        'pdf_size_bytes': pdf_size_bytes,
        'mime_type': mime_type,
    }
    contents: list[Any] = [
        types.Part.from_bytes(data=uploaded_pdf_bytes, mime_type=mime_type),
        build_review_pdf_analysis_prompt(current_reading_date),
    ]

    logger.info('review_pdf_analysis_started', extra={'model': GEMINI_MODEL})
    try:
        failed_step = 'client_init'
        api_key = get_gemini_api_key()
        client = get_gemini_client(api_key)
        failed_step = 'generate_content'
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_json_schema=REVIEW_PDF_ANALYSIS_RESPONSE_JSON_SCHEMA,
                temperature=0.1,
            ),
        )
    except Exception as exc:
        diagnostics = {
            **diagnostics_base,
            'error_type': type(exc).__name__,
            'error_message_short': _safe_error_message(exc),
            'failed_step': failed_step,
        }
        logger.warning(
            'review_pdf_analysis_failed',
            extra={
                'error_type': diagnostics['error_type'],
                'failed_step': failed_step,
                'model_name': GEMINI_MODEL,
                'pdf_size_bytes': pdf_size_bytes,
                'mime_type': mime_type,
            },
        )
        return _empty_review_pdf_analysis(
            '前回PDFの確認中にエラーが発生しました。時間をおいて再度お試しください。',
            diagnostics,
        )

    failed_step = 'parse_response'
    result = parse_review_pdf_analysis_result(response.text or '')
    result['diagnostics'] = {
        **diagnostics_base,
        'failed_step': '',
        'error_type': '',
        'error_message_short': '',
    }
    logger.info(
        'review_pdf_analysis_completed',
        extra={
            'review_pdf_analysis_success': bool(result.get('is_valid_previous_pdf')),
            'previous_reading_date_found': bool(result.get('previous_reading_date')),
            'previous_reading_date_confidence': result.get('previous_reading_date_confidence'),
        },
    )
    return result



def call_gemini_fortune(data: FortuneInput) -> dict[str, Any]:
    api_key = get_gemini_api_key()
    client = get_gemini_client(api_key)
    contents: list[Any] = [build_user_prompt(data)]
    contents.extend(data.image_parts)

    logger.info('gemini_request_started', extra={'model': GEMINI_MODEL, 'image_count': data.image_count})
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(),
            response_mime_type='application/json',
            response_json_schema=FORTUNE_RESPONSE_JSON_SCHEMA,
            temperature=0.7,
        ),
    )

    raw_text = (response.text or '').strip()
    if not raw_text:
        raise ValueError('Gemini から鑑定結果が返ってきませんでした。')

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON の解析に失敗しました: {exc}') from exc

    if not isinstance(parsed, dict):
        raise ValueError('鑑定結果の形式が想定と異なります。')

    logger.info('gemini_request_completed')
    return normalize_fortune_result(parsed)
