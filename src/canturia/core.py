"""Core: turn a topic or lyrics plus a genre into audio files on disk."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canturia.config import resolve_ollama_settings
from canturia.languages import language_name
from canturia.lyricists import build_lyricist, lyricist_options
from canturia.lyricists.base import (
    LyricistError,
    LyricRequest,
    LyricResult,
)
from canturia.providers import (
    AceStepClient,
    OllamaClient,
    OllamaError,
    SongRequest,
    SongResult,
)

DURATION_MIN = 10.0
DURATION_MAX = 600.0

#: Genre key -> (display label, base style prompt).
GENRES: dict[str, tuple[str, str]] = {
    "folk": ("Folk", "gentle acoustic folk, warm vocals, fingerpicked guitar"),
    "pop": ("Pop", "uplifting pop, catchy hook, polished production"),
    "rock": ("Rock", "guitar-driven rock, live drums, energetic vocal"),
    "indie": ("Indie", "indie folk-pop, intimate vocal, jangly guitars"),
    "lofi": ("Lo-fi", "lo-fi hip hop, warm vinyl crackle, mellow beat"),
    "electronic": ("Electronic", "electronic pop, synth arpeggios, tight beat"),
    "hiphop": ("Hip-hop", "hip hop, boom-bap drums, confident vocal"),
    "soul": ("Soul", "soulful R&B, warm keys, smooth vocal"),
    "country": ("Country", "country, acoustic guitar, pedal steel, storytelling"),
    "jazz": ("Jazz", "jazz, upright bass, brushed drums, smoky vocal"),
    "classical": ("Classical", "classical chamber arrangement, strings and piano"),
    "ambient": ("Ambient", "ambient, slow pads, no drums, atmospheric"),
    "metal": ("Metal", "heavy metal, distorted guitars, double-kick drums"),
    "lullaby": ("Lullaby", "gentle lullaby, music box, soft vocal"),
}

MODES = {"topic", "lyrics", "describe"}

_AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


@dataclass
class Generation:
    """One finished generation: audio plus the inputs that produced it."""

    songs: list[SongResult]
    mode: str
    genre: str
    style: str
    text: str
    style_prompt: str
    duration: float
    request: SongRequest
    lyricist: str | None = None
    lyricist_model: str | None = None
    lyrics_warnings: list[str] = field(default_factory=list)


def genre_options() -> list[dict[str, str]]:
    """Genre presets for the web UI and docs."""
    return [
        {"key": key, "label": label, "prompt": prompt}
        for key, (label, prompt) in GENRES.items()
    ]


def genre_prompt(genre: str, style: str | None = None) -> str:
    """Turn a genre key (or free-text genre) plus details into a style prompt."""
    key = (genre or "").strip().lower()
    base = GENRES[key][1] if key in GENRES else (genre or "").strip()
    details = (style or "").strip()
    prompt = ", ".join(part for part in (base, details) if part)
    return prompt or "pop"


def validate_duration(value: Any) -> float:
    """Return a duration in seconds, or raise a user-facing ValueError."""
    try:
        duration = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Duration must be a number (got {value!r})") from e
    if not DURATION_MIN <= duration <= DURATION_MAX:
        raise ValueError(
            f"Duration must be between {int(DURATION_MIN)} and "
            f"{int(DURATION_MAX)} seconds (got {duration:g})"
        )
    return duration


def validate_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(
            f"Mode must be 'topic', 'lyrics', or 'describe' (got {mode!r})"
        )
    return mode


def build_request(
    mode: str,
    text: str,
    genre: str,
    style: str | None = None,
    duration: Any = 30,
    model: str | None = None,
    *,
    thinking: bool = True,
    vocal_language: str = "en",
    bpm: int | None = None,
    key_scale: str | None = None,
    time_signature: str | None = None,
    seed: int | None = None,
    inference_steps: int | None = None,
    guidance_scale: float | None = None,
    instrumental: bool = False,
) -> SongRequest:
    """Build the ACE-Step request for lyrics or the raw describe path.

    Topic mode is resolved in :func:`generate` because it first asks Ollama
    for lyrics, then reuses the lyrics path.
    """
    validate_mode(mode)
    if mode == "topic" and not instrumental:
        raise ValueError("Topic mode is resolved by generate(), not build_request().")
    source = (text or "").strip()
    if not source and not instrumental:
        raise ValueError("Give me lyrics, or a topic with 'topic'.")
    if not (genre or "").strip():
        raise ValueError("Pick a genre, or type your own genre.")
    seconds = validate_duration(duration)
    prompt = genre_prompt(genre, style)
    advanced = {
        "bpm": int(bpm) if bpm is not None else None,
        "key_scale": (key_scale or "").strip() or None,
        "time_signature": (time_signature or "").strip() or None,
        "seed": int(seed) if seed is not None else None,
        "inference_steps": int(inference_steps)
        if inference_steps is not None
        else None,
        "guidance_scale": float(guidance_scale)
        if guidance_scale is not None
        else None,
        "instrumental": instrumental,
    }
    if instrumental:
        if source and mode in ("describe", "topic"):
            prompt = f"{prompt}, {source}"
        return SongRequest(
            prompt=prompt,
            lyrics="[Instrumental]",
            duration=seconds,
            model=model,
            thinking=thinking,
            vocal_language=vocal_language,
            **advanced,
        )
    if mode == "describe":
        language = language_name(vocal_language)
        # The 5Hz LM ignores vocal_language in sample mode. The only lever
        # that moved it in testing was putting the language in the description
        # itself. This is still best-effort, not a contract.
        lower = source.lower()
        already_asks = (
            f"in {language.lower()}" in lower
            or f"{language.lower()} lyrics" in lower
        )
        if already_asks:
            sample_query = f"{source}, about {seconds:g} seconds long"
        else:
            sample_query = (
                f"{source}, with lyrics in {language} and {language} vocals, "
                f"about {seconds:g} seconds long"
            )
        return SongRequest(
            prompt=prompt,
            duration=seconds,
            sample_query=sample_query,
            model=model,
            thinking=thinking,
            vocal_language=vocal_language,
            **advanced,
        )
    return SongRequest(
        prompt=prompt,
        lyrics=source,
        duration=seconds,
        model=model,
        thinking=thinking,
        vocal_language=vocal_language,
        **advanced,
    )


def client_from_settings(settings: dict[str, Any]) -> AceStepClient:
    """Build an ACE-Step client from resolved connection settings."""
    return AceStepClient(
        base_url=str(settings["base_url"]),
        api_key=settings.get("api_key"),
        username=settings.get("username"),
        password=settings.get("password"),
        timeout=float(settings.get("timeout") or 900),
        request_timeout=float(settings.get("request_timeout") or 60),
        poll_interval=float(settings.get("poll_interval") or 2),
    )


def health(settings: dict[str, Any]) -> dict[str, Any]:
    """Ask the configured server for its health/readiness payload."""
    return client_from_settings(settings).health()


def ollama_status(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the local lyricist's readiness and model list (never raises)."""
    try:
        ollama = resolve_ollama_settings(settings)
        client = OllamaClient(
            base_url=str(ollama["base_url"]),
            model=ollama.get("model"),
            timeout=min(float(ollama.get("timeout") or 90), 8),
        )
        models = client.models()
        model = client.model
        if not model:
            model = client.resolve_model() if models else None
        return {"ok": True, "model": model, "models": models, "error": None}
    except (OllamaError, ValueError) as e:
        return {"ok": False, "model": None, "models": [], "error": str(e)}


def lyrics(
    topic: str,
    settings: dict[str, Any],
    *,
    genre: str,
    style: str | None,
    duration: float,
    lyricist: str | None = None,
    language: str | None = None,
    on_progress: Any = None,
) -> LyricResult:
    """Write lyrics only, using the chosen lyricist."""
    subject = (topic or "").strip()
    if not subject:
        raise LyricistError("Give me a topic or a few words to write about.")
    writer = build_lyricist(lyricist, settings)
    request = LyricRequest(
        topic=subject,
        genre=genre,
        style=(style or "").strip(),
        duration=validate_duration(duration),
        language=language or str(settings.get("vocal_language") or "en"),
    )
    return writer.write(request, on_progress=on_progress)


def write_lyrics(
    topic: str,
    settings: dict[str, Any],
    *,
    genre: str,
    style: str | None,
    duration: float,
    lyricist: str | None = None,
    language: str | None = None,
    on_progress: Any = None,
) -> str:
    """Compatibility wrapper returning only the lyric text."""
    return lyrics(
        topic,
        settings,
        genre=genre,
        style=style,
        duration=duration,
        lyricist=lyricist,
        language=language,
        on_progress=on_progress,
    ).lyrics


def compare_lyrics(
    topic: str,
    settings: dict[str, Any],
    names: list[str],
    *,
    genre: str,
    style: str | None,
    duration: float,
    language: str | None = None,
    on_progress: Any = None,
) -> list[LyricResult]:
    """Run several lyricists, returning an error result for any failure."""
    results: list[LyricResult] = []
    for name in names:
        try:
            results.append(
                lyrics(
                    topic,
                    settings,
                    genre=genre,
                    style=style,
                    duration=duration,
                    lyricist=name,
                    language=language,
                    on_progress=on_progress,
                )
            )
        except Exception as exc:  # one provider must not stop the comparison
            results.append(
                LyricResult(lyrics="", provider=name, error=str(exc))
            )
    return results


def lyricist_choices(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Availability for each configured lyricist (for CLI/web status)."""
    return lyricist_options(settings)


def generate(
    mode: str,
    text: str,
    settings: dict[str, Any],
    *,
    genre: str | None = None,
    style: str | None = None,
    duration: Any = None,
    lyricist: str | None = None,
    bpm: int | None = None,
    key_scale: str | None = None,
    time_signature: str | None = None,
    seed: int | None = None,
    model: str | None = None,
    inference_steps: int | None = None,
    guidance_scale: float | None = None,
    instrumental: bool = False,
    vocal_language: str | None = None,
    on_progress: Any = None,
) -> Generation:
    """Generate one song (batch size 1) from lyrics or a topic."""
    chosen_genre = genre or str(settings.get("genre") or "folk")
    chosen_style = (
        style if style is not None else str(settings.get("style") or "")
    )
    chosen_duration = (
        duration if duration is not None else settings.get("duration") or 30
    )
    thinking = bool(settings.get("thinking", True))
    chosen_language = vocal_language or str(
        settings.get("vocal_language") or "en"
    )
    chosen_model = model or settings.get("model")
    advanced: dict[str, Any] = {
        "bpm": bpm,
        "key_scale": key_scale,
        "time_signature": time_signature,
        "seed": seed,
        "inference_steps": inference_steps,
        "guidance_scale": guidance_scale,
        "instrumental": instrumental,
    }

    source_text = (text or "").strip()
    writer_name: str | None
    writer_model: str | None = None
    if instrumental:
        writer_name = "instrumental"
        warnings = []
        request = build_request(
            mode,
            source_text,
            chosen_genre,
            chosen_style,
            chosen_duration,
            model=chosen_model,
            thinking=thinking,
            vocal_language=chosen_language,
            **advanced,
        )
    elif mode == "topic":
        written = lyrics(
            source_text,
            settings,
            genre=chosen_genre,
            style=chosen_style,
            duration=validate_duration(chosen_duration),
            lyricist=lyricist,
            language=chosen_language,
            on_progress=on_progress,
        )
        writer_name = written.provider
        writer_model = written.model
        warnings = list(written.warnings)
        request = build_request(
            "lyrics",
            written.lyrics,
            chosen_genre,
            chosen_style,
            chosen_duration,
            model=chosen_model,
            thinking=thinking,
            vocal_language=chosen_language,
            **advanced,
        )
    else:
        writer_name = "user" if mode == "lyrics" else "acestep"
        warnings = []
        if mode == "describe":
            writer_model = "ACE-Step 5Hz LM"
        request = build_request(
            mode,
            source_text,
            chosen_genre,
            chosen_style,
            chosen_duration,
            model=chosen_model,
            thinking=thinking,
            vocal_language=chosen_language,
            **advanced,
        )

    client = client_from_settings(settings)
    songs = client.generate(request, on_progress=on_progress)
    return Generation(
        songs=songs,
        mode=mode,
        genre=chosen_genre,
        style=chosen_style,
        text=source_text,
        style_prompt=request.prompt,
        duration=request.duration,
        request=request,
        lyricist=writer_name,
        lyricist_model=writer_model,
        lyrics_warnings=warnings,
    )


def slugify(text: str, max_length: int = 48) -> str:
    """Filesystem-safe slug for a default output name."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "song"


def unique_path(path: Path) -> Path:
    """Avoid clobbering existing files by appending -2, -3, ..."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find a free filename near {path}")


def audio_extension(data: bytes, remote_name: str = "") -> str:
    """Pick an extension from the remote name, then magic bytes, then mp3."""
    suffix = Path(remote_name).suffix.lower()
    if suffix in _AUDIO_SUFFIXES:
        return suffix
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return ".mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[:4] == b"fLaC":
        return ".flac"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[4:8] == b"ftyp":
        return ".m4a"
    return ".mp3"


def metadata_for(generation: Generation, song: SongResult) -> dict[str, Any]:
    """Reproducibility sidecar for one saved song."""
    writers = {
        "topic": "ollama",
        "lyrics": "user",
        "describe": "acestep",
    }
    return {
        "mode": generation.mode,
        "lyrics_writer": generation.lyricist
        or writers.get(generation.mode, "unknown"),
        "lyricist_model": generation.lyricist_model,
        "lyrics_warnings": generation.lyrics_warnings,
        "genre": generation.genre,
        "style": generation.style,
        "prompt": song.prompt,
        "lyrics": song.lyrics,
        "source_text": generation.text,
        "duration": generation.duration,
        "vocal_language": generation.request.vocal_language,
        "thinking": generation.request.thinking,
        "instrumental": generation.request.instrumental,
        "bpm": generation.request.bpm,
        "key_scale": generation.request.key_scale,
        "time_signature": generation.request.time_signature,
        "seed": generation.request.seed,
        "model": generation.request.model,
        "inference_steps": generation.request.inference_steps,
        "guidance_scale": generation.request.guidance_scale,
        "remote_file": song.file_path,
        "metas": song.metas,
        "created": datetime.now(timezone.utc).isoformat(),
    }


def write_metadata(song_path: Path, metadata: dict[str, Any]) -> Path:
    """Write a ``<song>.json`` sidecar next to the audio; return its path."""
    sidecar = song_path.with_suffix(song_path.suffix + ".json")
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return sidecar


def _default_name(generation: Generation) -> str:
    source = f"{generation.genre} {generation.text}"
    slug = slugify(source)
    return slug if slug != "song" else "song"


def save_song(
    generation: Generation,
    song: SongResult,
    out: str | None = None,
    out_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write one song and its sidecar; return ``(audio, metadata)``.

    ``out`` is an exact file. Without it, the song is named from the genre and
    words and written into ``out_dir`` (the current directory by default).
    Existing files are never overwritten.
    """
    extension = audio_extension(song.data, song.remote_name)
    if out:
        target = Path(out).expanduser()
        if target.parent != Path("."):
            target.parent.mkdir(parents=True, exist_ok=True)
        if not target.suffix:
            target = target.with_suffix(extension)
    else:
        base_dir = Path(out_dir).expanduser() if out_dir else Path(".")
        base_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(
            base_dir / Path(_default_name(generation)).with_suffix(extension)
        )

    target.write_bytes(song.data)
    sidecar = write_metadata(target, metadata_for(generation, song))
    return target, sidecar
