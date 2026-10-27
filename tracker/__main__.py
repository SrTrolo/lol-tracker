"""LoL match tracker → Discord.

Usage:
  python -m tracker                         normal check (what GitHub Actions runs)
  python -m tracker --demo                  render sample cards into output/ without Riot or Discord
  python -m tracker --test "Name#TAG"       post that player's latest match (to check the setup works)
  python -m tracker --dry-run               do everything, but save cards to output/ instead of sending
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import card, i18n, memes, webhook
from .match import MatchData, parse
from .riot import QUEUES, DataDragon, InvalidKey, NotFound, RiotAPI, RiotError

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"
OUTPUT = ROOT / "output"
MAX_SEEN = 100

log = logging.getLogger("tracker")


# ───────────────────────── config and state ─────────────────────────

def load_env() -> None:
    """Read a local .env file (for testing on your PC; GitHub uses secrets instead)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg["players"] = cfg.get("players") or []
    cfg.setdefault("default_region", "euw")
    cfg.setdefault("queues", ["soloq", "flex"])
    cfg.setdefault("show", "both")
    cfg.setdefault("skip_remakes", True)
    cfg.setdefault("timezone", "Europe/Madrid")
    cfg.setdefault("language", "es")
    cfg.setdefault("matches_per_check", 5)
    cfg["memes"] = cfg.get("memes") or {}
    cfg["memes"].setdefault("enabled", True)
    cfg["messages"] = cfg.get("messages") or {}
    cfg["messages"].setdefault("win", ["🏆 **{player}** — {champion} ({kda})"])
    cfg["messages"].setdefault("loss", ["💀 **{player}** — {champion} ({kda})"])

    show = str(cfg["show"]).lower().strip()
    if show not in ("wins", "losses", "both"):
        sys.exit(f"config.yaml: 'show' must be wins, losses or both (currently '{show}')")
    cfg["show"] = show

    queue_ids = []
    for q in cfg["queues"]:
        q = str(q).lower().strip()
        if q not in QUEUES:
            sys.exit(f"config.yaml: unknown queue '{q}'. Options: {', '.join(QUEUES)}")
        queue_ids.append(QUEUES[q])
    cfg["_queue_ids"] = queue_ids

    for p in cfg["players"]:
        if not p.get("name") or not p.get("tag"):
            sys.exit(f"config.yaml: every player needs a name and a tag (problem with: {p})")
    return cfg


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"players": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _remember(seen: list[str], new_ids: list[str]) -> list[str]:
    """Keep the most recent MAX_SEEN match ids, oldest first, without duplicates."""
    merged = list(dict.fromkeys(seen + [i for i in reversed(new_ids) if i not in seen]))
    return merged[-MAX_SEEN:]


def player_key(name: str, tag: str) -> str:
    return f"{name}#{tag}".lower()


def player_region(name: str, tag: str, cfg: dict) -> str:
    for p in cfg["players"]:
        if player_key(str(p["name"]), str(p["tag"])) == player_key(name, tag):
            return str(p.get("region") or cfg["default_region"])
    return str(cfg["default_region"])


# ───────────────────────── posting ─────────────────────────

def passes_filter(m: MatchData, cfg: dict) -> bool:
    if m.remake and cfg["skip_remakes"]:
        return False
    if cfg["show"] == "wins":
        return m.win
    if cfg["show"] == "losses":
        return not m.win
    return True


def message_text(m: MatchData, cfg: dict) -> str:
    t = i18n.get(cfg["language"])
    template = random.choice(cfg["messages"][m.result])
    values = defaultdict(str, player=m.riot_id, queue=t["queue_short"].get(m.queue_id, t["game"]),
                         champion=m.champion, kda=m.kda_text,
                         position=t["positions"].get(m.position, "?"), duration=m.duration)
    return template.format_map(values)


def post(m: MatchData, cfg: dict, dd: DataDragon, dry_run: bool) -> None:
    meme = memes.pick(m.result) if cfg["memes"]["enabled"] else None
    img = card.draw(m, dd, cfg["language"])
    text = message_text(m, cfg)
    if dry_run:
        OUTPUT.mkdir(exist_ok=True)
        path = OUTPUT / f"{m.match_id}_{m.player}.png"
        img.save(path)
        log.info("[dry run] %s → %s %s", text, path.name, f"+ {meme.name}" if meme else "")
        return
    webhook.send(os.environ["DISCORD_WEBHOOK_URL"], text, img, meme)
    log.info("Sent: %s", text)


# ───────────────────────── modes ─────────────────────────

def check(cfg: dict, api: RiotAPI, dd: DataDragon, dry_run: bool) -> int:
    state = load_state()
    state.setdefault("players", {})
    problems = 0

    if not cfg["players"]:
        log.warning("No players in config.yaml — nothing to do.")

    for p in cfg["players"]:
        name, tag = str(p["name"]).strip(), str(p["tag"]).strip().lstrip("#")
        region = str(p.get("region") or cfg["default_region"])
        entry = state["players"].setdefault(player_key(name, tag), {"seen": [], "initialized": False})

        try:
            puuid = api.account(name, tag, region)["puuid"]
            ids = []
            for queue in cfg["_queue_ids"]:
                ids += api.match_ids(puuid, region, queue, int(cfg["matches_per_check"]))
        except InvalidKey:
            raise
        except NotFound:
            log.error("Riot ID %s#%s doesn't exist in %s. Check config.yaml.", name, tag, region)
            problems += 1
            continue
        except RiotError as e:
            log.error("Error looking up %s#%s: %s", name, tag, e)
            problems += 1
            continue

        seen = set(entry["seen"])
        if not entry["initialized"]:
            # First time we see this player: don't post their history, just remember it.
            entry["seen"] = _remember(entry["seen"], ids)
            entry["initialized"] = True
            log.info("%s#%s added. Their matches will be posted from now on.", name, tag)
            continue

        new_matches = []
        for mid in dict.fromkeys(i for i in ids if i not in seen):
            try:
                md = parse(api.match(mid, region), puuid, dd, cfg["timezone"])
            except RiotError as e:
                log.error("Could not read match %s: %s", mid, e)
                problems += 1
                continue
            if md:
                new_matches.append(md)
            else:
                seen.add(mid)

        for md in sorted(new_matches, key=lambda x: x.ended_at):  # oldest first
            if passes_filter(md, cfg):
                try:
                    post(md, cfg, dd, dry_run)
                except Exception as e:  # noqa: BLE001
                    log.error("Could not post %s: %s", md.match_id, e)
                    problems += 1
                    break  # it will be retried on the next run
            else:
                log.info("Skipping %s for %s (show: %s%s).", md.result, md.riot_id, cfg["show"],
                         ", remake" if md.remake else "")
            seen.add(md.match_id)

        entry["seen"] = _remember(entry["seen"], [i for i in ids if i in seen])

    if not dry_run:
        save_state(state)
    return problems


def test(riot_id: str, cfg: dict, api: RiotAPI, dd: DataDragon, dry_run: bool) -> None:
    if "#" not in riot_id:
        sys.exit("Use the Name#TAG format")
    name, tag = (x.strip() for x in riot_id.rsplit("#", 1))
    region = player_region(name, tag, cfg)
    puuid = api.account(name, tag, region)["puuid"]
    ids = []
    for queue in cfg["_queue_ids"]:
        ids += api.match_ids(puuid, region, queue, 1)
    matches = [parse(api.match(i, region), puuid, dd, cfg["timezone"]) for i in ids]
    matches = [m for m in matches if m]
    if not matches:
        sys.exit(f"{riot_id} has no recent matches in the configured queues.")
    latest = max(matches, key=lambda x: x.ended_at)
    log.info("Test: latest match of %s (%s)", riot_id, latest.result)
    post(latest, cfg, dd, dry_run)


def demo(cfg: dict) -> None:
    """Sample cards with made-up data, to preview the design and your memes."""
    dd = DataDragon(i18n.LOCALES.get(cfg["language"], "en_US"))
    now = datetime.now(ZoneInfo(cfg["timezone"])).replace(second=0, microsecond=0)

    samples = [
        MatchData("DEMO_WIN", True, False, "YourFriend", "EUW", *dd.champion(103, "Ahri"), 16, "MIDDLE",
                  11, 3, 9, 214, 31 * 60 + 42, 28450, 13820, 21, 0.62, 420, now - timedelta(minutes=40),
                  [3285, 3020, 4645, 3089, 3157, 0, 3363]),
        MatchData("DEMO_LOSS", False, False, "YourFriend", "EUW", *dd.champion(157, "Yasuo"), 13, "TOP",
                  2, 11, 3, 156, 27 * 60 + 5, 12030, 8410, 9, 0.24, 440, now,
                  [6672, 3006, 1055, 1036, 0, 0, 3340]),
    ]
    OUTPUT.mkdir(exist_ok=True)
    for m in samples:
        meme = memes.pick(m.result) if cfg["memes"]["enabled"] else None
        img = card.draw(m, dd, cfg["language"])
        path = OUTPUT / f"demo_{m.result}.png"
        img.save(path)
        extra = f" (+ {meme.name} would be sent after it)" if meme else ""
        print(f"✔ {path.relative_to(ROOT)}{extra}\n  Message: {message_text(m, cfg)}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="LoL match tracker → Discord")
    ap.add_argument("--demo", action="store_true", help="render sample cards without Riot or Discord")
    ap.add_argument("--test", metavar="NAME#TAG", default=os.environ.get("TEST_RIOT_ID") or None,
                    help="post that player's latest match")
    ap.add_argument("--dry-run", action="store_true", help="save cards to output/ instead of sending them")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    load_env()
    cfg = load_config(Path(args.config))

    if args.demo:
        demo(cfg)
        return

    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        sys.exit("RIOT_API_KEY is missing (GitHub secret or .env file).")
    if not args.dry_run and not os.environ.get("DISCORD_WEBHOOK_URL", "").strip():
        sys.exit("DISCORD_WEBHOOK_URL is missing (GitHub secret or .env file).")

    api = RiotAPI(key)
    dd = DataDragon(i18n.LOCALES.get(cfg["language"], "en_US"))
    try:
        if args.test:
            test(args.test, cfg, api, dd, args.dry_run)
            return
        problems = check(cfg, api, dd, args.dry_run)
    except InvalidKey as e:
        sys.exit(f"❌ {e}")
    if problems:
        sys.exit(f"Finished with {problems} problem(s); see the messages above.")


if __name__ == "__main__":
    main()
