from dataclasses import dataclass, field
from datetime import date
from typing import Any


class AppConfigError(RuntimeError):
    pass


@dataclass
class PalmImageMeta:
    filename: str
    hand_side: str


@dataclass
class FortuneInput:
    user_name: str
    birth_date: date
    birth_place: str
    categories: list[str]
    concern_detail: str
    birth_time_accuracy: str
    birth_time_text: str
    image_parts: list[Any] = field(default_factory=list)
    image_meta: list[PalmImageMeta] = field(default_factory=list)
    image_count: int = 0


FORTUNE_RESPONSE_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'miko_intro': {'type': 'string'},
        'method_summary': {'type': 'string'},
        'palm_details': {'type': 'string'},
        'name_reading': {'type': 'string'},
        'shichusuimei': {'type': 'string'},
        'western_astrology': {'type': 'string'},
        'fortune_3months': {'type': 'string'},
        'fortune_1year': {'type': 'string'},
        'fortune_3years': {'type': 'string'},
        'advice': {
            'type': 'object',
            'properties': {
                'item': {'type': 'string'},
                'spot': {'type': 'string'},
                'color': {'type': 'string'},
                'luck_action': {'type': 'string'},
            },
            'required': ['item', 'spot', 'color', 'luck_action'],
        },
        'cautions': {
            'type': 'array',
            'items': {'type': 'string'},
            'minItems': 2,
            'maxItems': 4,
        },
        'miko_closing': {'type': 'string'},
    },
    'required': [
        'miko_intro',
        'method_summary',
        'palm_details',
        'name_reading',
        'shichusuimei',
        'western_astrology',
        'fortune_3months',
        'fortune_1year',
        'fortune_3years',
        'advice',
        'cautions',
        'miko_closing',
    ],
}
