import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pypdf import PdfReader

logger = logging.getLogger(__name__)

REGULAR_REQUIRED_SECTIONS = [
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

REGULAR_DIVINATION_SECTIONS = ['手相の導き', '姓名判断', '四柱推命', '西洋占星術']
REGULAR_TIMELINE_SECTIONS = ['直近：これから3カ月以内の運勢', '展望：これから1年先の運勢', '未来：2〜3年後の運勢']

REVIEW_CURRENT_SECTIONS = [
    '前回のお告げの振り返り',
    '前回のお告げと現在の状況との照らし合わせ',
    'これから3カ月ほど意識したいことや小さな行動',
    '1年先に向けて整えていくこと',
    '龍神さまからの見返しのことば',
    '巫女の助言',
    '結び',
]

REVIEW_ALIAS_SECTIONS = [
    'はじめに',
    '前回のお告げ',
    '今回の見返し',
    '見返しテーマ',
    '前回のお告げの振り返り',
    '前回のお告げから続いている流れ',
    '現在の手相と近況から見える変化',
    '現在の近況から見える変化',
    '今回のテーマについての見返し',
    '今回の見返しポイント',
    '前回のお告げと現在の照らし合わせ',
    '前回のお告げと現在の状況との照らし合わせ',
    'これから3カ月ほど意識したいことや小さな行動',
    'これから3カ月の小さな行動',
    '1年先に向けて整えていくこと',
    '龍神さまからの見返しのことば',
    '心に留めること',
]

BRAND_TEXT = '龍神さまのお告げ'
REGULAR_TITLE = '龍神さまの鑑定書'
REVIEW_TITLE = '龍神さまのお告げ 見返し便'
FOOTER_TEXT = '龍神湖神社 巫女 拝'


@dataclass
class ExtractedPdfText:
    text: str
    page_count: int
    encrypted: bool
    readable_pages: int
    extraction_method: str


def _decode_utf16_hex(hex_text: str) -> str:
    raw = bytes.fromhex(hex_text)
    if len(raw) % 2:
        raw = b'\x00' + raw
    return raw.decode('utf-16-be', errors='ignore')


def _parse_tounicode_cmap(raw_cmap: bytes) -> dict[bytes, str]:
    text = raw_cmap.decode('latin1', errors='ignore')
    mapping: dict[bytes, str] = {}

    for source, target in re.findall(r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>', text):
        try:
            mapping[bytes.fromhex(source)] = _decode_utf16_hex(target)
        except ValueError:
            continue

    return mapping


def _font_cmaps(page: Any) -> dict[str, dict[bytes, str]]:
    cmaps: dict[str, dict[bytes, str]] = {}
    resources = page.get('/Resources') or {}
    fonts = resources.get('/Font') or {}
    for raw_name, raw_font in fonts.items():
        font = raw_font.get_object()
        cmap_ref = font.get('/ToUnicode')
        if not cmap_ref:
            continue
        try:
            cmaps[str(raw_name)] = _parse_tounicode_cmap(cmap_ref.get_object().get_data())
        except Exception:
            continue
    return cmaps


def _read_pdf_literal(content: bytes, start: int) -> tuple[bytes, int]:
    result = bytearray()
    index = start + 1
    depth = 1
    while index < len(content) and depth > 0:
        char = content[index]
        if char == 0x5C:
            index += 1
            if index >= len(content):
                break
            escaped = content[index]
            if 0x30 <= escaped <= 0x37:
                octal = bytes([escaped])
                for _ in range(2):
                    if index + 1 < len(content) and 0x30 <= content[index + 1] <= 0x37:
                        index += 1
                        octal += bytes([content[index]])
                    else:
                        break
                result.append(int(octal, 8))
            else:
                replacements = {
                    ord('n'): b'\n',
                    ord('r'): b'\r',
                    ord('t'): b'\t',
                    ord('b'): b'\b',
                    ord('f'): b'\f',
                    ord('('): b'(',
                    ord(')'): b')',
                    ord('\\'): b'\\',
                }
                result.extend(replacements.get(escaped, bytes([escaped])))
        elif char == 0x28:
            depth += 1
            result.append(char)
        elif char == 0x29:
            depth -= 1
            if depth:
                result.append(char)
        else:
            result.append(char)
        index += 1
    return bytes(result), index


def _decode_pdf_string(raw: bytes, cmap: dict[bytes, str] | None) -> str:
    if not raw:
        return ''
    if not cmap:
        return raw.decode('latin1', errors='ignore')

    code_lengths = sorted({len(code) for code in cmap}, reverse=True)
    index = 0
    chars: list[str] = []
    while index < len(raw):
        matched = False
        for code_length in code_lengths:
            code = raw[index:index + code_length]
            if code in cmap:
                chars.append(cmap[code])
                index += code_length
                matched = True
                break
        if not matched:
            chars.append(bytes([raw[index]]).decode('latin1', errors='ignore'))
            index += 1
    return ''.join(chars)


def _extract_page_text_from_content(content: bytes, cmaps: dict[str, dict[bytes, str]]) -> str:
    parts: list[str] = []
    current_font = ''
    index = 0
    while index < len(content):
        if content[index:index + 1] == b'/':
            match = re.match(rb'/([A-Za-z0-9+\-]+)\s+[-+]?\d+(?:\.\d+)?\s+Tf', content[index:index + 80])
            if match:
                current_font = '/' + match.group(1).decode('latin1', errors='ignore')
                index += match.end()
                continue
        if content[index:index + 1] == b'(':
            literal, end_index = _read_pdf_literal(content, index)
            tail = content[end_index:end_index + 16]
            if re.match(rb'\s*Tj', tail):
                decoded = _decode_pdf_string(literal, cmaps.get(current_font))
                if decoded:
                    parts.append(decoded)
            index = end_index
            continue
        index += 1
    return '\n'.join(parts)


def extract_reportlab_pdf_text(pdf_bytes: bytes) -> ExtractedPdfText:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted:
        return ExtractedPdfText('', len(reader.pages), True, 0, 'pypdf_tounicode_cmap')

    page_texts: list[str] = []
    readable_pages = 0
    for page in reader.pages:
        try:
            content = page.get_contents().get_data()
            text = _extract_page_text_from_content(content, _font_cmaps(page))
        except Exception:
            text = ''
        if text.strip():
            readable_pages += 1
        page_texts.append(text)
    return ExtractedPdfText('\n'.join(page_texts), len(reader.pages), False, readable_pages, 'pypdf_tounicode_cmap')


def _normalize_pdf_text(text: str) -> str:
    normalized = re.sub(r'[ \t\u3000]+', ' ', text or '')
    return normalized.replace('：', ':')


def _contains_any(text: str, values: list[str]) -> bool:
    return any(value.replace('：', ':') in text for value in values)


def _detected(values: list[str], text: str) -> list[str]:
    return [value for value in values if value.replace('：', ':') in text]


def _normalize_date_match(match: re.Match[str]) -> tuple[str, str]:
    original = match.group(0)
    try:
        if original.startswith('令和'):
            era_year = 1 if match.group(1) == '元' else int(match.group(1))
            parsed = date(2018 + era_year, int(match.group(2)), int(match.group(3)))
        else:
            parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return '', ''
    return parsed.isoformat(), original


def _extract_reading_date(text: str) -> tuple[str, str]:
    patterns = [
        r'令和\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日',
        r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日',
        r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parsed, original = _normalize_date_match(match)
        if parsed:
            return parsed, original
    return '', ''


def _extract_review_previous_reading_date(text: str) -> tuple[str, str]:
    date_pattern = (
        r'(?:令和\s*(?:元|\d{1,2})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|'
        r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|'
        r'20\d{2}[-/]\d{1,2}[-/]\d{1,2})'
    )
    for label in ['前回のお告げ', '前回鑑定日']:
        match = re.search(rf'{label}\s*[:：]\s*({date_pattern})', text)
        if match:
            return _extract_reading_date(match.group(1))
    return '', ''


def _with_date_deltas(result: dict[str, Any], current_reading_date: date | None = None) -> dict[str, Any]:
    current_date = current_reading_date or date.today()
    result['current_reading_date'] = current_date.isoformat()
    previous_date_text = str(result.get('previous_reading_date') or '')
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


def _analysis_result(
    *,
    accepted: bool,
    confidence: str,
    reason: str,
    validation_method: str,
    previous_reading_date: str = '',
    previous_reading_date_original: str = '',
    detected_sections: list[str] | None = None,
    missing_sections: list[str] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        'is_valid_previous_pdf': accepted,
        'confidence': confidence,
        'previous_reading_date': previous_reading_date,
        'previous_reading_date_original': previous_reading_date_original,
        'previous_reading_date_confidence': 'high' if previous_reading_date else 'low',
        'detected_customer_name': '',
        'detected_sections': detected_sections or [],
        'missing_sections': missing_sections or [],
        'reason': reason,
        'validation_method': validation_method,
    }
    if diagnostics:
        result['diagnostics'] = diagnostics
    return _with_date_deltas(result)


def validate_review_pdf_deterministic(pdf_bytes: bytes) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        'validation_method': 'deterministic_structural',
        'pdf_size_bytes': len(pdf_bytes),
    }
    if not pdf_bytes.startswith(b'%PDF'):
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='PDFヘッダーを確認できませんでした。',
            validation_method='deterministic_reject',
            diagnostics={**diagnostics, 'failed_step': 'pdf_header'},
        )

    try:
        extracted = extract_reportlab_pdf_text(pdf_bytes)
    except Exception as exc:
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='PDFを読み取れませんでした。',
            validation_method='deterministic_reject',
            diagnostics={**diagnostics, 'failed_step': 'pdf_read', 'error_type': type(exc).__name__},
        )

    diagnostics.update(
        {
            'page_count': extracted.page_count,
            'readable_pages': extracted.readable_pages,
            'encrypted': extracted.encrypted,
            'text_extraction_method': extracted.extraction_method,
        }
    )
    if extracted.encrypted:
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='暗号化されたPDFは前回鑑定PDFとして確認できません。',
            validation_method='deterministic_reject',
            diagnostics={**diagnostics, 'failed_step': 'encrypted_pdf'},
        )
    if extracted.page_count < 1 or extracted.readable_pages < 1:
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='PDF本文を読み取れませんでした。',
            validation_method='deterministic_reject',
            diagnostics={**diagnostics, 'failed_step': 'text_extraction'},
        )

    text = _normalize_pdf_text(extracted.text)
    first_date, first_date_original = _extract_reading_date(text)
    has_brand = BRAND_TEXT in text
    has_footer = FOOTER_TEXT in text
    has_regular_title = REGULAR_TITLE in text
    has_review_title = REVIEW_TITLE in text

    regular_divinations = _detected(REGULAR_DIVINATION_SECTIONS, text)
    regular_timelines = _detected(REGULAR_TIMELINE_SECTIONS, text)
    regular_detected = _detected(REGULAR_REQUIRED_SECTIONS, text)
    review_aliases = _detected(REVIEW_ALIAS_SECTIONS, text)
    review_detected = _detected(REVIEW_CURRENT_SECTIONS, text)

    diagnostics.update(
        {
            'has_brand': has_brand,
            'has_footer': has_footer,
            'has_reading_date': bool(first_date),
            'has_regular_title': has_regular_title,
            'has_review_title': has_review_title,
            'regular_divination_section_count': len(regular_divinations),
            'regular_timeline_section_count': len(regular_timelines),
            'review_alias_section_count': len(review_aliases),
        }
    )

    if has_brand and first_date and has_footer and has_regular_title and len(regular_divinations) >= 3 and len(regular_timelines) >= 2 and _contains_any(text, ['巫女の助言']) and _contains_any(text, ['結び', '鑑定のまとめ']):
        return _analysis_result(
            accepted=True,
            confidence='high',
            reason='通常版PDFのブランド、日付、フッター、占術章、時期運章を確認しました。',
            validation_method='deterministic_regular',
            previous_reading_date=first_date,
            previous_reading_date_original=first_date_original,
            detected_sections=regular_detected,
            missing_sections=[section for section in REGULAR_REQUIRED_SECTIONS if section not in regular_detected],
            diagnostics=diagnostics,
        )

    review_previous_date, review_previous_date_original = _extract_review_previous_reading_date(text)
    review_result_date = review_previous_date or first_date
    review_result_date_original = review_previous_date_original or first_date_original
    if has_brand and first_date and has_footer and has_review_title and len(review_aliases) >= 3 and _contains_any(text, ['巫女の助言', '結び']):
        return _analysis_result(
            accepted=True,
            confidence='high',
            reason='見返し便PDFのブランド、日付、フッター、見返し系章群を確認しました。',
            validation_method='deterministic_review',
            previous_reading_date=review_result_date,
            previous_reading_date_original=review_result_date_original,
            detected_sections=list(dict.fromkeys([*review_detected, *review_aliases])),
            missing_sections=[section for section in REVIEW_CURRENT_SECTIONS if section not in review_detected],
            diagnostics=diagnostics,
        )

    if not has_brand or not first_date or not has_footer:
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='正規PDFとして必要なブランド、鑑定日、フッターの組み合わせを確認できませんでした。',
            validation_method='deterministic_reject',
            previous_reading_date=first_date,
            previous_reading_date_original=first_date_original,
            detected_sections=list(dict.fromkeys([*regular_detected, *review_detected, *review_aliases])),
            missing_sections=[],
            diagnostics={**diagnostics, 'failed_step': 'required_structure'},
        )

    if (has_regular_title or has_review_title) and not regular_divinations and len(review_aliases) < 2:
        return _analysis_result(
            accepted=False,
            confidence='high',
            reason='タイトルは確認できましたが、正規PDFとして必要な章構造を確認できませんでした。',
            validation_method='deterministic_reject',
            previous_reading_date=review_result_date,
            previous_reading_date_original=review_result_date_original,
            detected_sections=list(dict.fromkeys([*regular_detected, *review_detected, *review_aliases])),
            missing_sections=[],
            diagnostics={**diagnostics, 'failed_step': 'title_only'},
        )

    return _analysis_result(
        accepted=False,
        confidence='low',
        reason='deterministic判定だけでは正規PDFか断定できないためGeminiで確認します。',
        validation_method='gemini_fallback',
        previous_reading_date=review_result_date,
        previous_reading_date_original=review_result_date_original,
        detected_sections=list(dict.fromkeys([*regular_detected, *review_detected, *review_aliases])),
        missing_sections=[],
        diagnostics=diagnostics,
    )
