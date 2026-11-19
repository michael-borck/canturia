"""Small language-code to display-name map for prompts."""

from __future__ import annotations

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}


def language_name(code: str | None) -> str:
    value = (code or "en").strip().lower()
    return LANGUAGE_NAMES.get(value, value or "English")
