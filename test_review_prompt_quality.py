import json

from services import fortune_service
from services import pdf_service


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
    assert "見返し便の基本思想" in prompt
    assert "最重要情報" in prompt
    assert "相談者が選んだ「今回とくに見返したいテーマ」" in prompt
    assert "見返し便としての7章構成" in prompt
    assert "「前回のお告げ：」「現在の状況：」「今回の読み直し：」というラベル" in prompt


def test_review_prompt_prioritizes_theme_and_supplemental_context():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "仕事の方向性を見返したい"},
    )

    assert "相談テーマと補足情報を鑑定全体の軸" in prompt
    assert "今回何を見返したいのかを中心" in prompt
    assert "current_private_inputs の review_memo" in prompt
    assert "相談テーマと補足情報から外れた一般論を広げず" in prompt
    assert "近況メモに出てくる具体情報は、必要な箇所で一度整理すれば十分" in prompt


def test_review_prompt_strengthens_current_palm_section_when_image_exists():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "前回鑑定PDFに記されていた手相の傾向" in prompt
    assert "今回の画像から読み取れる範囲で印象に残る点" in prompt
    assert "近況メモと重なる読み" in prompt
    assert "これから3カ月の行動への手がかり" in prompt




def test_review_prompt_compresses_section_length_and_summary_overlap():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "全体として1〜2割短い印象" in prompt
    assert "今回の相談テーマに関係する部分を優先して3〜5項目程度" in prompt
    assert "1章と2章で同じ前回鑑定要約を繰り返さない" in prompt
    assert "2章後半に総括を書く場合は2〜4文程度" in prompt


def test_review_prompt_keeps_actions_and_closing_roles_separate():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "3章本文と同じ内容を再掲せず、具体行動は箇条書きに集約" in prompt
    assert "説明文は1〜2文に抑え" in prompt
    assert "3章の行動リストを再掲せず" in prompt
    assert "龍神さまは大きな方向性、巫女は続ける工夫、結びは短い締め" in prompt
    assert "things_to_remember は1〜3文程度" in prompt

def test_review_prompt_asks_to_merge_alignment_blocks_without_repeated_labels():
    prompt = fortune_service.build_review_fortune_prompt(
        make_review_context(1),
        {"user_name": "テスト", "review_memo": "近況"},
    )

    assert "本文では毎回ラベル分けせず" in prompt
    assert "短い導入・要点・まとめ" in prompt
    assert "同じ事実を章ごとに繰り返さず" in prompt
    assert "3章は具体的な行動に集中する" in prompt
    assert "巫女の助言」では同じ行動リストを繰り返さず" in prompt
    assert "単なるメモの羅列にしない" in prompt
    assert "手相だけを独立した説明にせず" in prompt


def test_review_pdf_comparison_blocks_render_without_repeated_labels():
    text = pdf_service._format_comparison_blocks(
        {
            "comparison_blocks": [
                {
                    "theme": "準備から改善へ",
                    "previous_message": "前回は準備の流れが示されていました。",
                    "current_status": "現在は販売後の改善点が見えています。",
                    "reinterpretation": "今は課題を絞る段階と見ることができます。",
                }
            ]
        }
    )

    assert "■ 準備から改善へ" in text
    assert "前回のお告げ：" not in text
    assert "現在の状況：" not in text
    assert "今回の読み直し：" not in text
    assert "前回は準備の流れが示されていました。\n現在は販売後の改善点" in text


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
    assert "少し時間を置いて読み返す" in prompt
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


def test_review_output_allows_advisory_phrases_with_diagnostics():
    for advisory_text in (
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
        review_fortune["current_changes"] = advisory_text
        review_fortune["review_summary_points"] = []
        review_fortune["next_3_month_action_items"] = []
        review_fortune["comparison_blocks"] = []

        result = fortune_service.parse_review_fortune_result(
            json.dumps({"review_fortune": review_fortune}, ensure_ascii=False)
        )

        assert result["fortune_success"]
        assert result["diagnostics"]["error_type"] == ""
        assert result["diagnostics"]["advisory_phrase_detected"]
        assert result["diagnostics"]["advisory_phrase_count"] >= 1
        assert not result["diagnostics"]["blocking_phrase_detected"]


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
    assert result["diagnostics"]["blocking_phrase_detected"]
    assert result["diagnostics"]["blocking_phrase_count"] >= 1


def test_review_output_allows_style_phrase_with_advisory_diagnostics():
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

    assert result["fortune_success"]
    assert result["diagnostics"]["advisory_phrase_detected"]
    assert result["diagnostics"]["advisory_phrase_count"] == 2
    assert not result["diagnostics"]["blocking_phrase_detected"]
