"""Picks a random meme from win/ or loss/ in the private repo and loads it for the card."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

FOLDER = Path(__file__).resolve().parent.parent / "private"
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FRAMES = 120  # longer animations are thinned out to keep the card light

log = logging.getLogger("tracker")


@dataclass
class Meme:
    frames: list[Image.Image]   # square RGBA frames, already at the size they're drawn
    durations: list[int]        # milliseconds each frame is shown


def pick(result: str, size: int) -> Meme | None:
    """A random meme for this result, cropped to size×size, or None if there's none to use."""
    path = _random_file(result)
    if path is None:
        return None
    try:
        return _load(path, size)
    except (OSError, ValueError) as e:  # a broken file shouldn't stop the card from being posted
        log.warning("Could not read meme %s (%s); posting without it.", path.name, e)
        return None


def _random_file(result: str) -> Path | None:
    folder = FOLDER / result
    if not folder.is_dir():
        return None
    candidates = [f for f in folder.iterdir() if f.suffix.lower() in EXTENSIONS]
    return random.choice(candidates) if candidates else None


def _load(path: Path, size: int) -> Meme:
    """Every frame (one for still images), keeping at most MAX_FRAMES without changing the total length."""
    frames, durations = [], []
    with Image.open(path) as img:
        step = math.ceil(getattr(img, "n_frames", 1) / MAX_FRAMES)
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            duration = frame.info.get("duration") or 100
            if i % step:
                durations[-1] += duration  # skipped frame: the previous one stays on screen instead
                continue
            frames.append(ImageOps.fit(frame.convert("RGBA"), (size, size), Image.Resampling.LANCZOS))
            durations.append(duration)
    return Meme(frames, durations)
