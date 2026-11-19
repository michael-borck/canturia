"""Shared lyric-writing prompts and cleanup for every lyricist provider."""

from __future__ import annotations

import re

from canturia.languages import language_name

SYSTEM_PROMPT = (
    "You are a concise, original lyricist. Write singable lyrics. "
    "Use [Verse], [Chorus], and [Bridge] section tags. "
    "Return only the lyrics: no title, explanation, notes, plans, "
    "or code fences."
)

_TAG_RE = re.compile(
    r"^\s*\[(Verse|Chorus|Bridge|Intro|Outro|Pre-Chorus)", re.IGNORECASE
)


def build_user_prompt(
    topic: str,
    *,
    genre: str,
    style: str | None,
    duration: float,
    language: str = "en",
) -> str:
    subject = (topic or "").strip()
    language_text = language_name(language)
    line_target = max(4, min(16, round(float(duration) / 5)))
    style_text = (style or "").strip()
    style_line = f"\nStyle details: {style_text}." if style_text else ""
    return (
        f"Write original {genre} song lyrics in {language_text} about: "
        f"{subject}\n"
        f"Aim for about {int(duration)} seconds of music, roughly "
        f"{line_target} lyric lines across the sections."
        f"{style_line}\n"
        "Include at least one [Verse] and one [Chorus]. "
        "Do not reuse existing songs. Return only the lyrics."
    )


def clean_lyrics(text: str) -> str:
    """Trim model chatter and make sure the result has a section tag."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    lines = text.splitlines()
    first_tag = next(
        (i for i, line in enumerate(lines) if _TAG_RE.match(line)), None
    )
    if first_tag is not None and first_tag > 0:
        lines = lines[first_tag:]
    text = "\n".join(lines).strip()

    if not text or "[instrumental]" in text.lower():
        return ""
    if not _TAG_RE.search(text):
        text = f"[Verse]\n{text}"
    return text
