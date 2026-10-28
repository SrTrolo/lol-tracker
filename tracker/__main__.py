"""LoL match tracker → Discord.

Usage:
  python -m tracker                         normal check (what GitHub Actions runs)
  python -m tracker --demo                  render sample cards into output/ without Riot or Discord
  python -m tracker --test 1                post the latest match of player 1 (to check the setup works)
  python -m tracker --test "Name#TAG"       same, for any Riot ID
  python -m tracker --dry-run               do everything, but save cards to output/ instead of sending
"""

from __future__ import annotations

import argparse
import hmac
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
from .match import MatchData, Rank, parse, rank_for
from .riot import QUEUES, RANKED_QUEUES, DataDragon, InvalidKey, NotFound, RiotAPI, RiotError

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"
PLAYERS_FILE = ROOT / "private" / "players.yaml"
OUTPUT = ROOT / "output"
MAX_SEEN = 100

# What a player can set in players.yaml; anything they leave out comes from config.yaml
PLAYER_SETTINGS = ("region", "queues", "show", "skip_remakes", "messages")

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
    cfg.setdefault("default_region", "euw")
    cfg.setdefault("queues", ["soloq", "flex"])
    cfg.setdefault("show", "both")
    cfg.setdefault("skip_remakes", True)
    cfg.setdefault("timezone", "Europe/Madrid")
    cfg.setdefault("language", "es")
    cfg.setdefault("matches_per_check", 5)
    cfg["memes"] = cfg.get("memes") or {}
    cfg["memes"].setdefault("enabled", True)
    cfg["messages"] = {"win": ["🏆 **{player}** — {champion} ({kda})"],
                       "loss": ["💀 **{player}** — {champion} ({kda})"],
                       **_messages(cfg.get("messages"), "config.yaml")}
    cfg["show"] = _show(cfg["show"], "config.yaml")
    cfg["_queue_ids"] = _queue_ids(cfg["queues"], "config.yaml")
    cfg["players"] = [_player(p, f"player {n}", cfg) for n, p in enumerate(_players(cfg), 1)]

    cfg["mentions"] = cfg.get("mentions") or {}
    for kind in ("roles", "users"):
        ids = [str(i).strip() for i in cfg["mentions"].get(kind) or []]
        if not all(i.isdigit() for i in ids):
            sys.exit(f"config.yaml: mentions.{kind} must be Discord IDs (numbers), e.g. \"123456789012345678\"")
        cfg["mentions"][kind] = ids
    return cfg


def _players(cfg: dict) -> list:
    """The players from the private repo, or from config.yaml (public) when there's no private repo."""
    if PLAYERS_FILE.exists():
        data = yaml.safe_load(PLAYERS_FILE.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, list) else data.get("players") or []  # with or without "players:"
    if os.environ.get("GITHUB_ACTIONS") and os.environ.get("PRIVATE_REPO"):
        sys.exit("players.yaml is missing: the private repo couldn't be fetched, or it has no players.yaml.")
    if cfg.get("players"):
        log.warning("Players are read from config.yaml, which anyone can see. "
                    "Move them to players.yaml in your private repo (see README).")
    return cfg.get("players") or []


def _player(p: dict, label: str, cfg: dict) -> dict:
    """A player's settings: what they set in players.yaml, and the config.yaml defaults for the rest."""
    if not isinstance(p, dict) or not p.get("name") or not p.get("tag"):
        sys.exit(f"{label} needs a name and a tag")
    unknown = sorted(set(p) - {"name", "tag", *PLAYER_SETTINGS})
    if unknown:
        sys.exit(f"{label}: unknown setting '{unknown[0]}'. Options: {', '.join(PLAYER_SETTINGS)}")
    return {
        "label": label,  # how logs refer to them: they're public, so no names
        "name": str(p["name"]).strip(),
        "tag": str(p["tag"]).strip().lstrip("#"),
        "region": str(p.get("region") or cfg["default_region"]),
        "queue_ids": _queue_ids(p["queues"], label) if "queues" in p else cfg["_queue_ids"],
        "show": _show(p["show"], label) if "show" in p else cfg["show"],
        "skip_remakes": p.get("skip_remakes", cfg["skip_remakes"]),
        "messages": {**cfg["messages"], **_messages(p.get("messages"), label)},  # win and loss separately
    }


def _show(value, where: str) -> str:
    show = str(value).lower().strip()
    if show not in ("wins", "losses", "both"):
        sys.exit(f"{where}: 'show' must be wins, losses or both (currently '{show}')")
    return show


def _queue_ids(names, where: str) -> list[int]:
    ids = []
    for q in [names] if isinstance(names, str) else names or []:
        q = str(q).lower().strip()
        if q not in QUEUES:
            sys.exit(f"{where}: unknown queue '{q}'. Options: {', '.join(QUEUES)}")
        ids.append(QUEUES[q])
    return ids


def _messages(value, where: str) -> dict[str, list[str]]:
    """The win / loss texts that are set, each as a list (a single text is fine too)."""
    value = value or {}
    if not isinstance(value, dict) or set(value) - {"win", "loss"}:
        sys.exit(f"{where}: 'messages' can only have win and loss, each with a list of texts")
    return {result: [texts] if isinstance(texts, str) else list(texts) for result, texts in value.items() if texts}


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


def _private(value: str) -> str:
    """value, unrecognisable without STATE_KEY: state.json is public and mustn't reveal who is tracked."""
    return hmac.new(os.environ.get("STATE_KEY", "").encode(), value.encode(), "sha256").hexdigest()[:16]


def find_player(target: str, cfg: dict) -> dict:
    """A tracked player by number (1, 2…) or Riot ID. A Riot ID that isn't tracked gets the defaults."""
    target = target.strip()
    if target.isdigit():
        if not 1 <= int(target) <= len(cfg["players"]):
            sys.exit(f"There's no player {target}: there are {len(cfg['players'])}.")
        return cfg["players"][int(target) - 1]
    if "#" not in target:
        sys.exit("Use the player's number (1, 2…) or the Name#TAG format")
    name, tag = (x.strip() for x in target.rsplit("#", 1))
    for p in cfg["players"]:
        if player_key(p["name"], p["tag"]) == player_key(name, tag):
            return p
    return _player({"name": name, "tag": tag}, "the test player", cfg)


# ───────────────────────── posting ─────────────────────────

def passes_filter(m: MatchData, p: dict) -> bool:
    if m.remake and p["skip_remakes"]:
        return False
    if p["show"] == "wins":
        return m.win
    if p["show"] == "losses":
        return not m.win
    return True


def message_text(m: MatchData, messages: dict, language: str) -> str:
    t = i18n.get(language)
    template = random.choice(messages[m.result])
    values = defaultdict(str, player=m.riot_id, queue=t["queue_short"].get(m.queue_id, t["game"]),
                         champion=m.champion, kda=m.kda_text,
                         position=t["positions"].get(m.position, "?"), duration=m.duration)
    return template.format_map(values)


def attach_ranks(matches: list[MatchData], api: RiotAPI, puuid: str, region: str, who: str) -> None:
    """Add the player's current rank to their ranked matches (one request; without it if Riot fails)."""
    ranked = [m for m in matches if m.queue_id in RANKED_QUEUES]
    if not ranked:
        return
    try:
        entries = api.league_entries(puuid, region)
    except RiotError as e:
        log.warning("Could not read the rank of %s (%s); posting without it.", who, e)
        return
    for m in ranked:
        m.rank = rank_for(entries, m.queue_id)


def render(m: MatchData, cfg: dict, dd: DataDragon) -> tuple[str, bytes]:
    """The card for a match, with a random meme, as (file name, contents)."""
    meme = memes.pick(m.result, card.MEME_SIZE) if cfg["memes"]["enabled"] else None
    banner = card.draw(m, dd, cfg["language"], meme)
    return banner.encode()


def post(m: MatchData, p: dict, cfg: dict, dd: DataDragon, dry_run: bool) -> None:
    filename, data = render(m, cfg, dd)
    text = message_text(m, p["messages"], cfg["language"])
    if dry_run:
        OUTPUT.mkdir(exist_ok=True)
        path = OUTPUT / f"{m.match_id}_{m.player}{Path(filename).suffix}"
        path.write_bytes(data)
        log.info("[dry run] %s → %s", text, path.name)
        return
    webhook.send(os.environ["DISCORD_WEBHOOK_URL"], text, filename, data,
                 cfg["mentions"]["roles"], cfg["mentions"]["users"])
    log.info("Sent the %s card of %s.", m.result, p["label"])


# ───────────────────────── modes ─────────────────────────

def check(cfg: dict, api: RiotAPI, dd: DataDragon, dry_run: bool) -> int:
    state = load_state()
    state.setdefault("players", {})
    problems = 0

    if not cfg["players"]:
        log.warning("No players to track (players.yaml in the private repo) — nothing to do.")

    for p in cfg["players"]:
        name, tag, region, who = p["name"], p["tag"], p["region"], p["label"]
        entry = state["players"].setdefault(_private(player_key(name, tag)), {"seen": [], "initialized": False})

        try:
            puuid = api.account(name, tag, region)["puuid"]
            ids = []
            for queue in p["queue_ids"]:
                ids += api.match_ids(puuid, region, queue, int(cfg["matches_per_check"]))
        except InvalidKey:
            raise
        except NotFound:
            log.error("The Riot ID of %s doesn't exist in %s. Check players.yaml.", who, region)
            problems += 1
            continue
        except RiotError as e:
            log.error("Error looking up %s: %s", who, e)
            problems += 1
            continue

        hidden = {i: _private(i) for i in ids}  # state.json only keeps these
        seen = set(entry["seen"])
        if not entry["initialized"]:
            # First time we see this player: don't post their history, just remember it.
            entry["seen"] = _remember(entry["seen"], list(hidden.values()))
            entry["initialized"] = True
            log.info("%s added. Their matches will be posted from now on.", who)
            continue

        new_matches = []
        for mid in dict.fromkeys(i for i in ids if hidden[i] not in seen):
            try:
                md = parse(api.match(mid, region), puuid, dd, cfg["timezone"])
            except RiotError as e:
                log.error("Could not read a match of %s: %s", who, e)
                problems += 1
                continue
            if md:
                new_matches.append(md)
            else:
                seen.add(hidden[mid])

        attach_ranks(new_matches, api, puuid, region, who)
        for md in sorted(new_matches, key=lambda x: x.ended_at):  # oldest first
            if passes_filter(md, p):
                try:
                    post(md, p, cfg, dd, dry_run)
                except Exception as e:  # noqa: BLE001
                    log.error("Could not post a match of %s: %s", who, e)
                    problems += 1
                    break  # it will be retried on the next run
            else:
                log.info("Skipping a %s of %s (show: %s%s).", md.result, who, p["show"],
                         ", remake" if md.remake else "")
            seen.add(hidden[md.match_id])

        entry["seen"] = _remember(entry["seen"], [hidden[i] for i in ids if hidden[i] in seen])

    if not dry_run:
        save_state(state)
    return problems


def test(target: str, cfg: dict, api: RiotAPI, dd: DataDragon, dry_run: bool) -> None:
    p = find_player(target, cfg)
    region = p["region"]
    puuid = api.account(p["name"], p["tag"], region)["puuid"]
    ids = []
    for queue in p["queue_ids"]:
        ids += api.match_ids(puuid, region, queue, 1)
    matches = [parse(api.match(i, region), puuid, dd, cfg["timezone"]) for i in ids]
    matches = [m for m in matches if m]
    if not matches:
        sys.exit(f"{p['label']} has no recent matches in their queues.")
    latest = max(matches, key=lambda x: x.ended_at)
    log.info("Test: latest match of %s (%s)", p["label"], latest.result)
    attach_ranks([latest], api, puuid, region, p["label"])
    post(latest, p, cfg, dd, dry_run)


def demo(cfg: dict) -> None:
    """Sample cards with made-up data, to preview the design and your memes."""
    dd = DataDragon(i18n.LOCALES.get(cfg["language"], "en_US"))
    now = datetime.now(ZoneInfo(cfg["timezone"])).replace(second=0, microsecond=0)

    samples = [
        MatchData("DEMO_WIN", True, False, "YourFriend", "EUW", *dd.champion(103, "Ahri"), 16, "MIDDLE",
                  11, 3, 9, 214, 31 * 60 + 42, 28450, 13820, 21, 0.62, 420, now - timedelta(minutes=40),
                  [3285, 3020, 4645, 3089, 3157, 0, 3363], spells=[4, 14], role_item=1206,
                  rank=Rank("EMERALD", "IV", 69)),
        MatchData("DEMO_LOSS", False, False, "YourFriend", "EUW", *dd.champion(157, "Yasuo"), 13, "TOP",
                  2, 11, 3, 156, 27 * 60 + 5, 12030, 8410, 9, 0.24, 440, now,
                  [6672, 3006, 1055, 1036, 0, 0, 3340], spells=[4, 12], role_item=1221,
                  rank=Rank("MASTER", "", 245)),
    ]
    OUTPUT.mkdir(exist_ok=True)
    for m in samples:
        filename, data = render(m, cfg, dd)
        path = OUTPUT / f"demo_{m.result}{Path(filename).suffix}"
        path.write_bytes(data)
        print(f"✔ {path.relative_to(ROOT)}\n  Message: {message_text(m, cfg['messages'], cfg['language'])}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="LoL match tracker → Discord")
    ap.add_argument("--demo", action="store_true", help="render sample cards without Riot or Discord")
    ap.add_argument("--test", metavar="N|NAME#TAG", default=os.environ.get("TEST_PLAYER") or None,
                    help="post the latest match of player N (1, 2…) or of any Riot ID")
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
    if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("STATE_KEY"):
        log.warning("STATE_KEY is missing: without it, state.json can reveal who is tracked (see README).")

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
