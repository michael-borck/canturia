"""A small Ollama client used only to write lyrics.

The topic box is intentionally not sent to ACE-Step's 5Hz LM: that model is a
music planner and treats duration/language loosely. Ollama runs locally, takes
one plain-language request, and returns lyrics with section tags. ACE-Step then
sings those words with an exact duration and vocal language.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from canturia.languages import language_name

# Prefer models that follow a "return only the lyrics" instruction. qwen3 (not
# 3.5) tends to put its planning in `content` even with think=false; keep it as
# a last resort.
PREFERRED_MODELS = (
    "qwen3.5",
    "gemma3",
    "llama3.1",
    "llama3",
    "mistral",
    "phi3",
    "qwen2.5",
    "qwen3",
)

_TAG_RE = re.compile(
    r"^\s*\[(Verse|Chorus|Bridge|Intro|Outro|Pre-Chorus)", re.IGNORECASE
)


class OllamaError(Exception):
    """Raised when Ollama is unreachable or returns unusable lyrics."""


def _detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason
    if isinstance(payload, dict):
        error = payload.get("error")
        if error:
            return str(error)
    return response.text.strip() or response.reason


def clean_lyrics(text: str) -> str:
    """Trim model chatter and make sure the result has a section tag."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    lines = text.splitlines()
    first_tag = next(
        (i for i, line in enumerate(lines) if _TAG_RE.match(line)), None
    )
    if first_tag is not None and first_tag > 0:
        lines = lines[first_tag:]
    text = "\n".join(lines).strip()

    if not text or "[instrumental]" in text.lower():
        return ""
    if not _TAG_RE.search(text):
        text = f"[Verse]\n{text}"
    return text


class OllamaClient:
    """One local lyricist call, no streaming, no SDK."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        model: str | None = None,
        timeout: float = 90.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or None
        self.timeout = float(timeout)
        self.session = session or requests.Session()

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> requests.Response:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url}: {e}. "
                "Is 'ollama serve' running?"
            ) from e
        if response.status_code >= 400:
            raise OllamaError(
                f"Ollama returned {response.status_code}: {_detail(response)}"
            )
        return response

    def models(self) -> list[str]:
        data = self._request("GET", "/api/tags").json()
        items = data.get("models") if isinstance(data, dict) else None
        names: list[str] = []
        for item in items or []:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return names

    def resolve_model(self) -> str:
        if self.model:
            return self.model
        names = self.models()
        for preferred in PREFERRED_MODELS:
            for name in names:
                base = name.split(":", 1)[0].lower()
                if base == preferred:
                    return name
        for name in names:
            base = name.split(":", 1)[0].lower()
            if not any(word in base for word in ("embed", "vision", "moondream")):
                return name
        raise OllamaError(
            "No Ollama chat model found. Pull one, e.g. "
            "'ollama pull qwen3.5:4b', or set ollama.model in the config."
        )

    def write_lyrics(
        self,
        topic: str,
        *,
        genre: str = "folk",
        style: str | None = None,
        duration: float = 30,
        language: str = "en",
    ) -> str:
        """Ask Ollama for original lyrics with section tags."""
        subject = (topic or "").strip()
        if not subject:
            raise OllamaError("Give me a topic or a few words to write about.")

        model = self.resolve_model()
        language_text = language_name(language)
        line_target = max(4, min(16, round(float(duration) / 5)))
        style_text = (style or "").strip()
        style_line = f"\nStyle details: {style_text}." if style_text else ""
        user = (
            f"Write original {genre} song lyrics in {language_text} about: "
            f"{subject}\n"
            f"Aim for about {int(duration)} seconds of music, roughly "
            f"{line_target} lyric lines across the sections."
            f"{style_line}\n"
            "Include at least one [Verse] and one [Chorus]. "
            "Do not reuse existing songs. Return only the lyrics."
        )
        system = (
            "You are a concise, original lyricist. Write singable lyrics. "
            "Use [Verse], [Chorus], and [Bridge] section tags. "
            "Return only the lyrics: no title, explanation, notes, plans, "
            "or code fences."
        )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.8, "num_predict": 600},
        }
        data = self._request("POST", "/api/chat", json_body=body).json()
        message = data.get("message") if isinstance(data, dict) else None
        content = ""
        if isinstance(message, dict):
            content = str(message.get("content") or "")
        if not content and isinstance(data, dict):
            content = str(data.get("response") or "")

        lyrics = clean_lyrics(content)
        if not lyrics:
            raise OllamaError(
                "Ollama returned no sung lyrics (it may have replied "
                "[Instrumental] or only planning text). Try again, pick a "
                "different ollama.model, or write the lyrics yourself."
            )
        return lyrics
