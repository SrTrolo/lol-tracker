"""Minimal clients for the official Riot Games API and Data Dragon (images)."""

from __future__ import annotations

import io
import logging
import time
from urllib.parse import quote

import requests
from PIL import Image

log = logging.getLogger("tracker")

# Player region → regional cluster used by Account-V1 and Match-V5
CLUSTERS = {
    "euw": "europe", "eune": "europe", "tr": "europe", "ru": "europe", "me": "europe",
    "na": "americas", "br": "americas", "lan": "americas", "las": "americas",
    "kr": "asia", "jp": "asia",
    "oce": "sea", "sg": "sea", "tw": "sea", "vn": "sea", "ph": "sea", "th": "sea",
}

# Player region → platform host used by League-V4 (PH and TH were merged into SG2)
PLATFORMS = {
    "euw": "euw1", "eune": "eun1", "tr": "tr1", "ru": "ru", "me": "me1",
    "na": "na1", "br": "br1", "lan": "la1", "las": "la2",
    "kr": "kr", "jp": "jp1",
    "oce": "oc1", "sg": "sg2", "tw": "tw2", "vn": "vn2", "ph": "sg2", "th": "sg2",
}

# Config name → Riot queueId
QUEUES = {
    "soloq": 420,
    "flex": 440,
    "normal": 400,
    "quickplay": 490,
    "aram": 450,
}

# Ranked queueId → League-V4 queueType
RANKED_QUEUES = {
    420: "RANKED_SOLO_5x5",
    440: "RANKED_FLEX_SR",
}


class RiotError(Exception):
    pass


class InvalidKey(RiotError):
    pass


class NotFound(RiotError):
    pass


def _lookup(table: dict[str, str], region: str) -> str:
    region = (region or "euw").lower().strip()
    if region not in table:
        raise RiotError(f"Unknown region '{region}'. Valid: {', '.join(table)}")
    return table[region]


def cluster_for(region: str) -> str:
    return _lookup(CLUSTERS, region)


def platform_for(region: str) -> str:
    return _lookup(PLATFORMS, region)


class RiotAPI:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = api_key.strip()

    def _get(self, host: str, path: str, params: dict | None = None):
        """GET from a regional cluster (e.g. "europe") or a platform (e.g. "euw1").

        Errors never include the path: it has the Riot ID or puuid, and the logs on GitHub are public.
        """
        url = f"https://{host}.api.riotgames.com{path}"
        for attempt in range(5):
            try:
                r = self.session.get(url, params=params, timeout=20)
            except requests.RequestException as e:
                log.warning("Network error talking to Riot (%s), retrying…", type(e).__name__)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429:  # rate limited: wait as long as Riot says
                wait = min(int(r.headers.get("Retry-After", "5")), 120)
                log.info("Riot rate limit hit, waiting %ss…", wait)
                time.sleep(wait)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise InvalidKey(
                    "Riot rejected the API key (401/403). Development keys expire every 24 h: "
                    "generate a new one and update the RIOT_API_KEY secret."
                )
            if r.status_code == 404:
                raise NotFound("Riot answered 404 (not found)")
            if r.status_code >= 400:
                raise RiotError(f"Riot answered HTTP {r.status_code}")
            return r.json()
        raise RiotError("Riot did not respond properly after several attempts")

    def account(self, name: str, tag: str, region: str) -> dict:
        cluster = cluster_for(region)
        account_cluster = "asia" if cluster == "sea" else cluster  # Account-V1 has no 'sea'
        return self._get(
            account_cluster,
            f"/riot/account/v1/accounts/by-riot-id/{quote(name, safe='')}/{quote(tag, safe='')}",
        )

    def match_ids(self, puuid: str, region: str, queue: int, count: int = 5) -> list[str]:
        return self._get(
            cluster_for(region),
            f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
            {"queue": queue, "start": 0, "count": count},
        )

    def match(self, match_id: str, region: str) -> dict:
        return self._get(cluster_for(region), f"/lol/match/v5/matches/{match_id}")

    def league_entries(self, puuid: str, region: str) -> list[dict]:
        """The player's current rank in every ranked queue they've played this season."""
        return self._get(platform_for(region), f"/lol/league/v4/entries/by-puuid/{puuid}")


DDRAGON = "https://ddragon.leagueoflegends.com"
CDRAGON = "https://raw.communitydragon.org/latest/plugins"


class DataDragon:
    """Champion, item and summoner spell images (Riot's public CDN) and rank emblems (CommunityDragon,
    the client's assets).

    Without a connection everything returns None and the card falls back to placeholders.
    """

    def __init__(self, locale: str = "en_US"):
        self.session = requests.Session()
        self.version: str | None = None
        self.champions: dict[int, tuple[str, str]] = {}  # numeric key → (id, display name)
        self.spells: dict[int, str] = {}                 # numeric key → id (e.g. 4 → "SummonerFlash")
        self._cache: dict[str, Image.Image | None] = {}
        try:
            self.version = self.session.get(f"{DDRAGON}/api/versions.json", timeout=15).json()[0]
            data = self.session.get(
                f"{DDRAGON}/cdn/{self.version}/data/{locale}/champion.json", timeout=20
            ).json()["data"]
            for c in data.values():
                self.champions[int(c["key"])] = (c["id"], c["name"])
            spells = self.session.get(
                f"{DDRAGON}/cdn/{self.version}/data/{locale}/summoner.json", timeout=20
            ).json()["data"]
            for s in spells.values():
                self.spells[int(s["key"])] = s["id"]
        except Exception as e:  # noqa: BLE001
            log.warning("Could not load Data Dragon (%s). Placeholder images will be used.", e)
            self.version = None

    def champion(self, champion_id: int, fallback_name: str) -> tuple[str, str]:
        """Return (image id, display name)."""
        return self.champions.get(int(champion_id), (fallback_name, fallback_name))

    def _image(self, url: str) -> Image.Image | None:
        if url in self._cache:
            return self._cache[url]
        img = None
        if self.version:
            try:
                r = self.session.get(url, timeout=20)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            except Exception as e:  # noqa: BLE001
                log.warning("Could not download %s (%s)", url, e)
        self._cache[url] = img
        return img

    def champion_icon(self, cid: str):
        return self._image(f"{DDRAGON}/cdn/{self.version}/img/champion/{cid}.png")

    def splash(self, cid: str):
        return self._image(f"{DDRAGON}/cdn/img/champion/splash/{cid}_0.jpg")

    def item(self, item_id: int):
        if not item_id:
            return None
        return self._image(f"{DDRAGON}/cdn/{self.version}/img/item/{item_id}.png")

    def spell(self, spell_id: int):
        if spell_id not in self.spells:
            return None
        return self._image(f"{DDRAGON}/cdn/{self.version}/img/spell/{self.spells[spell_id]}.png")

    def rank_emblem(self, tier: str):
        return self._image(f"{CDRAGON}/rcp-fe-lol-shared-components/global/default/{tier.lower()}.png")
