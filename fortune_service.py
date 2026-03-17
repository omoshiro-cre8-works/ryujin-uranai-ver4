import json
from typing import Any

import streamlit as st
from google import genai
from google.genai import types

from config import GEMINI_MODEL, get_gemini_api_key
from models.schemas import AppConfigError, FORTUNE_RESPONSE_JSON_SCHEMA, FortuneInput
from services.formatter_service import normalize_fortune_result
from services.prompt_service import build_system_instruction, build_user_prompt
from services.validation_service import get_mime_type


@st.cache_resource
def get_gemini_client(api_key: str) -> genai.Client:
    if not api_key:
        raise AppConfigError("Gemini APIキーが設定されていません。.env または Streamlit Secrets の GEMINI_API_KEY を確認してください。")
    return genai.Client(api_key=api_key)


def build_image_parts(uploaded_files: list[Any]) -> list[Any]:
    parts: list[Any] = []
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        mime_type = get_mime_type(uploaded_file.name)
        parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    return parts


def call_gemini_fortune(data: FortuneInput) -> dict[str, Any]:
    api_key = get_gemini_api_key()
    client = get_gemini_client(api_key)
    contents: list[Any] = [build_user_prompt(data)]
    contents.extend(data.image_parts)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(),
            response_mime_type="application/json",
            response_json_schema=FORTUNE_RESPONSE_JSON_SCHEMA,
            temperature=0.7,
        ),
    )

    raw_text = (response.text or "").strip()
    if not raw_text:
        raise ValueError("Gemini から鑑定結果が返ってきませんでした。")

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON の解析に失敗しました: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("鑑定結果の形式が想定と異なります。")

    return normalize_fortune_result(parsed)
