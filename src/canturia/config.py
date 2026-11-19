"""Layered configuration for Canturía.

Layers, later wins:

1. Built-in defaults
2. ``~/.canturia.yaml``  — server URL + credentials, set once
3. ``./canturia.yaml``   — per-directory overrides (or an explicit ``--config``)
4. CLI flags             — applied by the CLI on top of the loaded config

Secrets are referenced as ``${VAR}`` and expanded from the environment, so no
plaintext keys need to live in config files.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""


DEFAULT_CONFIG: dict[str, Any] = {
    "base_url": None,
    "api_key": None,
    "username": None,
    "password": None,
    "model": None,
    "timeout": 900,
    "request_timeout": 60,
    "poll_interval": 2.0,
    "genre": "folk",
    "style": "",
    "duration": 30,
    "vocal_language": "en",
    "thinking": True,
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "model": None,
        "timeout": 90,
    },
    "serve": {
        "host": "127.0.0.1",
        "port": 2268,
        "password": None,
        "out_dir": "~/Music/Canturia",
    },
}

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_ENV_OVERRIDES: dict[str, str] = {
    "base_url": "CANTURIA_BASE_URL",
    "api_key": "CANTURIA_API_KEY",
    "username": "CANTURIA_USERNAME",
    "password": "CANTURIA_PASSWORD",
    "model": "CANTURIA_MODEL",
    "timeout": "CANTURIA_TIMEOUT",
    "poll_interval": "CANTURIA_POLL_INTERVAL",
    "genre": "CANTURIA_GENRE",
    "duration": "CANTURIA_DURATION",
    "vocal_language": "CANTURIA_VOCAL_LANGUAGE",
    "thinking": "CANTURIA_THINKING",
}

_OLLAMA_ENV_OVERRIDES: dict[str, str] = {
    "base_url": "CANTURIA_OLLAMA_URL",
    "model": "CANTURIA_OLLAMA_MODEL",
    "timeout": "CANTURIA_OLLAMA_TIMEOUT",
}

_SERVE_ENV_OVERRIDES: dict[str, str] = {
    "host": "CANTURIA_HOST",
    "port": "CANTURIA_PORT",
    "password": "CANTURIA_SERVE_PASSWORD",
    "out_dir": "CANTURIA_OUT_DIR",
}


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` references in configuration values."""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def _first_existing(*candidates: Path) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def find_home_config() -> Path | None:
    """The user-level config (~/.canturia.yaml)."""
    return _first_existing(
        Path.home() / ".canturia.yaml",
        Path.home() / ".canturia.yml",
    )


def find_project_config() -> Path | None:
    """The directory-level config (./canturia.yaml)."""
    return _first_existing(
        Path("./canturia.yaml"),
        Path("./canturia.yml"),
    )


def _read_config_file(config_file: Path) -> dict[str, Any] | None:
    try:
        with open(config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {config_file}: {e}") from e
    except OSError as e:
        raise ConfigurationError(f"Error reading {config_file}: {e}") from e
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Config file {config_file} must contain a YAML mapping"
        )
    return data


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two config dicts (override wins)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration by layering defaults, home, and project files."""
    config = copy.deepcopy(DEFAULT_CONFIG)

    sources: list[Path] = []
    if home_config := find_home_config():
        sources.append(home_config)
    if config_path:
        explicit = Path(config_path)
        if not explicit.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        sources.append(explicit)
    elif project_config := find_project_config():
        sources.append(project_config)

    for source in sources:
        file_config = _read_config_file(source)
        if file_config:
            config = merge_configs(config, file_config)

    return expand_env_vars(config)


def normalize_base_url(value: str) -> str:
    """Accept ``host:port`` or a URL and return a usable http(s) base URL."""
    url = value.strip().rstrip("/")
    if not url:
        raise ConfigurationError("ACE-Step base_url is empty.")
    if "://" not in url:
        url = f"http://{url}"
    if not url.startswith(("http://", "https://")):
        raise ConfigurationError(
            f"ACE-Step base_url must start with http:// or https:// (got {value!r})"
        )
    return url


def _as_float(value: Any, name: str, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ConfigurationError(f"{name} must be a number (got {value!r})") from e


def _env_value(env_name: str) -> str | None:
    value = os.getenv(env_name)
    return value if value not in (None, "") else None


def _as_bool(value: Any, name: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false (got {value!r})")


def resolve_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Effective ACE-Step connection settings (everything except ``serve``)."""
    settings = {k: v for k, v in config.items() if k != "serve"}
    for key, env_name in _ENV_OVERRIDES.items():
        value = _env_value(env_name)
        if value is not None:
            settings[key] = value

    base_url = settings.get("base_url")
    if not base_url:
        raise ConfigurationError(
            "No ACE-Step server configured. Set 'base_url' in "
            "~/.canturia.yaml (run 'canturia --init-config' for a template), "
            "set CANTURIA_BASE_URL, or pass --base-url."
        )
    settings["base_url"] = normalize_base_url(str(base_url))
    settings["timeout"] = _as_float(settings.get("timeout"), "timeout", 900.0)
    settings["request_timeout"] = _as_float(
        settings.get("request_timeout"), "request_timeout", 60.0
    )
    settings["poll_interval"] = _as_float(
        settings.get("poll_interval"), "poll_interval", 2.0
    )
    settings["thinking"] = _as_bool(
        settings.get("thinking"), "thinking", True
    )
    settings["vocal_language"] = str(settings.get("vocal_language") or "en")
    ollama = settings.get("ollama")
    if not isinstance(ollama, dict):
        settings["ollama"] = dict(DEFAULT_CONFIG["ollama"])
    return settings


def resolve_ollama_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Effective local lyricist settings (Ollama)."""
    ollama = dict(DEFAULT_CONFIG["ollama"])
    configured = config.get("ollama")
    if isinstance(configured, dict):
        ollama = merge_configs(ollama, configured)
    for key, env_name in _OLLAMA_ENV_OVERRIDES.items():
        value = _env_value(env_name)
        if value is not None:
            ollama[key] = value

    base_url = ollama.get("base_url") or "http://127.0.0.1:11434"
    ollama["base_url"] = normalize_base_url(str(base_url))
    ollama["timeout"] = _as_float(ollama.get("timeout"), "ollama.timeout", 90.0)
    model = str(ollama.get("model") or "").strip()
    ollama["model"] = model or None
    return ollama


def resolve_serve_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Effective web-server settings."""
    serve = dict(DEFAULT_CONFIG["serve"])
    configured = config.get("serve")
    if isinstance(configured, dict):
        serve = merge_configs(serve, configured)
    for key, env_name in _SERVE_ENV_OVERRIDES.items():
        value = _env_value(env_name)
        if value is not None:
            serve[key] = value

    out_dir = serve.get("out_dir") or "~/Music/Canturia"
    serve["out_dir"] = str(Path(os.path.expanduser(str(out_dir))))
    try:
        serve["port"] = int(serve.get("port") or 2268)
    except (TypeError, ValueError) as e:
        raise ConfigurationError("serve.port must be an integer") from e
    return serve


EXAMPLE_CONFIG = """\
# Canturía configuration
#
# Layered, later wins:
#   1. built-in defaults
#   2. ~/.canturia.yaml   (server URL, credentials — set once)
#   3. ./canturia.yaml    (per-directory overrides; or pass --config FILE)
#   4. CLI flags          (e.g. --base-url, --genre)
#
# Secrets: reference environment variables as ${VAR} — no plaintext keys.

# The ACE-Step API. This is the LAN address used during setup; change it when
# the service moves behind a proxy.
base_url: http://192.168.20.120:8002

# Auth (pick one). ACE-Step accepts a Bearer token; a reverse proxy can use
# HTTP Basic instead. Both are optional while the service is LAN-only.
# api_key: "${ACESTEP_API_KEY}"       # Authorization: Bearer ...
# username: admin                     # Authorization: Basic ...
# password: "${ACESTEP_PASSWORD}"

# Longer than a normal request: the first cold generation may download weights.
timeout: 900
poll_interval: 2

# Defaults for the CLI and web form.
genre: folk
style: ""
duration: 30

# The local lyricist used by the topic box. Ollama writes the lyrics on this
# machine, then ACE-Step sings them. Pull a chat model first, e.g.
#   ollama pull qwen3.5:4b
# Leave model empty to auto-pick a sensible chat model from /api/tags.
ollama:
  base_url: http://127.0.0.1:11434
  model: qwen3.5:4b
  timeout: 90

# Fixed for the family app; still honoured exactly on the lyrics path.
vocal_language: en
thinking: true

serve:
  host: 127.0.0.1
  port: 2268
  # Shared password for the web UI when hosted beyond localhost. Leave unset
  # locally; set it here or via CANTURIA_SERVE_PASSWORD when exposing the app.
  # password: "${CANTURIA_SERVE_PASSWORD}"
  out_dir: ~/Music/Canturia
"""


def save_example_config(path: str = "canturia.yaml") -> Path:
    """Write an example configuration file and return its path."""
    target = Path(path)
    if target.exists():
        raise ConfigurationError(f"Refusing to overwrite existing {target}")
    target.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    return target
