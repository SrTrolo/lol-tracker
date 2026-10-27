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


def send(webhook_url: str, text: str, card: Image.Image, gif: Path | None = None) -> None:
    buf = io.BytesIO()
    card.save(buf, "PNG", optimize=True)
    files = {"files[0]": ("card.png", buf.getvalue(), "image/png")}

    if gif is not None:
        if gif.stat().st_size <= MAX_FILE_SIZE:
            files["files[1]"] = (gif.name, gif.read_bytes(), "image/gif")
        else:
            log.warning("GIF %s is larger than 10 MB; sending the card without it.", gif.name)

    payload = {"content": text, "allowed_mentions": {"parse": []}}
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
