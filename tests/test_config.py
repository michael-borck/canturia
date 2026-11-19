from __future__ import annotations

from pathlib import Path

import pytest

from canturia.config import (
    ConfigurationError,
    expand_env_vars,
    load_config,
    merge_configs,
    normalize_base_url,
    resolve_ollama_settings,
    resolve_serve_settings,
    resolve_settings,
)


def test_expand_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANTURIA_TEST_TOKEN", "s3cret")
    value = {"api_key": "${CANTURIA_TEST_TOKEN}", "list": ["${CANTURIA_TEST_TOKEN}"]}
    assert expand_env_vars(value) == {"api_key": "s3cret", "list": ["s3cret"]}


def test_merge_configs_is_deep() -> None:
    base = {"serve": {"host": "127.0.0.1", "port": 1}, "genre": "folk"}
    override = {"serve": {"port": 2}}
    merged = merge_configs(base, override)
    assert merged == {"serve": {"host": "127.0.0.1", "port": 2}, "genre": "folk"}


def test_normalize_base_url() -> None:
    assert normalize_base_url("192.168.1.2:8002/") == "http://192.168.1.2:8002"
    assert normalize_base_url("https://music.example.org/") == (
        "https://music.example.org"
    )
    with pytest.raises(ConfigurationError):
        normalize_base_url("ftp://music.example.org")


def test_layered_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home.yaml"
    home.write_text("base_url: http://home\ngenre: pop\n", encoding="utf-8")
    project = tmp_path / "project.yaml"
    project.write_text("genre: rock\n", encoding="utf-8")
    monkeypatch.setattr("canturia.config.find_home_config", lambda: home)
    monkeypatch.setattr("canturia.config.find_project_config", lambda: project)

    config = load_config()
    assert config["base_url"] == "http://home"
    assert config["genre"] == "rock"
    assert config["serve"]["port"] == 2268


def test_resolve_settings_requires_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("canturia.config.find_home_config", lambda: None)
    monkeypatch.setattr("canturia.config.find_project_config", lambda: None)
    monkeypatch.delenv("CANTURIA_BASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="No ACE-Step server"):
        resolve_settings(load_config())


def test_resolve_settings_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANTURIA_BASE_URL", "music.local:8002")
    monkeypatch.setenv("CANTURIA_API_KEY", "token")
    monkeypatch.setenv("CANTURIA_TIMEOUT", "120")
    settings = resolve_settings({"base_url": "http://ignored"})
    assert settings["base_url"] == "http://music.local:8002"
    assert settings["api_key"] == "token"
    assert settings["timeout"] == 120.0
    assert settings["thinking"] is True
    assert settings["vocal_language"] == "en"


def test_resolve_settings_language_and_bool() -> None:
    settings = resolve_settings(
        {
            "base_url": "http://ace",
            "vocal_language": "es",
            "thinking": "false",
        }
    )
    assert settings["vocal_language"] == "es"
    assert settings["thinking"] is False


def test_resolve_ollama_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANTURIA_OLLAMA_MODEL", "gemma3:4b")
    ollama = resolve_ollama_settings(
        {
            "ollama": {
                "base_url": "localhost:11434",
                "timeout": "30",
            }
        }
    )
    assert ollama["base_url"] == "http://localhost:11434"
    assert ollama["model"] == "gemma3:4b"
    assert ollama["timeout"] == 30.0


def test_resolve_serve_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANTURIA_SERVE_PASSWORD", "hunter2")
    config = {
        "serve": {
            "host": "0.0.0.0",
            "port": "9000",
            "out_dir": str(tmp_path / "music"),
        }
    }
    serve = resolve_serve_settings(config)
    assert serve["host"] == "0.0.0.0"
    assert serve["port"] == 9000
    assert serve["password"] == "hunter2"
    assert serve["out_dir"] == str(tmp_path / "music")
