"""Compatibility re-export; shared helpers live in canturia.lyrics_text."""

from canturia.lyrics_text import SYSTEM_PROMPT, build_user_prompt, clean_lyrics

__all__ = ["SYSTEM_PROMPT", "build_user_prompt", "clean_lyrics"]
