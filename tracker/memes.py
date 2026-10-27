"""Picks a random meme from memes/win or memes/loss."""

from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image

log = logging.getLogger("tracker")

FOLDER = Path(__file__).resolve().parent.parent / "memes"
STATIC = {".png", ".jpg", ".jpeg", ".webp"}
ANIMATED = {".gif"}


def pick(result: str) -> tuple[Image.Image | None, Path | None]:
    """Return (static image to embed in the card, gif to attach). One of them, or neither."""
    folder = FOLDER / result
    if not folder.is_dir():
        return None, None
    candidates = [f for f in folder.iterdir() if f.suffix.lower() in STATIC | ANIMATED]
    if not candidates:
        return None, None
    chosen = random.choice(candidates)
    if chosen.suffix.lower() in ANIMATED:
        return None, chosen
    try:
        return Image.open(chosen).convert("RGBA"), None
    except Exception as e:  # noqa: BLE001
        log.warning("Could not open meme %s (%s)", chosen.name, e)
        return None, None
