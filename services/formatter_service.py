import re
from typing import Any

from services.validation_service import normalize_text

def split_into_readable_blocks(text: str) -> str:
    value = normalize_text(text)
    if not value:
        return ""

    value = re.sub(r"\r\n?", "\n", value)
    raw_blocks = [normalize_text(block) for block in value.split("\n") if normalize_text(block)]
    if raw_blocks:
        blocks = raw_blocks
    else:
        sentences = re.split(r"(?<=[。！？])", value)
        current: list[str] = []
        blocks = []
        for sentence in sentences:
            s = normalize_text(sentence)
            if not s:
                continue
            current.append(s)
            if len(current) >= 2:
                blocks.append("".join(current))
                current = []
        if current:
            blocks.append("".join(current))

    fixed_blocks: list[str] = []
    for block in blocks:
        sentences = [normalize_text(s) for s in re.split(r"(?<=[。！？])", block) if normalize_text(s)]
        if not sentences:
            continue
        for i in range(0, len(sentences), 3):
            fixed_blocks.append("".join(sentences[i : i + 3]))

    return "\n\n".join(fixed_blocks)


def sanitize_miko_voice(text: str) -> str:
    value = normalize_text(text)
    replacements = [
        (r"巫女の(?:沙良|さくら|小夜|紗良|皐月|沙夜)と申します。?", "巫女より、お告げをお伝えいたします。"),
        (r"巫女の(?:沙良|さくら|小夜|紗良|皐月|沙夜)です。?", "巫女より、お告げをお伝えいたします。"),
        (r"(?:私|わたくし)は巫女の(?:沙良|さくら|小夜|紗良|皐月|沙夜)です。?", "巫女より、お告げをお伝えいたします。"),
    ]
    for pattern, repl in replacements:
        value = re.sub(pattern, repl, value)
    value = value.replace("龍神様", "龍神さま")
    return value



def strip_english_mixed_text(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"[A-Za-z]{2,}", "", text)
    text = re.sub(r"[Ａ-Ｚａ-ｚ]{2,}", "", text)
    text = text.replace("龍神様", "龍神さま")
    text = re.sub(r"\s{2,}", " ", text)
    return normalize_text(text)

def normalize_fortune_result(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "miko_intro": split_into_readable_blocks(strip_english_mixed_text(sanitize_miko_voice(str(data.get("miko_intro", ""))))),
        "method_summary": split_into_readable_blocks(strip_english_mixed_text(str(data.get("method_summary", "")))),
        "palm_details": split_into_readable_blocks(strip_english_mixed_text(str(data.get("palm_details", "")))),
        "name_reading": split_into_readable_blocks(strip_english_mixed_text(str(data.get("name_reading", "")))),
        "shichusuimei": split_into_readable_blocks(strip_english_mixed_text(str(data.get("shichusuimei", "")))),
        "western_astrology": split_into_readable_blocks(strip_english_mixed_text(str(data.get("western_astrology", "")))),
        "fortune_3months": split_into_readable_blocks(strip_english_mixed_text(str(data.get("fortune_3months", "")))),
        "fortune_1year": split_into_readable_blocks(strip_english_mixed_text(str(data.get("fortune_1year", "")))),
        "fortune_3years": split_into_readable_blocks(strip_english_mixed_text(str(data.get("fortune_3years", "")))),
        "advice": {
            "item": strip_english_mixed_text(str((data.get("advice", {}) or {}).get("item", ""))),
            "spot": strip_english_mixed_text(str((data.get("advice", {}) or {}).get("spot", ""))),
            "color": strip_english_mixed_text(str((data.get("advice", {}) or {}).get("color", ""))),
            "luck_action": strip_english_mixed_text(str((data.get("advice", {}) or {}).get("luck_action", ""))),
        },
        "cautions": [strip_english_mixed_text(str(x)).replace("龍神様", "龍神さま") for x in (data.get("cautions", []) or []) if strip_english_mixed_text(str(x))],
        "miko_closing": split_into_readable_blocks(strip_english_mixed_text(sanitize_miko_voice(str(data.get("miko_closing", ""))))),
    }

    if not normalized["cautions"]:
        normalized["cautions"] = ["焦りすぎないこと", "体力と気力の波を丁寧に整えること"]
    return normalized
