"""Lyricist providers: local, BYOK, and the experimental ACE-Step LM."""

from __future__ import annotations

from typing import Any

from canturia.config import ConfigurationError, resolve_lyricist_settings
from canturia.lyricists.acestep import AceStepLyricist
from canturia.lyricists.base import (
    Lyricist,
    LyricistError,
    LyricRequest,
    LyricResult,
)
from canturia.lyricists.ollama import OllamaLyricist
from canturia.lyricists.openai_compatible import OpenAICompatibleLyricist
from canturia.providers.acestep import AceStepClient, AceStepError
from canturia.providers.ollama import OllamaClient, OllamaError

LYRICIST_LABELS = {
    "ollama": "Ollama (local)",
    "openai-compatible": "OpenAI-compatible (BYOK)",
    "acestep": "ACE-Step LM (experimental)",
}

LYRICIST_NAMES = tuple(LYRICIST_LABELS)


def build_lyricist(name: str | None, settings: dict[str, Any]) -> Lyricist:
    """Build one lyricist from resolved settings."""
    chosen = (name or str(settings.get("lyricist") or "ollama")).strip()
    if chosen not in LYRICIST_NAMES:
        raise LyricistError(
            f"Unknown lyricist {chosen!r}; choose ollama, "
            "openai-compatible, or acestep."
        )
    resolved = resolve_lyricist_settings(settings, chosen)
    if chosen == "ollama":
        return OllamaLyricist(resolved)
    if chosen == "openai-compatible":
        return OpenAICompatibleLyricist(resolved)
    if chosen == "acestep":
        return AceStepLyricist(resolved)
    raise LyricistError(
        f"Unknown lyricist {chosen!r}; choose ollama, "
        "openai-compatible, or acestep."
    )


def lyricist_options(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Availability and model label for each lyricist (never raises)."""
    options: list[dict[str, Any]] = []

    try:
        resolved = resolve_lyricist_settings(settings, "ollama")
        client = OllamaClient(
            base_url=str(resolved["base_url"]),
            model=resolved.get("model"),
            timeout=min(float(resolved.get("timeout") or 90), 5),
        )
        models = client.models()
        model = client.model or (client.resolve_model() if models else None)
        options.append(
            {
                "name": "ollama",
                "label": LYRICIST_LABELS["ollama"],
                "model": model,
                "models": models,
                "available": bool(models),
                "error": None if models else "No Ollama models found.",
            }
        )
    except (OllamaError, ConfigurationError, ValueError) as e:
        options.append(
            {
                "name": "ollama",
                "label": LYRICIST_LABELS["ollama"],
                "model": None,
                "models": [],
                "available": False,
                "error": str(e),
            }
        )

    try:
        resolved = resolve_lyricist_settings(settings, "openai-compatible")
        model = resolved.get("model")
        base_url = str(resolved.get("base_url") or "")
        api_key = resolved.get("api_key")
        error = None
        if not model:
            error = "Set lyricists.openai-compatible.model."
        elif "api.openai.com" in base_url and not api_key:
            error = "Set lyricists.openai-compatible.api_key."
        options.append(
            {
                "name": "openai-compatible",
                "label": LYRICIST_LABELS["openai-compatible"],
                "model": model,
                "models": [model] if model else [],
                "available": error is None,
                "error": error,
            }
        )
    except (ConfigurationError, ValueError, KeyError, TypeError) as e:
        options.append(
            {
                "name": "openai-compatible",
                "label": LYRICIST_LABELS["openai-compatible"],
                "model": None,
                "models": [],
                "available": False,
                "error": str(e),
            }
        )

    try:
        resolved = resolve_lyricist_settings(settings, "acestep")
        client = AceStepClient(
            base_url=str(resolved["base_url"]),
            api_key=resolved.get("api_key"),
            username=resolved.get("username"),
            password=resolved.get("password"),
            timeout=float(resolved.get("timeout") or 180),
            request_timeout=5,
            poll_interval=float(resolved.get("poll_interval") or 2),
        )
        health = client.health()
        available = bool(health.get("llm_initialized"))
        options.append(
            {
                "name": "acestep",
                "label": LYRICIST_LABELS["acestep"],
                "model": health.get("loaded_lm_model") or "ACE-Step 5Hz LM",
                "models": [],
                "available": available,
                "error": None
                if available
                else "ACE-Step's LM is off on the server.",
            }
        )
    except (
        AceStepError,
        ConfigurationError,
        ValueError,
        KeyError,
        TypeError,
    ) as e:
        options.append(
            {
                "name": "acestep",
                "label": LYRICIST_LABELS["acestep"],
                "model": None,
                "models": [],
                "available": False,
                "error": str(e),
            }
        )

    return options


__all__ = [
    "LYRICIST_LABELS",
    "LYRICIST_NAMES",
    "AceStepLyricist",
    "LyricRequest",
    "LyricResult",
    "Lyricist",
    "LyricistError",
    "OllamaLyricist",
    "OpenAICompatibleLyricist",
    "build_lyricist",
    "lyricist_options",
]
