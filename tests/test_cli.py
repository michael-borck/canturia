from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from canturia import __version__
from canturia.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--init-config"])
    assert result.exit_code == 0
    assert (tmp_path / "canturia.yaml").exists()


def test_bare_text_routes_to_lyrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(mode: str, text: str, **kwargs: object) -> None:
        captured.update(mode=mode, text=text, **kwargs)

    monkeypatch.setattr("canturia.cli._run_generate", fake_run)
    result = runner.invoke(app, ["[Verse]\nhello", "-g", "folk"])
    assert result.exit_code == 0
    assert captured["mode"] == "lyrics"
    assert captured["text"] == "[Verse]\nhello"
    assert captured["genre"] == "folk"


def test_describe_routes_to_describe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(mode: str, text: str, **kwargs: object) -> None:
        captured.update(mode=mode, text=text, **kwargs)

    monkeypatch.setattr("canturia.cli._run_generate", fake_run)
    result = runner.invoke(app, ["describe", "a song about rain", "-t", "45"])
    assert result.exit_code == 0
    assert captured["mode"] == "describe"
    assert captured["text"] == "a song about rain"
    assert captured["duration"] == 45.0


def test_topic_routes_to_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(mode: str, text: str, **kwargs: object) -> None:
        captured.update(mode=mode, text=text, **kwargs)

    monkeypatch.setattr("canturia.cli._run_generate", fake_run)
    result = runner.invoke(app, ["topic", "a song about rain", "-t", "45"])
    assert result.exit_code == 0
    assert captured["mode"] == "topic"
    assert captured["text"] == "a song about rain"
    assert captured["duration"] == 45.0


def test_lyrics_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(mode: str, text: str, **kwargs: object) -> None:
        captured.update(mode=mode, text=text, **kwargs)

    monkeypatch.setattr("canturia.cli._run_generate", fake_run)
    lyrics = tmp_path / "words.txt"
    lyrics.write_text("[Verse]\nfrom a file", encoding="utf-8")
    result = runner.invoke(app, ["--lyrics-file", str(lyrics)])
    assert result.exit_code == 0
    assert captured["text"] == "[Verse]\nfrom a file"


def test_health_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "canturia.cli.health",
        lambda settings: {
            "status": "ok",
            "loaded_model": "acestep-v15-turbo",
            "models_initialized": True,
            "llm_initialized": False,
        },
    )
    monkeypatch.setattr(
        "canturia.cli.ollama_status",
        lambda settings: {
            "ok": True,
            "model": "qwen3.5:4b",
            "models": ["qwen3.5:4b"],
            "error": None,
        },
    )
    result = runner.invoke(app, ["health", "--base-url", "http://ace"])
    assert result.exit_code == 0
    assert "acestep-v15-turbo" in result.output
    assert "Ollama (qwen3.5:4b)" in result.output


def test_missing_text_is_an_error() -> None:
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 2
