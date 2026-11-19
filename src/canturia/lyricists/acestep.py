"""ACE-Step's own 5Hz LM, exposed only for comparison.

It is a music planner, not a lyricist. In testing it often returns
``[Instrumental]`` even when asked for sung vocals, and it ignores duration.
Treat a result as best-effort and always label it experimental.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from canturia.languages import language_name
from canturia.lyricists.base import (
    LyricistError,
    LyricRequest,
    LyricResult,
)
from canturia.lyrics_text import clean_lyrics
from canturia.providers.acestep import AceStepClient, AceStepError


class AceStepLyricist:
    name = "acestep"
    label = "ACE-Step LM (experimental)"

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.client = AceStepClient(
            base_url=str(settings["base_url"]),
            api_key=settings.get("api_key"),
            username=settings.get("username"),
            password=settings.get("password"),
            timeout=float(settings.get("timeout") or 180),
            request_timeout=float(settings.get("request_timeout") or 120),
            poll_interval=float(settings.get("poll_interval") or 2),
        )

    def write(
        self,
        request: LyricRequest,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> LyricResult:
        language = language_name(request.language)
        query = (
            f"{request.topic}, with lyrics in {language} and "
            f"{language} vocals"
        )
        if on_progress:
            on_progress("asking ACE-Step's 5Hz LM for lyrics…")
        try:
            data = self.client.create_sample(
                query,
                instrumental=False,
                vocal_language=request.language,
                temperature=0.8,
            )
        except AceStepError as e:
            raise LyricistError(str(e)) from e

        raw = str(data.get("lyrics") or "")
        if not raw or "[instrumental]" in raw.lower():
            raise LyricistError(
                "ACE-Step returned [Instrumental] instead of sung lyrics. "
                "Its 5Hz LM is not a reliable lyricist; use Ollama, an "
                "OpenAI-compatible model, or write the lyrics yourself."
            )
        lyrics = clean_lyrics(raw)
        if not lyrics:
            raise LyricistError("ACE-Step returned no usable lyrics.")
        caption = data.get("caption")
        return LyricResult(
            lyrics=lyrics,
            provider=self.name,
            model="ACE-Step 5Hz LM",
            caption=str(caption) if caption else None,
        )
