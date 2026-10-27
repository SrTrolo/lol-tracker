"""Turns a Match-V5 response into the data the card needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .riot import RANKED_QUEUES, DataDragon

APEX_TIERS = ("MASTER", "GRANDMASTER", "CHALLENGER")  # no divisions


@dataclass
class Rank:
    tier: str               # Riot tier id (e.g. "EMERALD")
    division: str           # "I"–"IV", or "" for apex tiers
    lp: int


@dataclass
class MatchData:
    match_id: str
    win: bool
    remake: bool
    player: str
    tag: str
    champion_id: str        # Data Dragon id (e.g. "MonkeyKing")
    champion: str           # display name (e.g. "Wukong")
    level: int
    position: str           # TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY or ""
    kills: int
    deaths: int
    assists: int
    cs: int
    duration_s: int
    damage: int
    gold: int
    vision: int
    kill_participation: float | None
    queue_id: int
    ended_at: datetime
    items: list[int] = field(default_factory=list)
    rank: Rank | None = None  # current rank in this queue, for ranked games

    @property
    def result(self) -> str:
        return "win" if self.win else "loss"

    @property
    def riot_id(self) -> str:
        return f"{self.player}#{self.tag}" if self.tag else self.player

    @property
    def kda_text(self) -> str:
        return f"{self.kills}/{self.deaths}/{self.assists}"

    @property
    def kda_ratio(self) -> float | None:
        """None means a perfect KDA (no deaths)."""
        if self.deaths == 0:
            return None
        return (self.kills + self.assists) / self.deaths

    @property
    def duration(self) -> str:
        m, s = divmod(self.duration_s, 60)
        return f"{m}:{s:02d}"

    @property
    def cs_per_min(self) -> str:
        return f"{self.cs / max(self.duration_s / 60, 1):.1f}"


def parse(match: dict, puuid: str, dd: DataDragon, tz: str = "Europe/Madrid") -> MatchData | None:
    info = match["info"]
    me = next((p for p in info["participants"] if p["puuid"] == puuid), None)
    if me is None:
        return None

    team_kills = sum(p["kills"] for p in info["participants"] if p["teamId"] == me["teamId"])
    kp = (me["kills"] + me["assists"]) / team_kills if team_kills else None

    duration = int(info.get("gameDuration", 0))
    if "gameEndTimestamp" not in info:  # very old matches reported duration in ms
        duration //= 1000
    end_ms = info.get("gameEndTimestamp") or (info["gameStartTimestamp"] + duration * 1000)
    ended_at = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).astimezone(ZoneInfo(tz))

    cid, name = dd.champion(me["championId"], me.get("championName", "?"))
    position = me.get("teamPosition") or me.get("individualPosition") or ""

    return MatchData(
        match_id=match["metadata"]["matchId"],
        win=bool(me["win"]),
        remake=bool(me.get("gameEndedInEarlySurrender")) or duration < 240,
        player=me.get("riotIdGameName") or me.get("summonerName") or "?",
        tag=me.get("riotIdTagline") or "",
        champion_id=cid,
        champion=name,
        level=int(me.get("champLevel", 0)),
        position=position if position in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY") else "",
        kills=me["kills"],
        deaths=me["deaths"],
        assists=me["assists"],
        cs=int(me.get("totalMinionsKilled", 0)) + int(me.get("neutralMinionsKilled", 0)),
        duration_s=duration,
        damage=int(me.get("totalDamageDealtToChampions", 0)),
        gold=int(me.get("goldEarned", 0)),
        vision=int(me.get("visionScore", 0)),
        kill_participation=kp,
        queue_id=int(info.get("queueId", 0)),
        ended_at=ended_at,
        items=[int(me.get(f"item{i}", 0)) for i in range(7)],
    )


def rank_for(entries: list[dict], queue_id: int) -> Rank | None:
    """Pick the rank of the given queue from League-V4 entries (None if unranked or not a ranked queue)."""
    queue_type = RANKED_QUEUES.get(queue_id)
    entry = next((e for e in entries if e.get("queueType") == queue_type), None)
    if entry is None:
        return None
    tier = entry["tier"]
    division = "" if tier in APEX_TIERS else entry.get("rank", "")
    return Rank(tier, division, int(entry.get("leaguePoints", 0)))
