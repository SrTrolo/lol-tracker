"""Picks a random meme from memes/win or memes/loss."""

from __future__ import annotations

import random
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent / "memes"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def pick(result: str) -> Path | None:
    """Return a random meme file to send after the card, or None if the folder is empty."""
    folder = FOLDER / result
    if not folder.is_dir():
        return None
    candidates = [f for f in folder.iterdir() if f.suffix.lower() in EXTENSIONS]
    return random.choice(candidates) if candidates else None
