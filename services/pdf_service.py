import io
import os
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import APP_TITLE, MIKO_IMAGE_PATH


ACCENT = colors.HexColor("#8A3D24")
TEXT = colors.HexColor("#222222")
MUTED = colors.HexColor("#666666")
BOX_BG = colors.HexColor("#FFF8F5")
BOX_BORDER = colors.HexColor("#E4C6B9")


def _register_fonts() -> tuple[str, str]:
    regular = "HeiseiMin-W3"
    bold = "HeiseiKakuGo-W5"
    try:
        registerFont(UnicodeCIDFont(regular))
    except Exception:
        pass
    try:
        registerFont(UnicodeCIDFont(bold))
    except Exception:
        pass
    return regular, bold


def _build_styles(font_name: str, bold_name: str) -> StyleSheet1:
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="MikoTitle",
            fontName=bold_name,
            fontSize=19,
            leading=24,
            textColor=ACCENT,
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MikoMeta",
            fontName=font_name,
            fontSize=10,
            leading=15,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=3 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontName=bold_name,
            fontSize=12.5,
            leading=17,
            textColor=ACCENT,
            spaceAfter=2.8 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyJP",
            fontName=font_name,
            fontSize=10.5,
            leading=18,
            textColor=TEXT,
            spaceAfter=1.6 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="NoteJP",
            fontName=font_name,
            fontSize=9.3,
            leading=14.5,
            textColor=MUTED,
            spaceAfter=1.6 * mm,
        )
    )
    return styles


def _escape_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _box(title: str, body: str, styles: StyleSheet1) -> Table:
    title_para = Paragraph(_escape_text(title), styles["SectionHeading"])
    body_para = Paragraph(_escape_text(body) or " ", styles["BodyJP"])
    table = Table([[title_para], [body_para]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BOX_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, BOX_BORDER),
                ("ROUNDEDCORNERS", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ]
        )
    )
    return table


def _advice_text(advice: dict[str, Any]) -> str:
    if not advice:
        return ""
    parts = [
        f"開運アイテム: {advice.get('item', '')}",
        f"開運スポット: {advice.get('spot', '')}",
        f"開運カラー: {advice.get('color', '')}",
        f"運気を上げる行動: {advice.get('luck_action', '')}",
    ]
    return "\n\n".join(parts)


def _build_story(user_name: str, data: dict[str, Any], styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []

    display_name = (user_name or "").strip() or "ご依頼者さま"
    today_str = date.today().strftime("%Y年%m月%d日")

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("巫女からの手紙", styles["MikoTitle"]))
    story.append(Paragraph(f"{_escape_text(display_name)} さま", styles["MikoMeta"]))
    story.append(Paragraph(today_str, styles["MikoMeta"]))
    story.append(Spacer(1, 3 * mm))

    story.append(
        Paragraph(
            "本鑑定書は参考情報としてお楽しみいただくためのものです。"
            "医療・法律・投資などの重要な判断には利用せず、必要に応じて専門家へご相談ください。",
            styles["NoteJP"],
        )
    )
    story.append(Spacer(1, 2 * mm))

    sections = [
        ("龍神さまよりの挨拶", data.get("miko_intro", "")),
        ("今回の鑑定のまとめ", data.get("method_summary", "")),
    ]
    for title, body in sections:
        story.append(_box(title, body, styles))
        story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("各占術から見た流れ", styles["SectionHeading"]))
    story.append(Spacer(1, 1.5 * mm))

    detail_sections = [
        ("手相術", data.get("palm_details", "")),
        ("姓名判断", data.get("name_reading", "")),
        ("四柱推命", data.get("shichusuimei", "")),
        ("西洋占星術", data.get("western_astrology", "")),
    ]
    for title, body in detail_sections:
        story.append(_box(title, body, styles))
        story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("時の波", styles["SectionHeading"]))
    story.append(Spacer(1, 1.5 * mm))

    future_sections = [
        ("直近：これから3カ月以内の運勢", data.get("fortune_3months", "")),
        ("展望：これから1年先の運勢", data.get("fortune_1year", "")),
        ("未来：2〜3年後の運勢", data.get("fortune_3years", "")),
    ]
    for title, body in future_sections:
        story.append(_box(title, body, styles))
        story.append(Spacer(1, 4 * mm))

    advice_text = _advice_text(data.get("advice", {}) or {})
    story.append(_box("巫女の助言", advice_text, styles))
    story.append(Spacer(1, 4 * mm))

    cautions = data.get("cautions", []) or []
    if cautions:
        caution_text = "\n".join([f"・{item}" for item in cautions])
        story.append(_box("心に留めること", caution_text, styles))
        story.append(Spacer(1, 4 * mm))

    story.append(_box("結び", data.get("miko_closing", ""), styles))
    return story


def _draw_header(canvas, doc, title: str, font_name: str, bold_name: str) -> None:
    canvas.saveState()

    canvas.setStrokeColor(colors.HexColor("#EBD9D1"))
    canvas.setLineWidth(0.7)
    canvas.line(doc.leftMargin, A4[1] - 18 * mm, A4[0] - doc.rightMargin, A4[1] - 18 * mm)

    canvas.setFillColor(ACCENT)
    canvas.setFont(bold_name, 10.5)
    canvas.drawString(doc.leftMargin, A4[1] - 13 * mm, title)

    if MIKO_IMAGE_PATH and os.path.exists(MIKO_IMAGE_PATH):
        try:
            img = ImageReader(MIKO_IMAGE_PATH)
            iw, ih = img.getSize()
            target_h = 14 * mm
            target_w = target_h * (iw / ih)
            x = A4[0] - doc.rightMargin - target_w
            y = A4[1] - 17.5 * mm
            canvas.drawImage(
                img,
                x,
                y,
                width=target_w,
                height=target_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    page_label = f"{canvas.getPageNumber()}"
    canvas.setFillColor(MUTED)
    canvas.setFont(font_name, 9)
    pw = stringWidth(page_label, font_name, 9)
    canvas.drawString(A4[0] - doc.rightMargin - pw, 12 * mm, page_label)

    canvas.restoreState()


def generate_miko_letter_pdf(user_name: str, data: dict[str, Any]) -> bytes:
    font_name, bold_name = _register_fonts()
    styles = _build_styles(font_name, bold_name)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=26 * mm,
        bottomMargin=16 * mm,
        title=f"{APP_TITLE} - 巫女からの手紙",
        author="OMOSHIRO CRE8 WORKS",
    )

    story = _build_story(user_name, data or {}, styles)

    def _on_page(canvas, document):
        _draw_header(canvas, document, APP_TITLE, font_name, bold_name)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
