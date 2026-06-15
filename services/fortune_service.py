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

REVIEW_PDF_SUMMARY_RESPONSE_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'previous_summary': {
            'type': 'object',
            'properties': {
                'overall_tone': {'type': 'string'},
                'core_message': {'type': 'string'},
                'palm_reading_summary': {'type': 'string'},
                'name_reading_summary': {'type': 'string'},
                'shichu_suimei_summary': {'type': 'string'},
                'western_astrology_summary': {'type': 'string'},
                'recent_3_months': {'type': 'string'},
                'one_year': {'type': 'string'},
                'two_to_three_years': {'type': 'string'},
                'miko_advice': {'type': 'string'},
                'lucky_items': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'lucky_places': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'lucky_colors': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'important_phrases': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
            },
            'required': [
                'overall_tone',
                'core_message',
                'palm_reading_summary',
                'name_reading_summary',
                'shichu_suimei_summary',
                'western_astrology_summary',
                'recent_3_months',
                'one_year',
                'two_to_three_years',
                'miko_advice',
                'lucky_items',
                'lucky_places',
                'lucky_colors',
                'important_phrases',
            ],
        },
    },
    'required': ['previous_summary'],
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

REVIEW_SUMMARY_TEXT_FIELDS = [
    'overall_tone',
    'core_message',
    'palm_reading_summary',
    'name_reading_summary',
    'shichu_suimei_summary',
    'western_astrology_summary',
    'recent_3_months',
    'one_year',
    'two_to_three_years',
    'miko_advice',
]

REVIEW_SUMMARY_LIST_FIELDS = [
    'lucky_items',
    'lucky_places',
    'lucky_colors',
    'important_phrases',
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


def build_review_pdf_summary_prompt(
    pdf_analysis: dict[str, Any],
    current_reading_date: date | None = None,
) -> str:
    current_date = current_reading_date or date.today()
    previous_reading_date = str(pdf_analysis.get('previous_reading_date') or '')
    days_since_previous = pdf_analysis.get('days_since_previous_reading')
    months_since_previous = pdf_analysis.get('months_since_previous_reading')
    return f"""
アップロードされた前回鑑定PDFを、見返し便の次フェーズで使うために構造化要約してください。

今回鑑定日: {current_date.isoformat()}
前回鑑定日: {previous_reading_date}
前回鑑定日からの経過日数: {days_since_previous}
前回鑑定日からの経過月数: {months_since_previous}

必ずJSONのみで返してください。PDF本文の長い引用や丸写しは避け、各項目は短い要約にしてください。

抽出・要約する項目:
- 全体の雰囲気
- 核となるお告げ
- 手相の導き
- 姓名判断
- 四柱推命
- 西洋占星術
- 直近：これから3カ月以内の運勢
- 展望：これから1年先の運勢
- 未来：2〜3年後の運勢
- 巫女の助言
- 開運アイテム
- 開運スポット
- 開運カラー
- 心に留めたい短い言葉

整理方針:
- 前回のお告げを「当たり」「外れ」と評価しない。
- 前回のお告げと現在の近況が重なる点、違う流れになっている点、今も続くテーマ、今後に持ち越される流れとして後で読み直しやすい要約にする。
- 姓名判断や生年月日由来の本質的傾向は、前回から大きく変わるものとして扱わない。
- 時期運は、今回時点で再解釈される前提の素材として要約する。
- 手相は、今回の現在手相と比較するための前回時点の手がかりとして要約する。
- 氏名や生年月日など、個人を直接特定する情報は要約に含めない。

期待するJSON構造:
{{
  "previous_summary": {{
    "overall_tone": "",
    "core_message": "",
    "palm_reading_summary": "",
    "name_reading_summary": "",
    "shichu_suimei_summary": "",
    "western_astrology_summary": "",
    "recent_3_months": "",
    "one_year": "",
    "two_to_three_years": "",
    "miko_advice": "",
    "lucky_items": [],
    "lucky_places": [],
    "lucky_colors": [],
    "important_phrases": []
  }}
}}
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


def _empty_previous_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {field: '' for field in REVIEW_SUMMARY_TEXT_FIELDS}
    summary.update({field: [] for field in REVIEW_SUMMARY_LIST_FIELDS})
    return summary


def _empty_review_pdf_summary(
    reason: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        'summary_success': False,
        'previous_summary': _empty_previous_summary(),
        'reason': reason,
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


def parse_review_pdf_summary_result(raw_text: str) -> dict[str, Any]:
    text = (raw_text or '').strip()
    if not text:
        return _empty_review_pdf_summary('Geminiから前回PDF要約結果が返ってきませんでした。')

    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _empty_review_pdf_summary('Geminiの前回PDF要約結果をJSONとして解析できませんでした。')

    if not isinstance(parsed, dict):
        return _empty_review_pdf_summary('Geminiの前回PDF要約結果の形式が想定と異なります。')

    raw_summary = parsed.get('previous_summary')
    if not isinstance(raw_summary, dict):
        return _empty_review_pdf_summary('Geminiの前回PDF要約に previous_summary が含まれていません。')

    summary = _empty_previous_summary()
    for field in REVIEW_SUMMARY_TEXT_FIELDS:
        summary[field] = str(raw_summary.get(field) or '').strip()
    for field in REVIEW_SUMMARY_LIST_FIELDS:
        values = raw_summary.get(field) or []
        if isinstance(values, list):
            summary[field] = [str(value).strip() for value in values if str(value).strip()]
        else:
            summary[field] = []

    return {
        'summary_success': True,
        'previous_summary': summary,
        'reason': '前回PDF要約を整理しました。',
    }


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


def call_gemini_review_pdf_summary(
    uploaded_pdf_bytes: bytes,
    pdf_analysis: dict[str, Any],
) -> dict[str, Any]:
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
        build_review_pdf_summary_prompt(pdf_analysis, current_reading_date),
    ]

    logger.info('review_pdf_summary_started', extra={'model': GEMINI_MODEL})
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
                response_json_schema=REVIEW_PDF_SUMMARY_RESPONSE_JSON_SCHEMA,
                temperature=0.2,
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
            'review_pdf_summary_failed',
            extra={
                'error_type': diagnostics['error_type'],
                'failed_step': failed_step,
                'model_name': GEMINI_MODEL,
                'pdf_size_bytes': pdf_size_bytes,
                'mime_type': mime_type,
            },
        )
        return _empty_review_pdf_summary(
            '前回PDFの要約中にエラーが発生しました。時間をおいてもう一度お試しください。',
            diagnostics,
        )

    failed_step = 'parse_response'
    result = parse_review_pdf_summary_result(response.text or '')
    result['diagnostics'] = {
        **diagnostics_base,
        'failed_step': '' if result.get('summary_success') else failed_step,
        'error_type': '',
        'error_message_short': '',
    }
    logger.info(
        'review_pdf_summary_completed',
        extra={
            'review_pdf_summary_success': bool(result.get('summary_success')),
            'model_name': GEMINI_MODEL,
            'pdf_size_bytes': pdf_size_bytes,
            'mime_type': mime_type,
        },
    )
    return result


def build_timeline_reinterpretation(pdf_analysis: dict[str, Any]) -> dict[str, Any]:
    months_value = pdf_analysis.get('months_since_previous_reading')
    days_value = pdf_analysis.get('days_since_previous_reading')
    try:
        months_since_previous = int(months_value)
    except (TypeError, ValueError):
        months_since_previous = None
    try:
        days_since_previous = int(days_value)
    except (TypeError, ValueError):
        days_since_previous = None

    if days_since_previous is not None and days_since_previous < 0:
        return {
            'months_since_previous_reading': months_since_previous,
            'recent_3_months_status': 'future',
            'one_year_status': 'future',
            'two_to_three_years_status': 'future',
            'note': '前回鑑定日が今回鑑定日より後の日付として読み取られたため、時間軸の確認が必要です。',
        }

    if months_since_previous is None:
        return {
            'months_since_previous_reading': None,
            'recent_3_months_status': 'unknown',
            'one_year_status': 'unknown',
            'two_to_three_years_status': 'unknown',
            'note': '前回鑑定日からの経過月数を確認できないため、時間軸は未分類として扱います。',
        }

    recent_status = 'past' if months_since_previous >= 3 else 'in_progress'
    one_year_status = 'past' if months_since_previous >= 12 else 'in_progress'
    long_term_status = 'past' if months_since_previous >= 36 else 'long_term'

    if months_since_previous < 1:
        note = '前回鑑定からまだ1カ月未満のため、直近3カ月の流れは進行中として扱います。'
    elif months_since_previous < 3:
        note = '前回鑑定から3カ月未満のため、直近3カ月の流れは進行中として扱います。'
    elif months_since_previous < 12:
        note = '前回鑑定から3カ月以上経過しているため、直近3カ月の流れは主に振り返り対象として扱います。'
    elif months_since_previous < 36:
        note = '前回鑑定から1年以上経過しているため、1年先までの流れは振り返り対象とし、2〜3年後の流れは長期テーマとして扱います。'
    else:
        note = '前回鑑定から3年以上経過しているため、2〜3年後の流れも振り返り対象に近いものとして扱います。'

    return {
        'months_since_previous_reading': months_since_previous,
        'recent_3_months_status': recent_status,
        'one_year_status': one_year_status,
        'two_to_three_years_status': long_term_status,
        'note': note,
    }


def build_review_context(
    pdf_analysis: dict[str, Any],
    previous_summary: dict[str, Any],
    current_inputs: dict[str, Any],
) -> dict[str, Any]:
    safe_pdf_analysis = {
        'is_valid_previous_pdf': bool(pdf_analysis.get('is_valid_previous_pdf')),
        'confidence': str(pdf_analysis.get('confidence') or ''),
        'previous_reading_date': str(pdf_analysis.get('previous_reading_date') or ''),
        'previous_reading_date_original': str(pdf_analysis.get('previous_reading_date_original') or ''),
        'previous_reading_date_confidence': str(pdf_analysis.get('previous_reading_date_confidence') or ''),
        'detected_sections': [str(x) for x in (pdf_analysis.get('detected_sections') or [])],
        'missing_sections': [str(x) for x in (pdf_analysis.get('missing_sections') or [])],
        'current_reading_date': str(pdf_analysis.get('current_reading_date') or ''),
        'days_since_previous_reading': pdf_analysis.get('days_since_previous_reading'),
        'months_since_previous_reading': pdf_analysis.get('months_since_previous_reading'),
    }
    safe_current_inputs = {
        'birth_time_text': str(current_inputs.get('birth_time_text') or ''),
        'selected_theme': str(current_inputs.get('selected_theme') or ''),
        'review_memo_present': bool(current_inputs.get('review_memo_present')),
        'palm_image_count': int(current_inputs.get('palm_image_count') or 0),
    }
    return {
        'review_context': {
            'previous_pdf_analysis': safe_pdf_analysis,
            'previous_summary': previous_summary,
            'timeline_reinterpretation': build_timeline_reinterpretation(pdf_analysis),
            'current_inputs': safe_current_inputs,
        }
    }



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
