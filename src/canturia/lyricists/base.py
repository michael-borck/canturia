"""The small interface every lyricist provider implements."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class LyricistError(Exception):
    """Raised when a lyricist cannot produce usable lyrics."""


@dataclass(frozen=True)
class LyricRequest:
    topic: str
    genre: str
    style: str
    duration: float
    language: str = "en"


@dataclass
class LyricResult:
    lyrics: str
    provider: str
    model: str | None = None
    caption: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


class Lyricist(Protocol):
    name: str

    def write(
        self,
        request: LyricRequest,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> LyricResult: ...
