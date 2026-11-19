from __future__ import annotations

from typing import Any

import pytest

from canturia.lyricists import (
    AceStepLyricist,
    LyricistError,
    LyricRequest,
    OllamaLyricist,
    OpenAICompatibleLyricist,
    build_lyricist,
)


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


def request() -> LyricRequest:
    return LyricRequest(
        topic="a song about rain",
        genre="folk",
        style="warm",
        duration=30,
        language="en",
    )


def test_openai_compatible_write() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "choices": [
                        {"message": {"content": "[Verse]\nRain on the window"}}
                    ]
                }
            )
        ]
    )
    lyricist = OpenAICompatibleLyricist(
        {
            "base_url": "http://lyrics/v1",
            "model": "test-model",
            "api_key": "secret",
            "timeout": 30,
        },
        session=session,  # type: ignore[arg-type]
    )
    result = lyricist.write(request())
    assert result.lyrics == "[Verse]\nRain on the window"
    assert result.provider == "openai-compatible"
    assert result.model == "test-model"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://lyrics/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"


def test_openai_compatible_reports_errors() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status_code=401,
                payload={"error": {"message": "bad key"}},
            )
        ]
    )
    lyricist = OpenAICompatibleLyricist(
        {
            "base_url": "http://lyrics/v1",
            "model": "test-model",
            "timeout": 30,
        },
        session=session,  # type: ignore[arg-type]
    )
    with pytest.raises(LyricistError, match="bad key"):
        lyricist.write(request())


def test_acestep_lyricist_success_and_instrumental() -> None:
    class FakeAce:
        def __init__(self, lyrics: str) -> None:
            self.lyrics = lyrics

        def create_sample(self, query: str, **kwargs: Any) -> dict[str, Any]:
            return {"lyrics": self.lyrics, "caption": "a caption"}

    lyricist = AceStepLyricist(
        {
            "base_url": "http://ace",
            "api_key": None,
            "username": None,
            "password": None,
            "timeout": 180,
            "request_timeout": 120,
            "poll_interval": 2,
        }
    )
    lyricist.client = FakeAce("[Verse]\nACE words")  # type: ignore[assignment]
    result = lyricist.write(request())
    assert result.lyrics == "[Verse]\nACE words"
    assert result.provider == "acestep"
    assert result.caption == "a caption"

    lyricist.client = FakeAce("[Music Box Melody]\n\n[Instrumental]")  # type: ignore[assignment]
    with pytest.raises(LyricistError, match="Instrumental"):
        lyricist.write(request())


def test_build_lyricist_and_unknown() -> None:
    settings = {
        "lyricist": "ollama",
        "lyricists": {
            "ollama": {"base_url": "http://127.0.0.1:11434"},
            "openai-compatible": {
                "base_url": "http://lyrics/v1",
                "model": "test",
            },
        },
        "ollama": {"base_url": "http://127.0.0.1:11434"},
    }
    assert isinstance(build_lyricist("ollama", settings), OllamaLyricist)
    assert isinstance(
        build_lyricist("openai-compatible", settings),
        OpenAICompatibleLyricist,
    )
    with pytest.raises(LyricistError, match="Unknown lyricist"):
        build_lyricist("nope", settings)
