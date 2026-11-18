from __future__ import annotations

import json
from pathlib import Path

import pytest

from canturia.core import (
    Generation,
    audio_extension,
    build_request,
    generate,
    genre_prompt,
    save_song,
    slugify,
    validate_duration,
)
from canturia.providers import SongRequest, SongResult


def test_genre_prompt_preset_and_details() -> None:
    prompt = genre_prompt("folk", "close mic, warm room")
    assert prompt.startswith("gentle acoustic folk")
    assert prompt.endswith("close mic, warm room")


def test_genre_prompt_free_text() -> None:
    assert genre_prompt("bedroom psych pop", "tape hiss") == (
        "bedroom psych pop, tape hiss"
    )


def test_duration_bounds() -> None:
    assert validate_duration(10) == 10.0
    assert validate_duration("600") == 600.0
    with pytest.raises(ValueError):
        validate_duration(9.9)
    with pytest.raises(ValueError):
        validate_duration(601)
    with pytest.raises(ValueError):
        validate_duration("soon")


def test_build_request_lyrics_and_describe() -> None:
    lyrics = build_request("lyrics", "  [Verse]\nhi\n", "folk", "warm", 30)
    assert lyrics.lyrics == "[Verse]\nhi"
    assert lyrics.sample_query is None
    assert lyrics.duration == 30.0

    described = build_request("describe", "a song about rain", "indie", "", 45)
    assert described.sample_query == "a song about rain"
    assert described.lyrics == ""
    assert described.prompt.startswith("indie folk-pop")


def test_build_request_rejects_empty_and_bad_mode() -> None:
    with pytest.raises(ValueError):
        build_request("lyrics", "   ", "folk")
    with pytest.raises(ValueError):
        build_request("sing", "words", "folk")


def test_slugify() -> None:
    assert slugify("Folk — Morning Light!") == "folk-morning-light"
    assert slugify("   ") == "song"


def test_audio_extension() -> None:
    assert audio_extension(b"ID3fake", "song.mp3") == ".mp3"
    assert audio_extension(b"RIFFxxxxWAVE", "unknown") == ".wav"
    assert audio_extension(b"xxxx", "song.flac") == ".flac"
    assert audio_extension(b"xxxx", "song") == ".mp3"


def _generation(text: str = "a song about rain") -> Generation:
    request = SongRequest(prompt="indie folk-pop", duration=30, sample_query=text)
    return Generation(
        songs=[],
        mode="describe",
        genre="indie",
        style="warm",
        text=text,
        style_prompt="indie folk-pop",
        duration=30,
        request=request,
    )


def test_save_song_writes_audio_and_sidecar(tmp_path: Path) -> None:
    generation = _generation()
    song = SongResult(
        data=b"ID3fake-audio",
        file_path="/app/outputs/song.mp3",
        prompt="indie folk-pop",
        lyrics="la la",
        metas={"bpm": 96, "duration": 30},
        remote_name="song.mp3",
        duration=30,
    )
    path, sidecar = save_song(generation, song, out_dir=tmp_path)
    assert path == tmp_path / "indie-a-song-about-rain.mp3"
    assert path.read_bytes() == b"ID3fake-audio"
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["mode"] == "describe"
    assert metadata["genre"] == "indie"
    assert metadata["metas"]["bpm"] == 96


def test_save_song_never_overwrites(tmp_path: Path) -> None:
    generation = _generation()
    song = SongResult(
        data=b"ID3one",
        file_path="/app/outputs/song.mp3",
        prompt="p",
        lyrics="l",
        remote_name="song.mp3",
    )
    first, _ = save_song(generation, song, out_dir=tmp_path)
    song2 = SongResult(
        data=b"ID3two",
        file_path="/app/outputs/song.mp3",
        prompt="p",
        lyrics="l",
        remote_name="song.mp3",
    )
    second, _ = save_song(generation, song2, out_dir=tmp_path)
    assert first != second
    assert first.read_bytes() == b"ID3one"
    assert second.read_bytes() == b"ID3two"


def test_generate_builds_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[SongRequest] = []

    class FakeClient:
        def generate(self, request: SongRequest, on_progress=None) -> list[SongResult]:
            captured.append(request)
            if on_progress:
                on_progress("working")
            return [
                SongResult(
                    data=b"ID3x",
                    file_path="/app/outputs/x.mp3",
                    prompt=request.prompt,
                    lyrics=request.lyrics,
                    remote_name="x.mp3",
                )
            ]

    monkeypatch.setattr(
        "canturia.core.client_from_settings", lambda settings: FakeClient()
    )
    settings = {
        "base_url": "http://test",
        "genre": "folk",
        "style": "close mic",
        "duration": 30,
        "model": None,
    }
    result = generate(
        "lyrics",
        "[Verse]\nhello",
        settings,
        duration=45,
    )
    assert result.duration == 45
    assert captured[0].lyrics == "[Verse]\nhello"
    assert captured[0].prompt == "gentle acoustic folk, warm vocals, fingerpicked guitar, close mic"
    assert len(result.songs) == 1
