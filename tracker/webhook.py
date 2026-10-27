"""Sends messages to a Discord webhook (no bot needed)."""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

import requests
from PIL import Image

log = logging.getLogger("tracker")

MAX_FILE_SIZE = 9_500_000  # Discord caps attachments at ~10 MB
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif"}


def send(webhook_url: str, text: str, card: Image.Image, meme: Path | None = None) -> None:
    """Post the card, then the meme (if any) as a separate message right after it."""
    buf = io.BytesIO()
    card.save(buf, "PNG", optimize=True)
    _post(webhook_url, {"content": text, "allowed_mentions": {"parse": []}},
          {"files[0]": ("card.png", buf.getvalue(), "image/png")})

    if meme is None:
        return
    if meme.stat().st_size > MAX_FILE_SIZE:
        log.warning("Meme %s is larger than 10 MB; skipping it.", meme.name)
        return
    content_type = CONTENT_TYPES.get(meme.suffix.lower(), "application/octet-stream")
    try:
        _post(webhook_url, {}, {"files[0]": (meme.name, meme.read_bytes(), content_type)})
    except Exception as e:  # noqa: BLE001
        # The card is already posted: don't fail, or the next run would post it again.
        log.warning("Could not send meme %s (%s)", meme.name, e)


def _post(webhook_url: str, payload: dict, files: dict) -> None:
    for attempt in range(4):
        r = requests.post(
            webhook_url,
            params={"wait": "true"},
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=30,
        )
        if r.status_code == 429:
            wait = float(r.json().get("retry_after", 2))
            time.sleep(min(wait, 30) + 0.5)
            continue
        if r.status_code in (401, 404):
            raise RuntimeError("Discord doesn't recognise the webhook (was it deleted?). Check DISCORD_WEBHOOK_URL.")
        if r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord did not accept the message after several attempts.")
