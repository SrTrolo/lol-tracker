"""Sends messages to a Discord webhook (no bot needed)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path

import requests

CONTENT_TYPES = {".png": "image/png", ".gif": "image/gif"}


def send(webhook_url: str, text: str, filename: str, data: bytes,
         roles: Sequence[str] = (), users: Sequence[str] = ()) -> None:
    """Post the message with the card attached.

    Only the given roles / users are pinged; any other mention stays silent.
    """
    pings = " ".join([f"<@&{r}>" for r in roles] + [f"<@{u}>" for u in users])
    content = f"{pings} {text}" if pings else text
    allowed = {"parse": [], "roles": list(roles), "users": list(users)}
    content_type = CONTENT_TYPES[Path(filename).suffix]
    _post(webhook_url, {"content": content, "allowed_mentions": allowed},
          {"files[0]": (filename, data, content_type)})


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
