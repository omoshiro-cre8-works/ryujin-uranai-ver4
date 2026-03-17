import datetime
from dataclasses import dataclass
from typing import Any

FORTUNE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "miko_intro",
        "method_summary",
        "palm_details",
        "name_reading",
        "shichusuimei",
        "western_astrology",
        "fortune_3months",
        "fortune_1year",
        "fortune_3years",
        "advice",
        "cautions",
        "miko_closing",
    ],
    "properties": {
        "miko_intro": {"type": "string"},
        "method_summary": {"type": "string"},
        "palm_details": {"type": "string"},
        "name_reading": {"type": "string"},
        "shichusuimei": {"type": "string"},
        "western_astrology": {"type": "string"},
        "fortune_3months": {"type": "string"},
        "fortune_1year": {"type": "string"},
        "fortune_3years": {"type": "string"},
        "advice": {
            "type": "object",
            "required": ["item", "spot", "color", "luck_action"],
            "properties": {
                "item": {"type": "string"},
                "spot": {"type": "string"},
                "color": {"type": "string"},
                "luck_action": {"type": "string"},
            },
        },
        "cautions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 4,
        },
        "miko_closing": {"type": "string"},
    },
}

@dataclass
class PalmImageMeta:
    filename: str
    hand_side: str


@dataclass
class FortuneInput:
    user_name: str
    birth_date: datetime.date
    birth_place: str
    categories: list[str]
    concern_detail: str
    birth_time_accuracy: str
    birth_time_text: str
    image_parts: list[Any]
    image_meta: list[PalmImageMeta]
    image_count: int


class AppConfigError(RuntimeError):
    pass
