import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from services import fortune_service
from services.pdf_service import generate_miko_letter_pdf, generate_review_fortune_pdf, register_japanese_font
from services import review_pdf_validation_service
from services.review_pdf_validation_service import _parse_tounicode_cmap, validate_review_pdf_deterministic
from services.validation_service import validate_review_pdf_content


def make_regular_fortune_data():
    return {
        "miko_intro": "静かな挨拶です。",
        "method_summary": "複数の占術を重ねて読みました。",
        "palm_details": "手相の導きです。",
        "name_reading": "姓名判断の読みです。",
        "shichusuimei": "四柱推命の読みです。",
        "western_astrology": "西洋占星術の読みです。",
        "fortune_3months": "これから3カ月以内の運勢です。",
        "fortune_1year": "これから1年先の運勢です。",
        "fortune_3years": "2〜3年後の運勢です。",
        "advice": {
            "item": "鈴",
            "spot": "湖",
            "color": "朱色",
            "luck_action": "朝に深呼吸をする",
        },
        "cautions": ["心に留めることです。"],
        "miko_closing": "結びの言葉です。",
    }


def make_review_fortune_data():
    return {
        "intro": "前回のお告げの振り返りです。",
        "theme_review": "今回の見返しです。",
        "next_3_months": "これから3カ月の小さな行動です。",
        "one_year_guidance": "1年先への見通しです。",
        "ryujin_message": "見返しのことばです。",
        "miko_advice": "巫女の助言です。",
        "things_to_remember": "結びの言葉です。",
    }


def make_review_context(previous_date="2026-01-02"):
    return {
        "review_context": {
            "previous_pdf_analysis": {
                "previous_reading_date": previous_date,
                "current_reading_date": "2026-09-09",
            },
            "current_inputs": {"selected_theme": "仕事運"},
        }
    }


def make_simple_pdf(lines):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    font_name = register_japanese_font()
    c.setFont(font_name, 12)
    y = A4[1] - 40
    for line in lines:
        c.drawString(40, y, line)
        y -= 22
    c.save()
    return buffer.getvalue()


def test_generated_regular_pdf_is_valid_for_review_validation():
    pdf_bytes = generate_miko_letter_pdf("テストユーザー", make_regular_fortune_data())

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_regular"
    assert result["previous_reading_date"]


def test_generated_review_pdf_is_valid_for_next_review_validation():
    pdf_bytes = generate_review_fortune_pdf(make_review_fortune_data(), make_review_context("2026-01-02"))

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_review"
    assert result["previous_reading_date"] == "2026-01-02"


def test_legacy_review_pdf_alias_sections_are_valid():
    pdf_bytes = make_simple_pdf(
        [
            "龍神さまのお告げ 見返し便",
            "令和 8年 4月 5日",
            "前回のお告げ：2026年1月2日",
            "見返しテーマ：仕事運",
            "はじめに",
            "前回のお告げから続いている流れ",
            "現在の手相と近況から見える変化",
            "今回のテーマについての見返し",
            "これから3カ月の小さな行動",
            "巫女の助言",
            "龍神湖神社 巫女 拝",
        ]
    )

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_review"
    assert result["previous_reading_date"] == "2026-01-02"


def test_unrelated_pdf_is_rejected():
    pdf_bytes = make_simple_pdf(["請求書", "2026年9月9日", "合計 1000円"])

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_reject"


def test_title_only_mimic_pdf_is_rejected():
    pdf_bytes = make_simple_pdf(
        [
            "龍神さまのお告げ 見返し便",
            "令和 8年 9月 9日",
            "これはタイトルだけを似せた文書です。",
            "龍神湖神社 巫女 拝",
        ]
    )

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_reject"


def test_review_meta_labels_only_mimic_pdf_is_rejected():
    pdf_bytes = make_simple_pdf(
        [
            "龍神さまのお告げ 見返し便",
            "令和 8年 9月 9日",
            "前回のお告げ：2026年1月2日",
            "今回の見返し：2026年9月9日",
            "見返しテーマ：仕事運",
            "結び",
            "龍神湖神社 巫女 拝",
        ]
    )

    result = validate_review_pdf_deterministic(pdf_bytes)

    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_reject"
    assert result["diagnostics"]["review_meta_label_count"] >= 3
    assert result["diagnostics"]["review_body_section_count"] < 3


def test_review_pdf_without_labeled_previous_date_does_not_use_cover_date_as_previous(monkeypatch):
    pdf_bytes = make_simple_pdf(
        [
            "龍神さまのお告げ 見返し便",
            "令和 8年 9月 9日",
            "はじめに",
            "前回のお告げから続いている流れ",
            "現在の手相と近況から見える変化",
            "今回のテーマについての見返し",
            "これから3カ月の小さな行動",
            "巫女の助言",
            "龍神湖神社 巫女 拝",
        ]
    )
    calls = []
    monkeypatch.setattr(
        fortune_service,
        "call_gemini_review_pdf_analysis",
        lambda pdf: calls.append(pdf) or {"is_valid_previous_pdf": False, "previous_reading_date": ""},
    )

    deterministic_result = validate_review_pdf_deterministic(pdf_bytes)
    fallback_result = validate_review_pdf_content(pdf_bytes)

    assert deterministic_result["validation_method"] == "gemini_fallback"
    assert deterministic_result["previous_reading_date"] == ""
    assert deterministic_result["previous_reading_date_confidence"] == "low"
    assert calls == [pdf_bytes]
    assert fallback_result["validation_method"] == "gemini_fallback"


def test_missing_profile_structure_uses_gemini_fallback(monkeypatch):
    pdf_bytes = make_simple_pdf(
        [
            "龍神さまのお告げ",
            "令和 8年 9月 9日",
            "本文らしい断片だけがあります。",
            "龍神湖神社 巫女 拝",
        ]
    )
    calls = []

    monkeypatch.setattr(
        fortune_service,
        "call_gemini_review_pdf_analysis",
        lambda pdf: calls.append(pdf) or {"is_valid_previous_pdf": False, "previous_reading_date": ""},
    )

    result = validate_review_pdf_content(pdf_bytes)

    assert calls == [pdf_bytes]
    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "gemini_fallback"


def test_regular_pdf_with_gemini_false_negative_is_accepted(monkeypatch):
    pdf_bytes = generate_miko_letter_pdf("テストユーザー", make_regular_fortune_data())

    monkeypatch.setattr(
        fortune_service,
        "call_gemini_review_pdf_analysis",
        lambda pdf: {"is_valid_previous_pdf": False, "previous_reading_date": ""},
    )

    result = validate_review_pdf_content(pdf_bytes)

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_regular"


def test_review_pdf_with_gemini_false_negative_is_accepted(monkeypatch):
    pdf_bytes = generate_review_fortune_pdf(make_review_fortune_data(), make_review_context("2026-02-03"))

    monkeypatch.setattr(
        fortune_service,
        "call_gemini_review_pdf_analysis",
        lambda pdf: {"is_valid_previous_pdf": False, "previous_reading_date": ""},
    )

    result = validate_review_pdf_content(pdf_bytes)

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_review"
    assert result["previous_reading_date"] == "2026-02-03"


def test_previous_reading_date_is_extracted_for_regular_and_review_pdf():
    regular_result = validate_review_pdf_deterministic(
        generate_miko_letter_pdf("テストユーザー", make_regular_fortune_data())
    )
    review_result = validate_review_pdf_deterministic(
        generate_review_fortune_pdf(make_review_fortune_data(), make_review_context("2026-03-04"))
    )

    assert regular_result["previous_reading_date"]
    assert review_result["previous_reading_date"] == "2026-03-04"


def test_broken_pdf_is_rejected():
    result = validate_review_pdf_deterministic(b"%PDF-1.4\nbroken")

    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_reject"


def test_custom_extraction_failure_uses_pypdf_extract_text_for_validation(monkeypatch):
    class FakeContents:
        def get_data(self):
            return b""

    class FakePage:
        def get(self, key):
            if key == "/Resources":
                return {}
            return None

        def get_contents(self):
            return FakeContents()

        def extract_text(self):
            return "\n".join(
                [
                    "龍神さまのお告げ",
                    "龍神さまの鑑定書",
                    "令和 8年 9月 9日",
                    "鑑定のまとめ",
                    "手相の導き",
                    "姓名判断",
                    "四柱推命",
                    "直近：これから3カ月以内の運勢",
                    "展望：これから1年先の運勢",
                    "巫女の助言",
                    "結び",
                    "龍神湖神社 巫女 拝",
                ]
            )

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, _stream):
            pass

    monkeypatch.setattr(review_pdf_validation_service, "PdfReader", FakeReader)

    result = validate_review_pdf_deterministic(b"%PDF-1.4\nfake")

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_regular"
    assert result["diagnostics"]["text_extraction_method"] == "pypdf_extract_text"


def test_partial_custom_extraction_still_tries_standard_and_accepts(monkeypatch):
    class FakeContents:
        def get_data(self):
            return b"partial custom content"

    class FakePage:
        def get(self, key):
            if key == "/Resources":
                return {}
            return None

        def get_contents(self):
            return FakeContents()

        def extract_text(self):
            return "\n".join(
                [
                    "龍神さまのお告げ 見返し便",
                    "令和 8年 9月 9日",
                    "前回のお告げ：2026年1月2日",
                    "見返しテーマ：仕事運",
                    "はじめに",
                    "前回のお告げから続いている流れ",
                    "現在の手相と近況から見える変化",
                    "今回のテーマについての見返し",
                    "巫女の助言",
                    "龍神湖神社 巫女 拝",
                ]
            )

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, _stream):
            pass

    monkeypatch.setattr(review_pdf_validation_service, "PdfReader", FakeReader)
    monkeypatch.setattr(
        review_pdf_validation_service,
        "_extract_page_text_from_content",
        lambda _content, _cmaps: "\n".join(
            [
                "龍神さまのお告げ 見返し便",
                "令和 8年 9月 9日",
                "前回のお告げ：2026年1月2日",
                "龍神湖神社 巫女 拝",
            ]
        ),
    )

    result = validate_review_pdf_deterministic(b"%PDF-1.4\nfake")

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_review"
    assert result["previous_reading_date"] == "2026-01-02"
    assert result["diagnostics"]["text_extraction_method"] == "pypdf_extract_text"


def test_complete_custom_extraction_accept_is_not_changed_by_standard_fallback(monkeypatch):
    class FakeContents:
        def get_data(self):
            return b"complete custom content"

    class FakePage:
        def get(self, key):
            if key == "/Resources":
                return {}
            return None

        def get_contents(self):
            return FakeContents()

        def extract_text(self):
            return "請求書\n2026年9月9日\n合計 1000円"

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, _stream):
            pass

    monkeypatch.setattr(review_pdf_validation_service, "PdfReader", FakeReader)
    monkeypatch.setattr(
        review_pdf_validation_service,
        "_extract_page_text_from_content",
        lambda _content, _cmaps: "\n".join(
            [
                "龍神さまのお告げ",
                "龍神さまの鑑定書",
                "令和 8年 9月 9日",
                "鑑定のまとめ",
                "手相の導き",
                "姓名判断",
                "四柱推命",
                "直近：これから3カ月以内の運勢",
                "展望：これから1年先の運勢",
                "巫女の助言",
                "結び",
                "龍神湖神社 巫女 拝",
            ]
        ),
    )

    result = validate_review_pdf_deterministic(b"%PDF-1.4\nfake")

    assert result["is_valid_previous_pdf"]
    assert result["validation_method"] == "deterministic_regular"
    assert result["diagnostics"]["text_extraction_method"] == "pypdf_tounicode_cmap"


def test_custom_and_standard_extraction_without_enough_text_uses_gemini_fallback(monkeypatch):
    class FakeContents:
        def get_data(self):
            return b""

    class FakePage:
        def get(self, key):
            if key == "/Resources":
                return {}
            return None

        def get_contents(self):
            return FakeContents()

        def extract_text(self):
            return "短い"

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

        def __init__(self, _stream):
            pass

    monkeypatch.setattr(review_pdf_validation_service, "PdfReader", FakeReader)

    result = validate_review_pdf_deterministic(b"%PDF-1.4\nfake")

    assert not result["is_valid_previous_pdf"]
    assert result["validation_method"] == "gemini_fallback"


def test_tounicode_cmap_maps_beginbfchar_entries_only():
    cmap = _parse_tounicode_cmap(
        b"""
        begincmap
        1 begincodespacerange
        <00> <FF>
        endcodespacerange
        2 beginbfchar
        <01> <9F8D>
        <02> <795E>
        endbfchar
        endcmap
        """
    )

    assert cmap == {b"\x01": "龍", b"\x02": "神"}


def test_tounicode_cmap_does_not_treat_codespacerange_or_bfrange_as_bfchar():
    cmap = _parse_tounicode_cmap(
        b"""
        begincmap
        1 begincodespacerange
        <00> <FF>
        endcodespacerange
        1 beginbfrange
        <10> <12> <3042>
        endbfrange
        endcmap
        """
    )

    assert cmap == {}


def test_review_pdf_analysis_prompt_includes_regular_review_and_legacy_rules():
    prompt = fortune_service.build_review_pdf_analysis_prompt()

    assert "通常版「龍神さまのお告げ」PDF" in prompt
    assert "見返し便「龍神さまのお告げ 見返し便」PDF" in prompt
    assert "過去に生成された正規の見返し便PDF" in prompt
    assert "通常版13章の完全一致は必須にしない" in prompt
    assert "detected_sections / missing_sections は参考情報" in prompt
