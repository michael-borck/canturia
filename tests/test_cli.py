from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from canturia import __version__
from canturia.cli import app
from canturia.lyricists import LyricResult

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


def test_advanced_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(mode: str, text: str, **kwargs: object) -> None:
        captured.update(mode=mode, text=text, **kwargs)

    monkeypatch.setattr("canturia.cli._run_generate", fake_run)
    result = runner.invoke(
        app,
        [
            "[Verse]\nhello",
            "--bpm",
            "90",
            "--instrumental",
            "--language",
            "es",
            "--key",
            "C major",
            "--time-signature",
            "4/4",
            "--seed",
            "7",
            "--steps",
            "20",
            "--guidance",
            "6.5",
            "--model",
            "acestep-v15-turbo",
        ],
    )
    assert result.exit_code == 0
    assert captured["bpm"] == 90
    assert captured["instrumental"] is True
    assert captured["language"] == "es"
    assert captured["key_scale"] == "C major"
    assert captured["time_signature"] == "4/4"
    assert captured["seed"] == 7
    assert captured["steps"] == 20
    assert captured["guidance"] == 6.5
    assert captured["model"] == "acestep-v15-turbo"


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


def test_lyrics_only_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "canturia.cli.lyrics_only",
        lambda *args, **kwargs: LyricResult(
            lyrics="[Verse]\npreview words",
            provider="ollama",
            model="qwen3.5:4b",
        ),
    )
    result = runner.invoke(
        app, ["lyrics", "a song about rain", "--base-url", "http://ace"]
    )
    assert result.exit_code == 0
    assert "preview words" in result.output
    assert "qwen3.5:4b" in result.output


def test_compare_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "canturia.cli.compare_lyrics",
        lambda *args, **kwargs: [
            LyricResult(
                lyrics="[Verse]\nfrom ollama",
                provider="ollama",
                model="qwen3.5:4b",
            ),
            LyricResult(lyrics="", provider="acestep", error="LM off"),
        ],
    )
    result = runner.invoke(
        app, ["compare", "a song about rain", "--base-url", "http://ace"]
    )
    assert result.exit_code == 0
    assert "from ollama" in result.output
    assert "LM off" in result.output


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


def test_library_command(tmp_path: Path) -> None:
    audio = tmp_path / "saved.mp3"
    audio.write_bytes(b"ID3saved")
    audio.with_suffix(".mp3.json").write_text(
        json.dumps(
            {
                "source_text": "a saved song",
                "genre": "folk",
                "duration": 30,
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["library", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "a saved song" in result.output
    assert "saved.mp3" in result.output


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
        "canturia.cli.lyricist_choices",
        lambda settings: [
            {
                "name": "ollama",
                "label": "Ollama (local)",
                "model": "qwen3.5:4b",
                "models": ["qwen3.5:4b"],
                "available": True,
                "error": None,
            },
            {
                "name": "acestep",
                "label": "ACE-Step LM (experimental)",
                "model": "ACE-Step 5Hz LM",
                "models": [],
                "available": False,
                "error": "off",
            },
        ],
    )
    result = runner.invoke(app, ["health", "--base-url", "http://ace"])
    assert result.exit_code == 0
    assert "acestep-v15-turbo" in result.output
    assert "Ollama (local)" in result.output
    assert "qwen3.5:4b" in result.output


def test_missing_text_is_an_error() -> None:
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 2
