from __future__ import annotations

from typing import Any

import pytest
import requests

from canturia.providers.ollama import OllamaClient, OllamaError, clean_lyrics


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        text: str = "",
        reason: str = "OK",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text
        self.reason = reason

    def json(self) -> Any:
        if self.payload is None:
            raise ValueError("no json body")
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def test_clean_lyrics_removes_preamble_and_fences() -> None:
    raw = """```text
Here are the lyrics:

[Verse]
Morning light
[Chorus]
Grow a little
```"""
    cleaned = clean_lyrics(raw)
    assert cleaned.startswith("[Verse]")
    assert "Here are the lyrics" not in cleaned
    assert cleaned.endswith("Grow a little")


def test_clean_lyrics_adds_a_verse_tag_and_rejects_instrumental() -> None:
    assert clean_lyrics("just one line") == "[Verse]\njust one line"
    assert clean_lyrics("[Instrumental]") == ""


def test_models_and_preferred_model() -> None:
    models = {
        "models": [
            {"name": "nomic-embed-text:latest"},
            {"name": "gemma3:4b"},
            {"name": "qwen3.5:4b"},
        ]
    }
    session = FakeSession([FakeResponse(payload=models), FakeResponse(payload=models)])
    client = OllamaClient("http://ollama", session=session)  # type: ignore[arg-type]
    assert client.models() == [
        "nomic-embed-text:latest",
        "gemma3:4b",
        "qwen3.5:4b",
    ]
    assert client.resolve_model() == "qwen3.5:4b"


def test_write_lyrics_payload_and_result() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "message": {
                        "content": "[Verse]\nRain on the window\n[Chorus]\nSing anyway"
                    }
                }
            )
        ]
    )
    client = OllamaClient(
        "http://ollama",
        model="gemma3:4b",
        session=session,  # type: ignore[arg-type]
    )
    lyrics = client.write_lyrics(
        "a song about rain", genre="folk", duration=30, language="en"
    )
    assert lyrics == "[Verse]\nRain on the window\n[Chorus]\nSing anyway"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://ollama/api/chat"
    body = kwargs["json"]
    assert body["model"] == "gemma3:4b"
    assert body["think"] is False
    assert "about: a song about rain" in body["messages"][1]["content"]


def test_write_lyrics_rejects_instrumental() -> None:
    session = FakeSession(
        [FakeResponse(payload={"message": {"content": "[Instrumental]"}})]
    )
    client = OllamaClient(
        "http://ollama",
        model="gemma3:4b",
        session=session,  # type: ignore[arg-type]
    )
    with pytest.raises(OllamaError, match="no sung lyrics"):
        client.write_lyrics("rain")


def test_unreachable_ollama_has_a_helpful_error() -> None:
    class BrokenSession:
        def request(self, *args: Any, **kwargs: Any) -> FakeResponse:
            raise requests.ConnectionError("boom")

    client = OllamaClient(
        "http://ollama", session=BrokenSession()  # type: ignore[arg-type]
    )
    with pytest.raises(OllamaError, match="ollama serve"):
        client.models()
