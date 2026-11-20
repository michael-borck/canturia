from __future__ import annotations

import json
from pathlib import Path

import pytest

from canturia.library import (
    LibraryError,
    delete_song,
    list_songs,
    resolve_song,
)


def make_song(root: Path, name: str = "song.mp3", **meta) -> Path:
    path = root / name
    path.write_bytes(b"ID3fake")
    data = {
        "source_text": "a warm song about the sea",
        "genre": "folk",
        "lyrics_writer": "ollama",
        "lyricist_model": "qwen3.5:4b",
        "duration": 30,
        "lyrics": "[Verse]\nhello",
        "created": "2026-11-19T09:00:00+00:00",
        **meta,
    }
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    return path


def test_list_songs_newest_first(tmp_path: Path) -> None:
    make_song(tmp_path, "old.mp3", created="2026-11-18T09:00:00+00:00")
    make_song(
        tmp_path,
        "new.mp3",
        source_text="a birthday song for grandma",
        created="2026-11-19T09:00:00+00:00",
        lyrics_warnings=["Repeated lines"],
    )
    (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")

    songs = list_songs(tmp_path)
    assert [song["id"] for song in songs] == ["new.mp3", "old.mp3"]
    assert songs[0]["title"] == "a birthday song for grandma"
    assert songs[0]["lyrics_warnings"] == ["Repeated lines"]
    assert songs[1]["genre"] == "folk"


def test_song_without_sidecar_still_lists(tmp_path: Path) -> None:
    (tmp_path / "untitled.wav").write_bytes(b"RIFFxxxxWAVE")
    songs = list_songs(tmp_path)
    assert len(songs) == 1
    assert songs[0]["title"] == "Untitled"


def test_resolve_and_delete_song(tmp_path: Path) -> None:
    path = make_song(tmp_path)
    assert resolve_song(tmp_path, "song.mp3") == path.resolve()
    delete_song(tmp_path, "song.mp3")
    assert not path.exists()
    assert not path.with_suffix(path.suffix + ".json").exists()
    with pytest.raises(LibraryError):
        resolve_song(tmp_path, "song.mp3")


def test_resolve_refuses_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.mp3"
    outside.write_bytes(b"ID3fake")
    with pytest.raises(LibraryError):
        resolve_song(tmp_path, "../outside.mp3")
    with pytest.raises(LibraryError):
        resolve_song(tmp_path, ".hidden.mp3")
