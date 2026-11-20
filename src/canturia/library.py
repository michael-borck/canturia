"""Saved-song library: scan the output folder and its JSON sidecars."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


class LibraryError(Exception):
    """Raised when a library item is missing or outside the library."""


def _read_sidecar(audio: Path) -> dict[str, Any]:
    sidecar = audio.with_suffix(audio.suffix + ".json")
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _title(metadata: dict[str, Any], audio: Path) -> str:
    source = str(metadata.get("source_text") or "").strip()
    if source:
        for line in source.splitlines():
            line = line.strip()
            if line and not line.startswith("["):
                return line
    prompt = str(metadata.get("prompt") or "").strip()
    return prompt or audio.stem.replace("-", " ").title()


def list_songs(out_dir: Path | str) -> list[dict[str, Any]]:
    """Return saved songs, newest first, with sidecar metadata where present."""
    root = Path(out_dir).expanduser()
    if not root.is_dir():
        return []
    songs: list[dict[str, Any]] = []
    for audio in root.iterdir():
        if not audio.is_file() or audio.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        metadata = _read_sidecar(audio)
        created = str(metadata.get("created") or "")
        if not created:
            created = datetime.fromtimestamp(
                audio.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        songs.append(
            {
                "id": audio.name,
                "filename": audio.name,
                "title": _title(metadata, audio),
                "genre": metadata.get("genre") or "",
                "style": metadata.get("style") or "",
                "mode": metadata.get("mode") or "",
                "lyrics_writer": metadata.get("lyrics_writer")
                or metadata.get("lyricist")
                or "",
                "lyricist_model": metadata.get("lyricist_model") or "",
                "lyrics_warnings": metadata.get("lyrics_warnings") or [],
                "duration": metadata.get("duration"),
                "lyrics": metadata.get("lyrics") or "",
                "prompt": metadata.get("prompt") or "",
                "created": created,
                "size": audio.stat().st_size,
            }
        )
    songs.sort(key=lambda item: str(item["created"]), reverse=True)
    return songs


def resolve_song(out_dir: Path | str, song_id: str) -> Path:
    """Resolve a library filename, refusing traversal or unknown types."""
    root = Path(out_dir).expanduser().resolve()
    name = Path(song_id).name
    if not name or name != song_id or name.startswith("."):
        raise LibraryError("Bad song name")
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise LibraryError("No such saved song")
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise LibraryError("Not an audio file")
    return path


def delete_song(out_dir: Path | str, song_id: str) -> Path:
    """Delete one saved song and its sidecar."""
    path = resolve_song(out_dir, song_id)
    sidecar = path.with_suffix(path.suffix + ".json")
    path.unlink()
    if sidecar.exists():
        sidecar.unlink()
    return path


def reveal_folder(path: Path | str) -> None:
    """Open a folder in the platform file manager (desktop mode only)."""
    target = str(Path(path).expanduser())
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", target])
