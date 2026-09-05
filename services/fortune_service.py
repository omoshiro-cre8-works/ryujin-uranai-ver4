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

REVIEW_FORTUNE_RESPONSE_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'review_fortune': {
            'type': 'object',
            'properties': {
                'review_summary_points': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'comparison_blocks': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'theme': {'type': 'string'},
                            'previous_message': {'type': 'string'},
                            'current_status': {'type': 'string'},
                            'reinterpretation': {'type': 'string'},
                        },
                        'required': [
                            'theme',
                            'previous_message',
                            'current_status',
                            'reinterpretation',
                        ],
                    },
                },
                'next_3_month_action_items': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'intro': {'type': 'string'},
                'continuing_flow': {'type': 'string'},
                'current_changes': {'type': 'string'},
                'theme_review': {'type': 'string'},
                'next_3_months': {'type': 'string'},
                'one_year_guidance': {'type': 'string'},
                'ryujin_message': {'type': 'string'},
                'miko_advice': {'type': 'string'},
                'things_to_remember': {'type': 'string'},
            },
            'required': [
                'intro',
                'continuing_flow',
                'current_changes',
                'theme_review',
                'next_3_months',
                'one_year_guidance',
                'ryujin_message',
                'miko_advice',
                'things_to_remember',
            ],
        },
    },
    'required': ['review_fortune'],
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

REVIEW_FORTUNE_FIELDS = [
    'intro',
    'continuing_flow',
    'current_changes',
    'theme_review',
    'next_3_months',
    'one_year_guidance',
    'ryujin_message',
    'miko_advice',
    'things_to_remember',
]

REVIEW_FORTUNE_LIST_FIELDS = [
    'review_summary_points',
    'next_3_month_action_items',
]

REVIEW_FORTUNE_COMPARISON_FIELDS = [
    'theme',
    'previous_message',
    'current_status',
    'reinterpretation',
]

REVIEW_FORTUNE_BLOCKING_PHRASES = [
    # 前回画像を保存・記憶・比較しているという重大なプライバシー誤認
    '前回の手相画像と比べると',
    '前回の手相にも見られた線が',
    '以前の手相画像では',
    '前回の手の状態から見ると',
    '前回の画像を見返すと',
    '前回から手相が変化している',
    '前回と同じ線が今回も',
    # 医療・投資・転職に関する危険な断定や指示
    '投資すべき',
    '転職すべき',
    '治ります',
    '診断します',
]

REVIEW_FORTUNE_ADVISORY_PHRASES = [
    # 文体・品質上は避けたいが、成果物全体を破棄するほどではない表現
    '絶対に',
    '必ず成功',
    '必ず当たる',
    '運命です',
    '悪いことが起きます',
    '前回は当たっていました',
    '前回は外れていました',
    '前回のお告げは当たっていました',
    '前回のお告げは外れていました',
    '前回の鑑定は正しかったです',
    '前回の鑑定は間違っていました',
    'あなたはこうするべきです',
    'すべきです',
    'そなた',
    '龍神の力',
    '大いなる流れ',
    '大いなる潮流',
    '恐れることはない',
    '無限の可能性',
    '運命が動き出す',
    '龍神が示す',
    '龍神に導かれ',
    '豊かな未来が必ず',
    '裏付ける',
    '証拠',
    '証明',
    '一致している',
    '一致しています',
    '一致する',
    '一致した',
    '新たな導き',
    '新しいお告げが示された',
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
        parts.append(
            types.Part.from_bytes(
                data=uploaded_file.jpeg_bytes,
                mime_type=uploaded_file.mime_type,
            )
        )
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
- 手相は、前回鑑定PDF本文に書かれている手相の記述だけを要約する。前回の手相画像そのものを見た、保存した、記憶した、今回画像と比較できる、という前提を置かない。
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


def build_review_fortune_prompt(
    review_context: dict[str, Any],
    current_private_inputs: dict[str, Any],
) -> str:
    safe_context_json = json.dumps(review_context, ensure_ascii=False, indent=2)
    private_inputs_json = json.dumps(current_private_inputs, ensure_ascii=False, indent=2)
    current_inputs = (review_context or {}).get('review_context', {}).get('current_inputs', {}) or {}
    palm_image_count = int(current_inputs.get('palm_image_count') or 0)
    has_current_palm_images = palm_image_count > 0
    palm_image_instruction = (
        f"現在の手相画像は {palm_image_count} 枚添付されています。今回アップロードされた現在の手相画像から読み取れる範囲で、今の傾向や印象を少し具体的に述べ、"
        "前回PDF要約、時間軸再分類、相談テーマ、補足情報、近況メモと重ねてください。本文では「今回アップロードされた画像から読み取れる範囲では」「今回の手相画像から読み取れる範囲では」「画像から確認できる範囲では」など、画像に基づく範囲を明示してください。"
        "ただし、前回の手相画像との比較は行わず、前回画像を保存しているかのように見える表現は避けてください。前回PDF内に記載された手相情報に触れる場合は「前回鑑定に記された手相の傾向」として扱い、今回の手相画像は「現在の手相画像から読み取れる範囲」として扱ってください。"
        if has_current_palm_images
        else
        "今回は現在の手相画像が添付されていません。現在の手相を新たに読み取ったような表現はしないでください。前回PDF内の手相情報に触れる場合は「前回鑑定に記された手相の傾向」と明示し、現在の近況メモと見返しテーマを中心に照合してください。"
    )
    current_status_example = (
        "今回の近況・現在の手相画像・見返しテーマから見える現在の状態"
        if has_current_palm_images
        else
        "今回の近況・見返しテーマから見える現在の状態"
    )
    current_reference_text = (
        "今回の手相画像・近況・見返しテーマ"
        if has_current_palm_images
        else
        "今回の近況・見返しテーマ"
    )
    return f"""
AIうらない「龍神さまのお告げ 見返し便」の鑑定本文を生成してください。

以下の review_context は、第3弾Bで作成した前回PDF要約・時間軸再分類・現在入力の統合データです。
以下の current_private_inputs は、今回の本文生成だけに使う現在入力情報です。

review_context:
{safe_context_json}

current_private_inputs:
{private_inputs_json}

{palm_image_instruction}

見返し便の基本思想:
前回のお告げを踏まえ、現在の状況と相談テーマを中心に読み直し、姓名判断・四柱推命・西洋占星術・手相術のメソッドを使いながら、今後の変化と小さな行動を、静かで読みやすい言葉で伝えてください。

最重要情報:
- 相談者が選んだ「今回とくに見返したいテーマ」
- current_private_inputs の review_memo / recent_note に含まれる、特に重視したいこと・現在の近況
- current_private_inputs の birth_place / birth_time_accuracy / birth_time_text。四柱推命・西洋占星術の土台として通常版と同等に扱う
- 前回鑑定PDFの内容
- 今回アップロードされた手相画像（添付がある場合のみ）

見返し便の回答は、ユーザーの近況に合わせた一般的な助言ではなく、前回鑑定で用いた手相・姓名判断・四柱推命・西洋占星術の読み取りを前提に、{current_reference_text}を照合して作成してください。
相談テーマと補足情報を鑑定全体の軸に置き、前回PDFをただ要約するだけでなく、相談者が今回何を見返したいのかを中心に、前回鑑定と現在の状況を照らし合わせてください。
見返しサマリー、比較ブロック、3カ月の行動提案も、必ず占術上の示唆や前回鑑定の時間軸とのつながりを踏まえてください。全体の文章量は現在より2割ほど短い印象を目指し、PDFで4ページ前後、長くても5ページ程度に収まる密度を意識してください。

必ずJSONのみで返してください。章立ては以下のキーに対応させてください。
{{
  "review_fortune": {{
    "review_summary_points": [
      "前回PDFの占術的な示唆・今回の近況・見返しテーマ・時間軸のつながりを、1項目40字前後で短く整理した見返しポイント"
    ],
    "comparison_blocks": [
      {{
        "theme": "近況メモと見返しテーマに応じたテーマ名",
        "previous_message": "短い導入文1〜2文。前回から現在への接続に必要な参照だけを書き、前回鑑定の長い再説明はしない",
        "current_status": "要点の箇条書き3〜4個。各項目は単なる事実で終わらせず、だから今どう見るかまで短く含める。{current_status_example}、相談テーマ、必要な範囲の占術・手相要素を整理する",
        "reinterpretation": "短い読み直しのまとめ1〜2文。今はどの段階か、次に何を意識するかを静かにまとめる"
      }}
    ],
    "next_3_month_action_items": [
      "前回鑑定の時間軸と占術的示唆を踏まえて、これから3カ月で意識できる具体的な小さな行動"
    ],
    "intro": "1. 前回のお告げの振り返り。今回の相談テーマに関係する部分だけを3〜4項目の短い箇条書き中心でまとめ、長い段落にしない",
    "continuing_flow": "2章の短い締め。小見出しで述べた内容を繰り返さず、2文程度で全体の流れだけをまとめる",
    "current_changes": "2章の補足。今回の近況や手相画像から見える現在との関係だけを短く述べ、前回鑑定の再説明や同じ手相説明の反復はしない",
    "theme_review": "2章の短い結び。相談テーマと補足情報に沿って、今あらためて見直すことを2〜3文でまとめる",
    "next_3_months": "3章の短い方向づけ。直後に行動リストが続くため、『以下のような』などの二重導入は避け、本文は1文程度にする",
    "one_year_guidance": "4. 1年先に向けて整えていくこと。強く断定せず、方向性を考えやすくする",
    "ryujin_message": "5章。現在の歩みを大きな方向性として静かに受け止める。お告げらしい余韻は残しつつ、演劇的な言い回しや結びと同じ励ましは繰り返さない",
    "miko_advice": "6章。3章・4章の行動提案を再掲せず、実行を支える小さな心がけや工夫を、助言らしい温かさを残して短く伝える",
    "things_to_remember": "7章。龍神さま・巫女の助言を言い換えず、1〜3文で静かに締める"
  }}
}}

情報源と表現の境界（最優先）:
- このアプリは、前回鑑定時の手相画像・個人情報を保存、記憶、再参照していない。
- 参照できる前回情報は、今回ユーザーがアップロードした前回鑑定PDFに書かれている文章だけである。
- 前回の手相について述べるときは、必ず「前回鑑定PDFには〜と記されていました」「前回鑑定PDFに書かれていた手相の傾向」のように、PDF内の記述であることを明示する。
- 「前回の手相画像と比べると」「前回の手相にも見られた線が」「以前の手相画像では」「前回の手の状態から見ると」「前回の画像を見返すと」「前回から手相が変化している」「前回と同じ線が今回も」のように、前回画像を見た、保存した、記憶した、比較したと受け取られる表現は禁止する。
- 今回の手相について述べられるのは、今回アップロードされた画像から読み取れる範囲だけである。画像の限界を踏まえ、変化・強弱・確実性を断定しない。
- 今回の手相画像がない場合は、今回の手相、線、丘、手の状態を見たかのような記述を一切しない。

見返し便としての7章構成:
1. 前回のお告げの振り返り: 前回鑑定結果を簡単に要約し、今回の相談テーマに関係する部分を優先して3〜5項目程度で拾う。すべての占術結果を長く再説明しない。
2. 前回のお告げと現在の状況との照らし合わせ: 前回鑑定から現在までにどのような変化が起きているかを、近況メモ・相談テーマ・補足情報と照らし合わせる。「〜と見ることができます」「〜のように見受けられます」程度にとどめる。
3. これから3カ月ほど意識したいことや小さな行動: 相談テーマと補足情報に沿った具体例を、箇条書きを中心に実行しやすく示す。抽象的な励ましだけで終わらせない。
4. 1年先に向けて整えていくこと: 今すぐの行動だけでなく、1年先に向けて整えるテーマを伝える。強く断定しない。
5. 龍神さまからの見返しのことば: 現状を踏まえた大きな方向性や道すじを、静かであたたかい言葉で述べる。演劇的にしない。
6. 巫女の助言: 龍神さまのことばを受けて、日々の行動に落とし込める短い助言を伝える。
7. 結び: 静かに締める。必要であれば、1〜3カ月後に読み返すとよい程度の自然な文にする。

既存JSONキーとの対応:
- intro は 1章「前回のお告げの振り返り」。
- continuing_flow / current_changes / theme_review / comparison_blocks は 2章「前回のお告げと現在の状況との照らし合わせ」の材料。内容を重複させず、それぞれ短く役割分担する。
- 今回の主対象は2章である。1章、3章、4章、龍神さまのことば、巫女の助言、結びは大きく変更しない。
- 2章では前回鑑定の再説明を避け、現在との関係に必要な短い参照だけに留める。
- 2章では「前回のお告げ：」「現在の状況：」「今回の読み直し：」というラベルを小項目ごとに繰り返さない。
- comparison_blocks は、相談テーマに応じた2〜3個の小見出しに絞る。各項目は「■ 個人事業は準備から改善の段階へ」のような見出し、短い導入文1〜2文、要点の箇条書き3〜4個、短い読み直しのまとめ1〜2文で整理する。
- next_3_months / next_3_month_action_items は 3章。
- one_year_guidance は 4章、ryujin_message は 5章、miko_advice は 6章、things_to_remember は 7章。
- 各章は長くしすぎず、要点はできるだけ箇条書きまたは短い段落で整理する。全体として2割ほど短い印象を目指す。
- 1章 intro は長い説明文にせず、今回の見返しに必要な前回ポイントだけを3〜4項目の短い箇条書き中心にする。
- 2章の comparison_blocks は前回との差分、現在見えている課題、今回の読み直しを優先し、同じ手相説明や同じ補足を別ブロックで繰り返さない。
- 3章、4章、6章は役割を分ける。3章は直近3カ月の具体行動、4章は1年先の準備、6章は行動を続ける小さな心がけに寄せ、同じ助言を言い換えて再掲しない。
- 1章と2章で同じ要約を重ねない。1章は前回内容、2章は変化・継続・見直しに役割を分ける。
- 通常版の占術説明を最初から繰り返さず、姓名判断・四柱推命・西洋占星術・手相は、前回PDFと今回状況を照らし合わせる根拠として必要な分だけ使う。

本文に必ず反映すること:
- 前回鑑定日、今回鑑定日、前回鑑定日からの経過日数・経過月数。
- timeline_reinterpretation の status と note。
- 前回PDF要約の内容。
- 前回PDFから抽出された手相・姓名判断・四柱推命・西洋占星術の占術結果を、単なる背景情報ではなく、見返し鑑定の根拠として扱う。
- 現在の手相画像が添付されている場合のみ、画像から読み取れる今回時点の手がかり。
- 現在の手相画像が添付されていない場合は、手相からの新たな読み取りは行わず、前回鑑定に記された手相の傾向と現在の近況メモを中心に見返すこと。
- 今回とくに見返したいテーマ。これは鑑定全体の最重要軸として扱う。
- current_private_inputs の review_memo / recent_note に書かれた補足情報と現在の近況。これは相談テーマを具体化する最重要情報として扱う。
- current_private_inputs の user_name、birth_date、birth_place、birth_time_accuracy、birth_time_text を、姓名判断・四柱推命・西洋占星術の現在入力情報として確認する。
- 出生地と出生時刻精度は占術上の土台として反映するが、鑑定全体を出生情報や専門用語だけに偏らせず、前回PDF、見返しテーマ、近況メモ、現在の手相画像との照合に統合する。
- 近況メモに書かれた本人の現実感。
- review_summary_points は3項目程度。1章の振り返りを補助する短い要点にし、intro と同じ内容を言い換えて繰り返さない。
- comparison_blocks は2〜3項目程度。テーマは近況メモと見返しテーマに応じて選び、「前回のお告げ」「現在の状況」「今回の読み直し」をラベルとして分割しない。各ブロックは、短い導入文、腹落ちする要点3〜4個、短い読み直しのまとめで構成する。当たった・外れたの判定はしない。
- next_3_month_action_items は3〜4項目程度。重大判断ではなく、前回鑑定の時間軸・占術的示唆・今回テーマを踏まえた鑑定上の助言として、今後3カ月で意識できる具体的な小さな行動にする。命令口調にしない。3章本文と同じ内容を再掲せず、具体行動は箇条書きに集約する。

重要な解釈方針:
- 見返し便では、前回鑑定の単なる要約や言い換えに終わらせない。
- 相談テーマと補足情報から外れた一般論を広げず、今回何を見返したいのかに関係する差分を優先する。
- 1章で前回のお告げをまとめた後は、2章以降で前回内容を細かく再説明しない。必要なときだけ「この流れ」「その課題」「前回から続くテーマ」のように受ける。1章と2章で同じ前回鑑定要約を繰り返さない。
- 「前回のお告げで占術上示されていたこと」「今回の近況と、手相画像がある場合のみ現在の手相から見える現在の状態」「それを踏まえた今回の読み直し」は、内部では区別して考える。ただし本文では毎回ラベル分けせず、読みやすい短い導入・要点・まとめに整理する。2章後半に総括を書く場合は2〜4文程度の短い締めにする。
- 特に「直近3カ月」「1年先」「2〜3年後」の時間軸については、前回のお告げと今回の状態がどうつながっているかを明確にする。
- 前回鑑定の手相・姓名判断・四柱推命・西洋占星術の読み取りを軽視せず、現在入力や近況メモだけで結論を作らない。
- 一般的なビジネス助言、生活助言、自己啓発だけで終わらせず、鑑定上の根拠を自然に含める。
- 2章の箇条書きは単なるメモの羅列にしない。「広告を出した」「不安がある」のような事実だけで止めず、それが今の段階や相談テーマにどう関係するのか、だから今どう見るかまで短く添える。
- 近況メモに出てくる具体情報は、必要な箇所で一度整理すれば十分。同じ事実を章ごとに繰り返さず、以降は「その課題」「この流れ」「今見えている不安」などで受ける。
- 現在の手相画像が添付されていない場合、「現在の手相から見える」「今回の手のひらでは」「今回の手相画像から読み取れる範囲では」など、現在の手相を読んだような表現は禁止。
- 前回PDF内に記載された手相情報に触れる場合は、「前回鑑定に記された手相の傾向」と明示する。
- 現在の手相画像が添付されている場合のみ、「今回の手相画像から読み取れる範囲では」と表現できる。
- 現在の手相画像が添付されている場合は、今回アップロードされた現在の手相画像だけから読み取れる範囲で、特に印象に残る線・丘・手の雰囲気を無理のない範囲で具体的に述べる。
- 現在の手相画像が添付されている場合は、見返しテーマに応じて、今回アップロードされた現在の手相画像から重点的に見る観点を変える。
- 見返しテーマが事業運・仕事運・金運の場合は、今回の手相画像から読み取れる範囲で、水星丘、財運線、太陽線、運命線、知能線、手のひら全体の張りや印象など、商才、金銭感覚、継続力、判断力、事業や仕事への向き合い方に関係しそうな要素を優先する。
- 見返しテーマが恋愛・人間関係・家族関係の場合は、感情線、金星丘、手のひらの柔らかさ、指の開き方、手全体の印象など、対人感覚、愛情表現、距離感、共感力に関係しそうな要素を優先する。
- 見返しテーマが創作・発信・企画・学習に関する場合は、知能線、太陽線、水星丘、指先や手全体の印象など、創造性、表現力、伝える力、思考の傾向に関係しそうな要素を優先する。
- 見返しテーマが健康・体調・疲れに関する場合は、医療的な診断や改善保証は行わず、手相上の一般的な活力や休息のサインとして控えめに扱う。
- 現在の手相画像から見える印象は、今回の近況メモや見返しテーマとどう重なるか、これから3カ月の行動に関係しそうな手がかりは何かを整理する。手相だけを独立した説明にせず、現在の状況や相談テーマとの関係を短く添える。
- current_changes は、手相画像がある場合、「前回鑑定PDFに記されていた手相の傾向」「今回の画像から読み取れる範囲で印象に残る点」「近況メモと重なる読み」「これから3カ月の行動への手がかり」の4点が区別できるように整理する。
- 手相画像がある場合でも「前回から大きく変化したと断定するものではありませんが」など情報境界を明確にし、今回の画像で印象に残る点を中心に書く。
- 手相の読み取りは画像の光の当たり方、角度、ピント、解像度、手の開き方によって精度が変わるため、細かな線の断定ではなく全体の傾向として扱う。
- 手相の読み取りは断定せず、「画像から読み取れる範囲では」「〜のように見受けられます」「今回の近況メモと重ねて見ると」「前回鑑定PDFの記述と近い方向性が感じられます」「前回鑑定に記された傾向と矛盾しない印象です」など柔らかい表現にする。
- 前回鑑定PDFの記述と今回の手相画像の関係に、「裏付ける」「証拠」「証明」「一致している」「一致しています」などの強い確証表現を使わない。両者は別の情報源として扱い、「重ねて見ると」「近い方向性が感じられる」「矛盾しない印象」程度にとどめる。
- 前回の手相画像との比較は行わない。「前回と比べて」「前回より強くなっている」「前回から変化している」「前回の画像と比較すると」「以前より線が明瞭になっている」「弱まっている」「強まっている」「変化が見える」のように、前回画像を保存・比較しているように見える表現は避ける。
- 前半では、前回と現在の差分・照合を優先する。前回の全文要約や一般的な励ましより、何が進み、何が残り、次に何を整えるかを短く示す。
- 同じ意味の励ましや助言を複数セクションで繰り返しすぎない。
- 「焦らず」「一歩一歩」「着実に」「地道に」「長期的視点」「不安は自然」「自分を信じる」「直感を信じる」「休息を大切にする」は、必要な場合だけ本文全体で最小限にし、複数章で繰り返さない。
- 3章は具体的な行動に集中する。説明文は1文程度に抑え、「以下のような」などの導入を重ねず、決済改善、広告分析、転職活動の見直しなどの具体行動は箇条書きに集約する。6章「巫女の助言」では同じ行動リストを繰り返さず、行動を続けるための日々の心がけや小さな工夫に寄せる。
- 同じ助言・励まし・結論は本文全体で原則1回、必要でも2回までに抑える。語句を言い換えただけの反復も避ける。
- 比較ブロックと中盤の各章では、抽象的な安心表現ではなく、前回PDFの記述・今回の近況・今回画像から読み取れる範囲の差分と具体的な行動を優先する。
- 「焦らず」「地道に」「着実に」「基盤固め」「長期的な視点」「不安は自然」「自分を信じる」「直感を信じる」「心身のバランス」「休息を大切にする」「一歩一歩」など、同じ意味を持つ励まし表現の使用は本文全体で合計1〜2回までに抑える。同じ語を避けても、言い換えて意味を反復しない。
- 中盤のセクションでは、抽象的な励ましよりも、前回鑑定・現在の近況・今回のテーマ・手相画像がある場合のみ現在の手相画像から読み取れる内容の整理を優先する。
- 励まし要素は、主に「龍神さまからの見返しの言葉」「巫女の助言」「結び」に集約し、比較・分析セクションでは具体的な見返し内容を中心にする。龍神さまは大きな方向性、巫女は続ける工夫、結びは短い締めに分け、同じ励ましを繰り返さない。
- 前回のお告げを「当たり」「外れ」と評価しない。
- 「前回のお告げは当たっていました」「外れていました」「正しかった」「間違っていた」のような採点表現を使わない。
- 前回のお告げと現在の近況が重なる点、前回時点とは違う流れになっている点、今も続いているテーマ、これからも意識したい流れとして整理する。
- 姓名判断は変わりにくい土台として扱う。
- 生年月日由来の四柱推命・西洋占星術の本質的傾向は土台として扱い、前回から大きく変化したものとして扱わない。
- 時期運は、前回鑑定日からの経過期間を踏まえて今回時点で再解釈する。
- 手相は、今回の現在の状態や内面の傾向を映す手がかりとして扱う。
- 近況メモは、本人が実際に感じている現実として尊重する。
- 医療・法律・投資・転職などの重大判断を促す表現は避ける。
- things_to_remember は1〜3文程度に抑える。龍神さまの言葉や巫女の助言を言い換えず、今回の鑑定書を少し時間を置いて読み返すと今日とは違う点に目が留まることがある、という静かな結びにする。購入や継続利用を直接勧めない。
- 次回見返しにつながる導線は強い販促にしない。「また購入してください」「次回もぜひご利用ください」「継続利用がおすすめです」「定期的に受けると運気が上がります」「次回購入すると運勢がさらに良くなります」のような表現は避ける。

文体:
- やさしく、静かで、少し神秘的に。
- 不安をあおらない。
- 断定しすぎない。
- 押しつけない。
- 広告っぽくしない。
- 鑑定らしさは保ちつつ、怖がらせない。

「龍神さまからの見返しの言葉」の文体:
- 龍神さまのお告げらしい余韻を保ちつつも、過度に大げさ・宗教的・演劇的・断定的な表現は避ける。
- 「そなた」「龍神の力」「大いなる流れ」「大いなる潮流」「恐れることはない」「無限の可能性」「豊かな実り」「内なる声」「龍神は見守っています」「見守っています」「道を切り開く力」「新たな流れを創り出す」「運命が動き出す」「龍神が示す」「龍神に導かれ」「豊かな未来が必ず」「試練」「使命」「魂」「奇跡」は基本的に避ける。
- 呼びかける場合は、必ず「〇〇さん」とさん付けにする。「そなた」のような古風な呼びかけは使わない。
- 「龍神が示す」ではなく、巫女が静かに読み直して伝える言葉として書く。
- 読者に圧を与える口調ではなく、静かであたたかく、現実の状況に接続した短い言葉にする。龍神さまのお告げらしい余韻は残してよいが、結びで同じ内容を再度言い換えなくて済むよう、この章では大きな方向性だけを述べる。
- 「龍神さまからの新たな導き」「新しいお告げが示された」のように新しい啓示を授ける表現は避け、「現在の流れをあらためて読み直す」「今の状況を静かに見返す」程度の表現にする。
- 前回鑑定の占術根拠や今回の近況を踏まえつつも、未来を断定せず、「〜のように見受けられます」「〜を意識するとよさそうです」などの柔らかい表現を使う。「〜の流れが感じられます」を多用せず、現在の具体状況と次の小さな行動に接続する。

避ける表現:
- 絶対に
- 必ず
- 運命です
- 悪いことが起きます
- あなたはこうするべきです
- 前回は当たっていました
- 前回は外れていました
- 前回の鑑定は正しかったです
- 前回の鑑定は間違っていました

使ってよい表現:
- 〜の流れが見えます
- 〜を意識するとよさそうです
- 〜として受け取ることができます
- 〜が静かに続いているようです
- 〜を整えていく時期かもしれません

個人情報の扱い:
- 氏名や生年月日を本文内に不必要に繰り返さない。
- 近況メモは丸写しせず、本人の状況として短く受け止めて要約する。
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


def _empty_review_fortune(
    reason: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review_fortune: dict[str, Any] = {field: '' for field in REVIEW_FORTUNE_FIELDS}
    review_fortune.update({field: [] for field in REVIEW_FORTUNE_LIST_FIELDS})
    review_fortune['comparison_blocks'] = []
    result = {
        'fortune_success': False,
        'review_fortune': review_fortune,
        'reason': reason,
    }
    if diagnostics:
        result['diagnostics'] = diagnostics
    return result


def _parse_review_fortune_list(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    return [str(value).strip() for value in raw_value if str(value).strip()]


def _parse_review_fortune_comparison_blocks(raw_value: Any) -> list[dict[str, str]]:
    if not isinstance(raw_value, list):
        return []

    blocks: list[dict[str, str]] = []
    for raw_block in raw_value:
        if not isinstance(raw_block, dict):
            continue
        block = {
            field: str(raw_block.get(field) or '').strip()
            for field in REVIEW_FORTUNE_COMPARISON_FIELDS
        }
        if any(block.values()):
            blocks.append(block)
    return blocks


def _replace_current_palm_references_without_images(text: str) -> str:
    result = str(text or '')
    replacements = [
        ('今回の手相画像から読み取れる範囲では', '今回の近況から見返すと'),
        ('現在の手相画像から読み取れる範囲では', '現在の近況から見返すと'),
        ('今回の手のひらでは', '今回の近況では'),
        ('現在の手のひらでは', '現在の近況では'),
        ('現在の手相と近況', '現在の近況'),
        ('今回の手相画像', '今回の近況'),
        ('現在の手相画像', '現在の近況'),
        ('今回の手のひら', '今回の近況'),
        ('現在の手のひら', '現在の近況'),
        ('現在の手相から', '現在の近況から'),
        ('今回の手相から', '今回の近況から'),
        ('現在の手相では', '現在の近況では'),
        ('今回の手相では', '今回の近況では'),
        ('現在の手相に', '現在の近況に'),
        ('今回の手相に', '今回の近況に'),
        ('現在の手相を', '現在の近況を'),
        ('今回の手相を', '今回の近況を'),
    ]
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def _sanitize_current_palm_references_without_images(review_fortune: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for field in REVIEW_FORTUNE_FIELDS:
        sanitized[field] = _replace_current_palm_references_without_images(str(review_fortune.get(field) or ''))
    for field in REVIEW_FORTUNE_LIST_FIELDS:
        values = review_fortune.get(field)
        if isinstance(values, list):
            sanitized[field] = [_replace_current_palm_references_without_images(str(value)) for value in values]
        else:
            sanitized[field] = []

    blocks: list[dict[str, str]] = []
    for block in review_fortune.get('comparison_blocks') or []:
        if not isinstance(block, dict):
            continue
        blocks.append(
            {
                field: _replace_current_palm_references_without_images(str(block.get(field) or ''))
                for field in REVIEW_FORTUNE_COMPARISON_FIELDS
            }
        )
    sanitized['comparison_blocks'] = blocks

    current_changes = str(sanitized.get('current_changes') or '').strip()
    no_image_note = (
        '今回は現在の手相画像が添付されていないため、手相からの新たな読み取りは行わず、'
        '前回鑑定に記された手相の傾向と、現在の近況メモを中心に見返してまいります。'
    )
    if current_changes and no_image_note not in current_changes:
        sanitized['current_changes'] = f'{no_image_note}\n\n{current_changes}'
    elif not current_changes:
        sanitized['current_changes'] = no_image_note
    return sanitized


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


def parse_review_fortune_result(raw_text: str) -> dict[str, Any]:
    text = (raw_text or '').strip()
    if not text:
        return _empty_review_fortune('Geminiから見返し便鑑定本文が返ってきませんでした。')

    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _empty_review_fortune('Geminiの見返し便鑑定本文をJSONとして解析できませんでした。')

    if not isinstance(parsed, dict):
        return _empty_review_fortune('Geminiの見返し便鑑定本文の形式が想定と異なります。')

    raw_fortune = parsed.get('review_fortune')
    if not isinstance(raw_fortune, dict):
        return _empty_review_fortune('Geminiの見返し便鑑定本文に review_fortune が含まれていません。')

    review_fortune: dict[str, Any] = {field: str(raw_fortune.get(field) or '').strip() for field in REVIEW_FORTUNE_FIELDS}
    for field in REVIEW_FORTUNE_LIST_FIELDS:
        review_fortune[field] = _parse_review_fortune_list(raw_fortune.get(field))
    review_fortune['comparison_blocks'] = _parse_review_fortune_comparison_blocks(raw_fortune.get('comparison_blocks'))

    combined_text_parts = [str(review_fortune.get(field) or '') for field in REVIEW_FORTUNE_FIELDS]
    for field in REVIEW_FORTUNE_LIST_FIELDS:
        combined_text_parts.extend(review_fortune.get(field) or [])
    for block in review_fortune.get('comparison_blocks') or []:
        combined_text_parts.extend(str(block.get(field) or '') for field in REVIEW_FORTUNE_COMPARISON_FIELDS)
    combined_text = '\n'.join(combined_text_parts)
    blocking_phrases = [
        phrase for phrase in REVIEW_FORTUNE_BLOCKING_PHRASES if phrase in combined_text
    ]
    advisory_phrases = [
        phrase for phrase in REVIEW_FORTUNE_ADVISORY_PHRASES if phrase in combined_text
    ]
    missing_sections = [field for field in REVIEW_FORTUNE_FIELDS if not review_fortune[field]]
    if blocking_phrases:
        return _empty_review_fortune(
            '見返し便鑑定本文に重大な避けたい表現が含まれていました。',
            {
                'failed_step': 'parse_response',
                'error_type': 'ForbiddenPhrase',
                'missing_sections_count': len(missing_sections),
                'forbidden_phrase_detected': True,
                'blocking_phrase_detected': True,
                'blocking_phrase_count': len(blocking_phrases),
                'advisory_phrase_detected': bool(advisory_phrases),
                'advisory_phrase_count': len(advisory_phrases),
            },
        )

    fortune_success = not missing_sections
    return {
        'fortune_success': fortune_success,
        'review_fortune': review_fortune,
        'reason': '見返し便鑑定本文を整理しました。' if fortune_success else '見返し便鑑定本文の必須章に空欄がありました。',
        'diagnostics': {
            'failed_step': '' if fortune_success else 'parse_response',
            'error_type': '',
            'missing_sections_count': len(missing_sections),
            'forbidden_phrase_detected': False,
            'blocking_phrase_detected': False,
            'blocking_phrase_count': 0,
            'advisory_phrase_detected': bool(advisory_phrases),
            'advisory_phrase_count': len(advisory_phrases),
        },
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
        'birth_place': str(current_inputs.get('birth_place') or ''),
        'birth_time_accuracy': str(current_inputs.get('birth_time_accuracy') or ''),
        'birth_time_text': str(current_inputs.get('birth_time_text') or ''),
        'selected_theme': str(current_inputs.get('selected_theme') or ''),
        'review_theme': str(current_inputs.get('review_theme') or current_inputs.get('selected_theme') or ''),
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


def call_gemini_review_fortune(
    review_context: dict[str, Any],
    current_private_inputs: dict[str, Any],
    image_parts: list[Any],
) -> dict[str, Any]:
    failed_step = 'build_contents'
    diagnostics_base = {
        'model_name': GEMINI_MODEL,
    }
    contents: list[Any] = [build_review_fortune_prompt(review_context, current_private_inputs)]
    contents.extend(image_parts)

    logger.info('review_fortune_started', extra={'model': GEMINI_MODEL, 'image_count': len(image_parts)})
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
                response_json_schema=REVIEW_FORTUNE_RESPONSE_JSON_SCHEMA,
                temperature=0.65,
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
            'review_fortune_failed '
            f"fortune_success=False failed_step={failed_step} "
            f"error_type={diagnostics['error_type']} reason=gemini_exception "
            f"missing_sections_count=0 forbidden_phrase_detected=False image_count={len(image_parts)}"
        )
        return _empty_review_fortune(
            '見返し便の鑑定本文生成中にエラーが発生しました。時間をおいてもう一度お試しください。',
            diagnostics,
        )

    failed_step = 'parse_response'
    result = parse_review_fortune_result(response.text or '')
    parse_diagnostics = result.get('diagnostics') or {}
    current_inputs = (review_context or {}).get('review_context', {}).get('current_inputs', {}) or {}
    try:
        palm_image_count = int(current_inputs.get('palm_image_count') or 0)
    except (TypeError, ValueError):
        palm_image_count = 0
    if palm_image_count <= 0 and not image_parts and isinstance(result.get('review_fortune'), dict):
        result['review_fortune'] = _sanitize_current_palm_references_without_images(result['review_fortune'])
    result_failed_step = str(parse_diagnostics.get('failed_step') or ('' if result.get('fortune_success') else failed_step))
    result_error_type = str(parse_diagnostics.get('error_type') or '')
    missing_sections_count = int(parse_diagnostics.get('missing_sections_count') or 0)
    forbidden_phrase_detected = bool(parse_diagnostics.get('forbidden_phrase_detected'))
    blocking_phrase_detected = bool(parse_diagnostics.get('blocking_phrase_detected'))
    blocking_phrase_count = int(parse_diagnostics.get('blocking_phrase_count') or 0)
    advisory_phrase_detected = bool(parse_diagnostics.get('advisory_phrase_detected'))
    advisory_phrase_count = int(parse_diagnostics.get('advisory_phrase_count') or 0)
    result['diagnostics'] = {
        **diagnostics_base,
        'failed_step': result_failed_step,
        'error_type': result_error_type,
        'error_message_short': '',
        'missing_sections_count': missing_sections_count,
        'forbidden_phrase_detected': forbidden_phrase_detected,
        'blocking_phrase_detected': blocking_phrase_detected,
        'blocking_phrase_count': blocking_phrase_count,
        'advisory_phrase_detected': advisory_phrase_detected,
        'advisory_phrase_count': advisory_phrase_count,
    }
    if advisory_phrase_detected:
        logger.warning(
            'review_fortune_advisory_phrase_detected '
            f"advisory_phrase_count={advisory_phrase_count} "
            f"fortune_success={bool(result.get('fortune_success'))} image_count={len(image_parts)}"
        )
    safe_reason = re.sub(r'[^0-9A-Za-z_\-ぁ-んァ-ヶ一-龠々ー。・、 ]+', '', str(result.get('reason') or ''))
    if len(safe_reason) > 80:
        safe_reason = safe_reason[:80]
    logger.info(
        'review_fortune_completed '
        f"fortune_success={bool(result.get('fortune_success'))} "
        f"failed_step={result_failed_step} error_type={result_error_type} "
        f"reason={safe_reason} missing_sections_count={missing_sections_count} "
        f"forbidden_phrase_detected={forbidden_phrase_detected} "
        f"blocking_phrase_detected={blocking_phrase_detected} "
        f"blocking_phrase_count={blocking_phrase_count} "
        f"advisory_phrase_detected={advisory_phrase_detected} "
        f"advisory_phrase_count={advisory_phrase_count} image_count={len(image_parts)}"
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
