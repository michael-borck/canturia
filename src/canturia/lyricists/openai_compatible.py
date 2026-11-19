"""OpenAI-compatible lyricist (LM Studio, llama.cpp, OpenRouter, OpenAI)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from canturia.lyricists.base import (
    LyricistError,
    LyricRequest,
    LyricResult,
)
from canturia.lyrics_text import (
    SYSTEM_PROMPT,
    build_user_prompt,
    clean_lyrics,
)


def _detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if error:
            return str(error)
    return response.text.strip() or response.reason


class OpenAICompatibleLyricist:
    name = "openai-compatible"
    label = "OpenAI-compatible"

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = str(settings.get("base_url") or "").rstrip("/")
        self.model = settings.get("model")
        self.api_key = settings.get("api_key")
        self.timeout = float(settings.get("timeout") or 90)
        self.session = session or requests.Session()

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise LyricistError(
                f"Could not reach the lyricist at {self.base_url}: {e}"
            ) from e
        if response.status_code >= 400:
            raise LyricistError(
                f"Lyricist returned {response.status_code}: {_detail(response)}"
            )
        return response

    def models(self) -> list[str]:
        data = self._request("GET", "/models").json()
        items = data.get("data") if isinstance(data, dict) else data
        return [
            str(item["id"])
            for item in (items or [])
            if isinstance(item, dict) and item.get("id")
        ]

    def resolve_model(self) -> str:
        if self.model:
            return str(self.model)
        models = self.models()
        for name in models:
            base = name.lower()
            if not any(word in base for word in ("embed", "vision")):
                return name
        raise LyricistError(
            "No lyricist model configured. Set "
            "lyricists.openai-compatible.model in ~/.canturia.yaml."
        )

    def write(
        self,
        request: LyricRequest,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> LyricResult:
        if not self.base_url:
            raise LyricistError(
                "No OpenAI-compatible base_url configured. Set "
                "lyricists.openai-compatible.base_url in ~/.canturia.yaml."
            )
        model = self.resolve_model()
        if on_progress:
            on_progress(f"writing lyrics with {model}…")
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(
                        request.topic,
                        genre=request.genre,
                        style=request.style,
                        duration=request.duration,
                        language=request.language,
                    ),
                },
            ],
            "temperature": 0.8,
            "max_tokens": 600,
        }
        data = self._request("POST", "/chat/completions", json_body=body).json()
        choices = data.get("choices") if isinstance(data, dict) else None
        content: Any = ""
        if choices and isinstance(choices, list):
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first, dict) else {}
            if isinstance(message, dict):
                content = message.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        lyrics = clean_lyrics(str(content))
        if not lyrics:
            raise LyricistError(
                "The lyricist returned no usable lyrics. Check its model and "
                "whether it supports chat completions."
            )
        return LyricResult(lyrics=lyrics, provider=self.name, model=model)
