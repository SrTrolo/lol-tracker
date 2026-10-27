"""Encodes an animated card as a GIF.

All frames share one 256-colour palette and only the meme area changes between them,
so the file stays small and the rest of the card doesn't flicker.
"""

from __future__ import annotations

import io

from PIL import Image

PALETTE_SAMPLES = 10  # meme frames used, next to the full card, to choose the palette
DITHER = Image.Dither.FLOYDSTEINBERG


def encode(still: Image.Image, patches: list[Image.Image], origin: tuple[int, int],
           durations: list[int]) -> bytes:
    """still: the whole card with the first frame. patches: the meme area of every frame, placed at origin."""
    palette = _palette(still, patches)
    first = still.quantize(palette=palette, dither=DITHER)
    frames = [first]
    for patch in patches[1:]:
        frame = first.copy()
        frame.paste(patch.quantize(palette=palette, dither=DITHER), origin)
        frames.append(frame)

    buf = io.BytesIO()
    first.save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)
    return buf.getvalue()


def _palette(still: Image.Image, patches: list[Image.Image]) -> Image.Image:
    """The 256 colours that best cover the card and a sample of the meme frames."""
    samples = patches[::max(1, len(patches) // PALETTE_SAMPLES)]
    width, height = patches[0].size
    sheet = Image.new("RGB", (max(still.width, width * len(samples)), still.height + height))
    sheet.paste(still, (0, 0))
    for i, patch in enumerate(samples):
        sheet.paste(patch, (i * width, still.height))
    return sheet.quantize(256, method=Image.Quantize.FASTOCTREE)
