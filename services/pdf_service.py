import datetime
import io
import os
import re
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from config import APP_TITLE, MIKO_IMAGE_PATH, PDF_FONT_PATHS
from services.formatter_service import normalize_fortune_result

REVIEW_PDF_TITLE = "龍神さまのお告げ 見返し便"
REVIEW_FORTUNE_SECTION_TITLES = [
    ("前回のお告げの振り返り", "intro"),
    ("前回のお告げと現在の状況との照らし合わせ", "theme_review"),
    ("これから3カ月ほど意識したいことや小さな行動", "next_3_months"),
    ("1年先に向けて整えていくこと", "one_year_guidance"),
    ("龍神さまからの見返しのことば", "ryujin_message"),
    ("巫女の助言", "miko_advice"),
    ("結び", "things_to_remember"),
]
REVIEW_FORTUNE_COMPARISON_FIELDS = [
    "theme",
    "previous_message",
    "current_status",
    "reinterpretation",
]


def register_japanese_font() -> str:
    for font_path in PDF_FONT_PATHS:
        if os.path.exists(font_path):
            font_name = os.path.splitext(os.path.basename(font_path))[0]
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            return font_name
    return "Helvetica"


def wrap_text_by_char_count(text: str, width: int = 34) -> list[str]:
    forbidden_line_start_chars = "、。，．）】』」〉》〕】"
    preferred_break_chars = "。、】【』」"
    short_tail_patterns = (
        "す。", "ます。", "した。", "です。", "でした。", "た。", "る。", "う。", "い。",
        "ますが、", "ですが、", "でしたが、", "ので、", "ため、", "でしょう。", "ました。",
        "こと。", "もの。", "けて", "えて", "める", "らか", "実に", "利に"
    )
    lines: list[str] = []

    def is_hiragana(ch: str) -> bool:
        return "ぁ" <= ch <= "ゖ"

    def is_kanji(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff"

    def looks_like_short_tail(fragment: str) -> bool:
        fragment = fragment.strip()
        if not fragment:
            return False
        if fragment in forbidden_line_start_chars:
            return True
        if len(fragment) <= 2:
            return True
        if len(fragment) <= 4 and fragment[-1] in forbidden_line_start_chars:
            return True
        return any(fragment.endswith(p) or fragment == p for p in short_tail_patterns)

    def bad_boundary(left: str, right: str) -> bool:
        if not left or not right:
            return False
        if right[0] in forbidden_line_start_chars:
            return True
        if len(right) >= 1 and is_kanji(right[0]) and (
            len(right) == 1 or (len(right) >= 2 and is_kanji(right[0]) and is_hiragana(right[1]))
        ):
            return True
        if len(right) >= 1 and is_hiragana(right[0]):
            head = right[:2]
            if len(right) <= 2 or all(is_hiragana(c) for c in head):
                return True
        if len(left) >= 1 and len(right) >= 1 and is_kanji(left[-1]) and is_hiragana(right[0]):
            return True
        for size in (2, 3, 4, 5):
            if len(right) >= size and right[:size] in short_tail_patterns:
                return True
        if len(left) >= 1 and len(right) >= 1:
            if is_hiragana(left[-1]) and is_hiragana(right[0]):
                return True
            if is_kanji(left[-1]) and len(right) >= 2 and all(is_hiragana(c) for c in right[:2]):
                return True
        return False

    def choose_break_pos(paragraph: str, start_pos: int, limit: int) -> int:
        end_pos = min(start_pos + limit, len(paragraph))
        if end_pos >= len(paragraph):
            return len(paragraph)
        window = paragraph[start_pos:end_pos]
        for i in range(len(window) - 1, max(-1, len(window) - 12), -1):
            if window[i] in preferred_break_chars:
                pos = start_pos + i + 1
                if not bad_boundary(paragraph[start_pos:pos], paragraph[pos:]):
                    return pos
        for i in range(len(window) - 1, max(-1, len(window) - 10), -1):
            if window[i] in "、，":
                pos = start_pos + i + 1
                if not bad_boundary(paragraph[start_pos:pos], paragraph[pos:]):
                    return pos
        candidate = end_pos
        for back in (0, 1, 2, 3):
            pos = candidate - back
            if pos <= start_pos + 1 or pos >= len(paragraph):
                continue
            if not bad_boundary(paragraph[start_pos:pos], paragraph[pos:]):
                return pos
        return end_pos

    def chunk_long_segment(segment: str, limit: int) -> list[str]:
        result: list[str] = []
        start_pos = 0
        while start_pos < len(segment):
            break_pos = choose_break_pos(segment, start_pos, limit)
            current = segment[start_pos:break_pos]
            while break_pos < len(segment) and segment[break_pos] in forbidden_line_start_chars and len(current) <= limit + 4:
                current += segment[break_pos]
                break_pos += 1
            remaining = segment[break_pos:]
            while remaining and looks_like_short_tail(remaining) and len(current) < limit + 3:
                current += remaining[0]
                break_pos += 1
                remaining = segment[break_pos:]
            result.append(current)
            start_pos = break_pos
        return result

    def split_into_segments(paragraph: str) -> list[str]:
        parts = re.findall(r".+?(?:[。、】【』」]|[、，]|$)", paragraph)
        return [p for p in (part.strip() for part in parts) if p]

    def rebalance_lines(paragraph_lines: list[str]) -> list[str]:
        if len(paragraph_lines) < 2:
            return paragraph_lines
        changed = True
        while changed and len(paragraph_lines) >= 2:
            changed = False
            for idx in range(1, len(paragraph_lines)):
                prev_line = paragraph_lines[idx - 1]
                curr_line = paragraph_lines[idx]
                if not curr_line:
                    continue
                while curr_line and curr_line[0] in forbidden_line_start_chars and len(prev_line) <= width + 4:
                    prev_line += curr_line[0]
                    curr_line = curr_line[1:]
                    changed = True
                for take in (6, 5, 4, 3, 2, 1):
                    if len(curr_line) >= take:
                        head = curr_line[:take]
                        if (looks_like_short_tail(head) or bad_boundary(prev_line, curr_line)) and len(prev_line) + len(head) <= width + 3:
                            prev_line += head
                            curr_line = curr_line[take:]
                            changed = True
                            break
                paragraph_lines[idx - 1] = prev_line
                paragraph_lines[idx] = curr_line
            paragraph_lines = [line for line in paragraph_lines if line != ""]
        if len(paragraph_lines) >= 2:
            last_line = paragraph_lines[-1]
            prev_line = paragraph_lines[-2]
            if looks_like_short_tail(last_line) and len(prev_line) + len(last_line) <= width + 4:
                paragraph_lines[-2] = prev_line + last_line
                paragraph_lines.pop()
        return paragraph_lines

    for paragraph in (text or "").split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        segments = split_into_segments(paragraph)
        paragraph_lines: list[str] = []
        current_line = ""
        for segment in segments:
            if len(segment) > width:
                if current_line:
                    paragraph_lines.append(current_line)
                    current_line = ""
                paragraph_lines.extend(chunk_long_segment(segment, width))
                continue
            if not current_line:
                current_line = segment
                continue
            if len(current_line) + len(segment) <= width:
                current_line += segment
            else:
                paragraph_lines.append(current_line)
                current_line = segment
        if current_line:
            paragraph_lines.append(current_line)
        paragraph_lines = rebalance_lines(paragraph_lines)
        lines.extend(paragraph_lines)
    return lines


def build_review_pdf_sections(review_fortune: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (title, str((review_fortune or {}).get(key) or "").strip())
        for title, key in REVIEW_FORTUNE_SECTION_TITLES
    ]


def _has_current_palm_images(review_context: dict[str, Any]) -> bool:
    context = (review_context or {}).get("review_context", {})
    current_inputs = context.get("current_inputs", {}) or {}
    try:
        return int(current_inputs.get("palm_image_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _current_changes_title(review_context: dict[str, Any]) -> str:
    if _has_current_palm_images(review_context):
        return "現在の手相と近況から見える変化"
    return "現在の近況から見える変化"


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _format_review_summary_points(review_fortune: dict[str, Any]) -> str:
    points = _clean_string_list((review_fortune or {}).get("review_summary_points"))
    if not points:
        return ""
    return "\n".join(f"・{point}" for point in points)


def _format_next_3_month_action_items(review_fortune: dict[str, Any]) -> str:
    items = _clean_string_list((review_fortune or {}).get("next_3_month_action_items"))
    if not items:
        return ""
    intro = "これから3カ月は、以下のような小さな行動を意識するとよさそうです。"
    return "\n".join([intro, "", *[f"・{item}" for item in items]])


def _format_comparison_blocks(review_fortune: dict[str, Any]) -> str:
    raw_blocks = (review_fortune or {}).get("comparison_blocks")
    if not isinstance(raw_blocks, list):
        return ""

    formatted_blocks: list[str] = []
    for raw_block in raw_blocks[:3]:
        if not isinstance(raw_block, dict):
            continue
        block = {
            field: str(raw_block.get(field) or "").strip()
            for field in REVIEW_FORTUNE_COMPARISON_FIELDS
        }
        if not any(block.values()):
            continue
        theme = block["theme"] or "見返しテーマ"
        body_parts = [
            block["previous_message"],
            block["current_status"],
            block["reinterpretation"],
        ]
        body = " ".join(part for part in body_parts if part)
        formatted_blocks.append("\n".join(part for part in [f"■ {theme}", body] if part))
    return "\n\n".join(formatted_blocks)


def _format_iso_date_japanese(value: str) -> str:
    try:
        parsed = datetime.datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return str(value or "")
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def generate_review_fortune_pdf(
    review_fortune: dict[str, Any],
    review_context: dict[str, Any],
) -> bytes:
    context = (review_context or {}).get("review_context", {})
    previous_pdf_analysis = context.get("previous_pdf_analysis", {}) or {}
    current_inputs = context.get("current_inputs", {}) or {}
    previous_reading_date = _format_iso_date_japanese(previous_pdf_analysis.get("previous_reading_date", ""))
    current_reading_date = _format_iso_date_japanese(previous_pdf_analysis.get("current_reading_date", ""))
    selected_theme = str(current_inputs.get("selected_theme") or "未選択")

    def join_parts(parts: list[str]) -> str:
        return "\n\n".join(part for part in (p.strip() for p in parts) if part)

    intro_text = str((review_fortune or {}).get("intro") or "").strip()
    reflection_text = intro_text or _format_review_summary_points(review_fortune)
    alignment_text = join_parts([
        _format_comparison_blocks(review_fortune),
        str((review_fortune or {}).get("current_changes") or ""),
        str((review_fortune or {}).get("theme_review") or ""),
    ])
    three_month_text = join_parts([
        str((review_fortune or {}).get("next_3_months") or ""),
        _format_next_3_month_action_items(review_fortune),
    ])
    closing_text = str((review_fortune or {}).get("things_to_remember") or "").strip()
    sections = [
        ("前回のお告げの振り返り", reflection_text),
        ("前回のお告げと現在の状況との照らし合わせ", alignment_text),
        ("これから3カ月ほど意識したいことや小さな行動", three_month_text),
        ("1年先に向けて整えていくこと", str((review_fortune or {}).get("one_year_guidance") or "").strip()),
        ("龍神さまからの見返しのことば", str((review_fortune or {}).get("ryujin_message") or "").strip()),
        ("巫女の助言", str((review_fortune or {}).get("miko_advice") or "").strip()),
        ("結び", closing_text),
    ]

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    font_name = register_japanese_font()
    page_num = 1

    def draw_page_base() -> None:
        c.setStrokeColor(HexColor("#8b0000"))
        c.setLineWidth(2)
        c.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm)
        c.setLineWidth(0.5)
        c.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)
        header_y = height - 24 * mm
        c.setStrokeColor(HexColor("#d8b6a9"))
        c.setLineWidth(0.8)
        c.line(18 * mm, header_y, width - 18 * mm, header_y)
        c.setFont(font_name, 11)
        c.setFillColor(HexColor("#8b0000"))
        c.drawString(22 * mm, height - 20.5 * mm, REVIEW_PDF_TITLE)
        if os.path.exists(MIKO_IMAGE_PATH):
            try:
                c.drawImage(
                    MIKO_IMAGE_PATH,
                    width - 36.5 * mm,
                    height - 22.0 * mm,
                    width=18 * mm,
                    height=18 * mm,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="ne",
                )
            except Exception:
                pass

    def new_page() -> None:
        nonlocal page_num, y
        c.showPage()
        page_num += 1
        draw_page_base()
        y = height - 31 * mm

    draw_page_base()

    c.setFont(font_name, 22)
    c.setFillColor(HexColor("#8b0000"))
    c.drawCentredString(width / 2, height - 40 * mm, REVIEW_PDF_TITLE)

    today = datetime.date.today()
    reiwa = today.year - 2018
    c.setFont(font_name, 11)
    c.setFillColor(HexColor("#000000"))
    c.drawRightString(width - 25 * mm, height - 52 * mm, f"令和 {reiwa}年 {today.month}月 {today.day}日")

    y = height - 68 * mm
    line_h = 7.2 * mm
    c.setFont(font_name, 12)
    for label, value in [
        ("前回のお告げ", previous_reading_date),
        ("今回の見返し", current_reading_date),
        ("見返しテーマ", selected_theme),
    ]:
        if value:
            c.drawString(30 * mm, y, f"{label}：{value}")
            y -= line_h

    y -= 6 * mm

    def add_section(title: str, text: str) -> None:
        nonlocal y
        if not text:
            return
        wrapped_lines = wrap_text_by_char_count(text, width=33)
        min_needed_lines = min(max(len(wrapped_lines), 1), 3)
        min_needed = line_h * (1 + min_needed_lines) + 5 * mm
        if y < 22 * mm + min_needed:
            new_page()

        c.setFont(font_name, 14)
        c.setFillColor(HexColor("#8b0000"))
        c.drawString(25 * mm, y, f"【{title}】")
        y -= line_h

        c.setFont(font_name, 11)
        c.setFillColor(HexColor("#000000"))
        for i, line in enumerate(wrapped_lines):
            remaining_lines = len(wrapped_lines) - i
            if y < 22 * mm + (line_h * min(remaining_lines, 2)):
                new_page()
                c.setFont(font_name, 11)
                c.setFillColor(HexColor("#000000"))
            if line == "":
                y -= line_h * 0.7
                continue
            c.drawString(30 * mm, y, line)
            y -= line_h
        y -= 3 * mm

    for title, text in sections:
        add_section(title, text)

    if not closing_text:
        add_section("結び", "ここに記した見返しの言葉が、これからの日々を静かに整える手がかりとなりますように。")

    c.setFont(font_name, 10)
    c.setFillColor(HexColor("#000000"))
    c.drawRightString(width - 25 * mm, 18 * mm, "龍神湖神社 巫女 拝")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_miko_letter_pdf(user_name: str, fortune_data: dict[str, Any]) -> bytes:
    data = normalize_fortune_result(fortune_data or {})

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    font_name = register_japanese_font()

    def draw_page_base(page_num: int) -> None:
        c.setStrokeColor(HexColor("#8b0000"))
        c.setLineWidth(2)
        c.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm)
        c.setLineWidth(0.5)
        c.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)

        header_y = height - 24 * mm
        c.setStrokeColor(HexColor("#d8b6a9"))
        c.setLineWidth(0.8)
        c.line(18 * mm, header_y, width - 18 * mm, header_y)

        # タイトルを少し下げて罫線に近づける
        c.setFont(font_name, 11)
        c.setFillColor(HexColor("#8b0000"))
        c.drawString(22 * mm, height - 20.5 * mm, APP_TITLE or "龍神さまのお告げ")

        # 画像を約150%に拡大し、飾り罫から少しはみ出す配置
        if os.path.exists(MIKO_IMAGE_PATH):
            try:
                c.drawImage(
                    MIKO_IMAGE_PATH,
                    width - 36.5 * mm,
                    height - 22.0 * mm,
                    width=18 * mm,
                    height=18 * mm,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="ne",
                )
            except Exception:
                pass

    page_num = 1

    def new_page() -> None:
        nonlocal page_num
        c.showPage()
        page_num += 1
        draw_page_base(page_num)

    draw_page_base(page_num)

    c.setFont(font_name, 24)
    c.setFillColor(HexColor("#8b0000"))
    c.drawCentredString(width / 2, height - 36 * mm, "龍神さまの鑑定書")

    today = datetime.date.today()
    reiwa = today.year - 2018
    c.setFont(font_name, 12)
    c.setFillColor(HexColor("#000000"))
    c.drawString(25 * mm, height - 50 * mm, f"{user_name} 様")
    c.drawRightString(width - 25 * mm, height - 50 * mm, f"令和 {reiwa}年 {today.month}月 {today.day}日")

    y = height - 66 * mm
    line_h = 7.2 * mm

    def add_section(title: str, text: str, title_color: str = "#8b0000") -> None:
        nonlocal y
        if not text:
            return

        wrapped_lines = wrap_text_by_char_count(text)
        min_needed_lines = min(max(len(wrapped_lines), 1), 3)
        min_needed = line_h * (1 + min_needed_lines) + 5 * mm
        if y < 22 * mm + min_needed:
            new_page()
            y = height - 31 * mm

        c.setFont(font_name, 14)
        c.setFillColor(HexColor(title_color))
        c.drawString(25 * mm, y, f"【{title}】")
        y -= line_h

        c.setFont(font_name, 11)
        c.setFillColor(HexColor("#000000"))

        for i, line in enumerate(wrapped_lines):
            remaining_lines = len(wrapped_lines) - i
            if y < 22 * mm + (line_h * min(remaining_lines, 2)):
                new_page()
                y = height - 31 * mm
                c.setFont(font_name, 11)
                c.setFillColor(HexColor("#000000"))
            if line == "":
                y -= line_h * 0.7
                continue
            c.drawString(30 * mm, y, line)
            y -= line_h

        y -= 3 * mm

    add_section("龍神さまよりの挨拶", data.get("miko_intro", ""))
    add_section("鑑定のまとめ", data.get("method_summary", ""))
    add_section("手相の導き", data.get("palm_details", ""))
    add_section("姓名判断", data.get("name_reading", ""))
    add_section("四柱推命", data.get("shichusuimei", ""))
    add_section("西洋占星術", data.get("western_astrology", ""))
    add_section("直近：これから3カ月以内の運勢", data.get("fortune_3months", ""))
    add_section("展望：これから1年先の運勢", data.get("fortune_1year", ""))
    add_section("未来：2〜3年後の運勢", data.get("fortune_3years", ""))

    advice = data.get("advice", {}) or {}
    advice_text = "\n".join([
        f"・開運アイテム: {advice.get('item', '')}",
        f"・開運スポット: {advice.get('spot', '')}",
        f"・開運カラー: {advice.get('color', '')}",
        f"・運気を上げる行動: {advice.get('luck_action', '')}",
    ])
    add_section("巫女の助言", advice_text)

    cautions = data.get("cautions", []) or []
    caution_text = "\n".join([f"・{c}" for c in cautions])
    add_section("心に留めること", caution_text)
    add_section("結び", data.get("miko_closing", ""))

    c.setFont(font_name, 10)
    c.setFillColor(HexColor("#000000"))
    c.drawRightString(width - 25 * mm, 18 * mm, "龍神湖神社 巫女 拝")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()
