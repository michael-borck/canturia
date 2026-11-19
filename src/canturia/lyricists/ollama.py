"""Ollama lyricist: local, no key, one chat call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from canturia.lyricists.base import (
    LyricistError,
    LyricRequest,
    LyricResult,
)
from canturia.providers.ollama import OllamaClient, OllamaError


class OllamaLyricist:
    name = "ollama"

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    def write(
        self,
        request: LyricRequest,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> LyricResult:
        try:
            client = OllamaClient(
                base_url=str(self.settings["base_url"]),
                model=self.settings.get("model"),
                timeout=float(self.settings.get("timeout") or 90),
            )
            model = client.resolve_model()
            client.model = model
            if on_progress:
                on_progress(f"writing lyrics with Ollama ({model})…")
            lyrics = client.write_lyrics(
                request.topic,
                genre=request.genre,
                style=request.style,
                duration=request.duration,
                language=request.language,
            )
        except OllamaError as e:
            raise LyricistError(str(e)) from e
        return LyricResult(lyrics=lyrics, provider=self.name, model=model)
