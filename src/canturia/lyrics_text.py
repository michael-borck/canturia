"""Shared lyric-writing prompts and cleanup for every lyricist provider."""

from __future__ import annotations

import re
from collections import Counter

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


def repetition_warnings(lyrics: str) -> list[str]:
    """Flag obvious lyric degeneration (repeated lines or a tiny vocabulary)."""
    lines = [
        re.sub(r"\s+", " ", line.strip().lower())
        for line in (lyrics or "").splitlines()
        if line.strip() and not _TAG_RE.match(line)
    ]
    warnings: list[str] = []
    if len(lines) >= 8:
        unique_lines = len(set(lines)) / len(lines)
        if unique_lines < 0.6:
            warnings.append(
                f"Repeated lines: only {unique_lines:.0%} of the lyric lines "
                "are different."
            )
    repeated = [
        line
        for line, count in Counter(lines).items()
        if count >= 3 and len(line.split()) > 2
    ]
    if repeated:
        warnings.append("At least one line repeats three or more times.")
    words = re.findall(r"[a-z']+", " ".join(lines))
    if len(words) >= 30:
        unique_words = len(set(words)) / len(words)
        if unique_words < 0.35:
            warnings.append(
                f"Small vocabulary: only {unique_words:.0%} of the words are "
                "different."
            )
    return warnings


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
