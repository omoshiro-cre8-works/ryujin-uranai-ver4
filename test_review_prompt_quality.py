import json

from services import fortune_service


def make_review_context(palm_image_count):
    return {
        "review_context": {
            "previous_pdf_analysis": {
                "previous_reading_date": "2026-01-01",
                "current_reading_date": "2026-06-23",
                "days_since_previous_reading": 173,
                "months_since_previous_reading": 5,
            },
            "previous_summary": {
                "palm_reading_summary": "分析力に関する記述",
            },
            "timeline_reinterpretation": {
                "recent_3_months_status": "past",
            },
            "current_inputs": {
                "selected_theme": "仕事運",
                "review_memo_present": True,
                "palm_image_count": palm_image_count,
            },
        }
    }


def test_review_pdf_summary_prompt_limits_previous_palm_to_pdf_text():
    prompt = fortune_service.build_review_pdf_summary_prompt(
        {
            "previous_reading_date": "2026-01-01",
            "days_since_previous_reading": 173,
            "months_since_previous_reading": 5,
        }
    )

    assert "前回鑑定PDF本文に書かれている手相の記述だけ" in prompt
    assert "前回の手相画像そのものを見た、保存した、記憶した" in prompt
    assert "今回の現在手相と比較するため" not in prompt


def test_review_prompt_declares_information_boundary_and_review_structure():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "前回鑑定時の手相画像・個人情報を保存、記憶、再参照していない" in prompt
    assert "参照できる前回情報は、今回ユーザーがアップロードした前回鑑定PDF" in prompt
    assert "前回の手相画像と比べると" in prompt
    assert "受け取られる表現は禁止する" in prompt
    assert "前回のお告げ → 現在の状況 → 今回の読み直し" in prompt
    assert "今も活かせること → 見直した方がよいこと" in prompt


def test_review_prompt_strengthens_current_palm_section_when_image_exists():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "前回鑑定PDFに記されていた手相の傾向" in prompt
    assert "今回の画像から読み取れる範囲で印象に残る点" in prompt
    assert "近況メモと重なる読み" in prompt
    assert "これから3カ月の行動への手がかり" in prompt


def test_review_prompt_forbids_current_palm_reading_without_image():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(0),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "今回は現在の手相画像が添付されていません" in prompt
    assert "今回の手相、線、丘、手の状態を見たかのような記述を一切しない" in prompt


def test_review_prompt_suppresses_spiritual_sales_tone_and_repetition():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "『そなた』" not in prompt
    assert "「そなた」" in prompt
    assert "は使わない" in prompt
    assert "同じ助言・励まし・結論は本文全体で原則1回" in prompt
    assert "語句を言い換えただけの反復も避ける" in prompt
    assert "1〜3カ月ほどが一つの目安" in prompt
    assert "購入や継続利用を直接勧めない" in prompt


def test_review_prompt_uses_soft_relationship_language():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "重ねて見ると" in prompt
    assert "近い方向性が感じられます" in prompt
    assert "矛盾しない印象です" in prompt
    assert "強い確証表現を使わない" in prompt


def test_review_prompt_limits_reassurance_family_and_new_guidance_tone():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "励まし表現の使用は本文全体で合計1〜2回まで" in prompt
    assert "言い換えて意味を反復しない" in prompt
    assert "龍神さまからの新たな導き" in prompt
    assert "現在の流れをあらためて読み直す" in prompt
    assert "今の状況を静かに見返す" in prompt


def test_review_output_rejects_strong_confirmation_and_new_guidance():
    for prohibited_text in (
        "今回の画像は前回PDFの記述を裏付けるものです。",
        "今回の画像は前回PDFの記述を証明しています。",
        "今回の線は前回の読みと一致しています。",
        "龍神さまからの新たな導きをお伝えします。",
        "新しいお告げが示されたようです。",
    ):
        review_fortune = {
            field: "静かな見返しです。"
            for field in fortune_service.REVIEW_FORTUNE_FIELDS
        }
        review_fortune["current_changes"] = prohibited_text
        review_fortune["review_summary_points"] = []
        review_fortune["next_3_month_action_items"] = []
        review_fortune["comparison_blocks"] = []

        result = fortune_service.parse_review_fortune_result(
            json.dumps({"review_fortune": review_fortune}, ensure_ascii=False)
        )

        assert not result["fortune_success"]
        assert result["diagnostics"]["error_type"] == "ForbiddenPhrase"


def test_review_output_rejects_previous_palm_image_comparison():
    review_fortune = {
        field: "静かな見返しです。"
        for field in fortune_service.REVIEW_FORTUNE_FIELDS
    }
    review_fortune["current_changes"] = "前回の手相画像と比べると、線が強くなっています。"
    review_fortune["review_summary_points"] = []
    review_fortune["next_3_month_action_items"] = []
    review_fortune["comparison_blocks"] = []

    result = fortune_service.parse_review_fortune_result(
        json.dumps({"review_fortune": review_fortune}, ensure_ascii=False)
    )

    assert not result["fortune_success"]
    assert result["diagnostics"]["error_type"] == "ForbiddenPhrase"


def test_review_output_rejects_representative_forbidden_phrase():
    review_fortune = {
        field: "静かな見返しです。"
        for field in fortune_service.REVIEW_FORTUNE_FIELDS
    }
    review_fortune["ryujin_message"] = "そなたには無限の可能性があります。"
    review_fortune["review_summary_points"] = []
    review_fortune["next_3_month_action_items"] = []
    review_fortune["comparison_blocks"] = []

    result = fortune_service.parse_review_fortune_result(
        json.dumps({"review_fortune": review_fortune}, ensure_ascii=False)
    )

    assert not result["fortune_success"]
    assert result["diagnostics"]["error_type"] == "ForbiddenPhrase"
