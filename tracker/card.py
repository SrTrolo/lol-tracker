"""Draws the win / loss card with Pillow."""

from __future__ import annotations

import io
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import gif, i18n
from .match import MatchData, Rank
from .memes import Meme
from .riot import DataDragon

log = logging.getLogger("tracker")

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

W, H = 1200, 560
PAD = 48
TEXT_RIGHT = 760   # text never goes past this point, so the splash art shows on the right

# Rows of the layout
TITLE_BASELINE = 136
META_Y = 152
ICON_Y, ICON_SIZE = 204, 150
ITEMS_Y, ITEM_SIZE, ITEM_GAP = 382, 44, 7
STATS_Y, STATS_H, STATS_GAP = 448, 82, 12

# Type sizes shared by several blocks
TITLE_SIZE = 132
NAME_SIZE, SUBTITLE_SIZE = 40, 24   # player name and the line under it; the rank block reuses both
NAME_TO_SUBTITLE = 16               # from the name's baseline to the top of the line under it

# Rank: emblem, tier and LP, centred in the column right of the text
RANK_LEFT, RANK_RIGHT, RANK_MARGIN = TEXT_RIGHT, W - PAD, 20
RANK_CX = (RANK_LEFT + RANK_RIGHT) // 2
EMBLEM_H, EMBLEM_GAP = 200, 22
HALO_DARKNESS = 0.55   # how much the halo behind the rank darkens the splash art (0–1)
HALO_GLOW = 60         # opacity of the tier-coloured glow behind the emblem

# Meme: a square sticker tucked under the end of the title
MEME_SIZE, MEME_BORDER, MEME_RADIUS = 100, 4, 14
MEME_OVERLAP = 20          # how far it slides under the last letter
TITLE_SHADOW_REACH = 32    # margin needed to redraw the title and its blurred shadow over each meme frame

MAX_BYTES = 9_500_000      # Discord caps attachments at ~10 MB

WHITE = (245, 246, 250)
GREY = (176, 182, 198)
DARK_GREY = (120, 126, 142)
BG = (12, 14, 20)
BADGE_BG = (16, 18, 26)
DEATHS_RED = (255, 96, 108)

ACCENT = {
    "win": (64, 170, 255),   # blue
    "loss": (255, 70, 85),   # red
}

# Main colour of each tier's emblem, for the glow behind it
TIER_COLORS = {
    "IRON": (140, 125, 120),
    "BRONZE": (180, 115, 80),
    "SILVER": (170, 185, 200),
    "GOLD": (230, 180, 75),
    "PLATINUM": (75, 195, 185),
    "EMERALD": (40, 205, 125),
    "DIAMOND": (100, 130, 245),
    "MASTER": (185, 95, 235),
    "GRANDMASTER": (235, 75, 70),
    "CHALLENGER": (110, 200, 245),
}


@dataclass
class Card:
    still: Image.Image                                          # the whole card (first frame if animated)
    patches: list[Image.Image] = field(default_factory=list)    # meme area of every frame
    origin: tuple[int, int] = (0, 0)                            # where the patches go on the card
    durations: list[int] = field(default_factory=list)          # milliseconds per frame

    @property
    def animated(self) -> bool:
        return len(self.patches) > 1

    def encode(self) -> tuple[str, bytes]:
        """File name and contents to post: a GIF when the meme is animated, otherwise a PNG."""
        if self.animated:
            data = gif.encode(self.still, self.patches, self.origin, self.durations)
            if len(data) <= MAX_BYTES:
                return "card.gif", data
            log.warning("The animated card is %.1f MB, too big for Discord; sending it still.", len(data) / 1e6)
        buf = io.BytesIO()
        self.still.save(buf, "PNG", optimize=True)
        return "card.png", buf.getvalue()


# ───────────────────────── fonts ─────────────────────────

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def display(size: int):
    return _font("BebasNeue-Regular.ttf", size)


def poppins(weight: str, size: int):
    return _font(f"Poppins-{weight}.ttf", size)


# ───────────────────────── drawing helpers ─────────────────────────

def _cover(img: Image.Image, size: tuple[int, int], centering=(0.5, 0.35)) -> Image.Image:
    return ImageOps.fit(img.convert("RGBA"), size, Image.Resampling.LANCZOS, centering=centering)


def _gradient(size, start_alpha: int, end_alpha: int, color=(0, 0, 0), horizontal=True) -> Image.Image:
    """A colour layer whose transparency fades left→right (or top→bottom)."""
    mask = Image.linear_gradient("L")  # top black → bottom white
    if horizontal:
        mask = mask.rotate(90, expand=True)  # left black → right white
    mask = mask.resize(size).point(lambda v: int(start_alpha + (end_alpha - start_alpha) * v / 255))
    layer = Image.new("RGBA", size, color + (0,))
    layer.putalpha(mask)
    return layer


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    img = img.convert("RGBA")
    mask = _rounded_mask(img.size, radius)
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mask))
    return img


def _translucent(canvas: Image.Image, draw_fn) -> None:
    """Draw semi-transparent shapes on a separate layer so they blend properly."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    canvas.alpha_composite(layer)


def _shadow(canvas: Image.Image, mask: Image.Image, xy, blur: int, alpha: int = 160) -> None:
    """A soft black shadow with the shape of mask (an "L" image), placed at xy."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste((0, 0, 0, alpha), (xy[0], xy[1], xy[0] + mask.width, xy[1] + mask.height), mask)
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _shadow_text(canvas: Image.Image, xy, text, font, fill, anchor="la", blur=6, alpha=170):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((xy[0], xy[1] + 3), text, font=font, fill=(0, 0, 0, alpha), anchor=anchor)
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(canvas).text(xy, text, font=font, fill=fill, anchor=anchor)


def _centered_text(canvas: Image.Image, cx: float, y: float, text: str, font, fill, anchor="ls") -> None:
    """Text with a shadow, centred on cx by its ink rather than its advance width."""
    left, _, right, _ = font.getbbox(text, anchor=anchor)
    _shadow_text(canvas, (cx - (left + right) / 2, y), text, font, fill, anchor=anchor, blur=4)


def _cap_height(font) -> int:
    return -font.getbbox("H", anchor="ls")[1]


def _fit_font(text: str, factory, size: int, max_width: float, minimum: int = 18):
    """Shrink the font until the text fits."""
    while size > minimum:
        f = factory(size)
        if f.getlength(text) <= max_width:
            return f
        size -= 2
    return factory(minimum)


def _short(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


# ───────────────────────── placeholders ─────────────────────────

def _placeholder_background(seed: str, accent) -> Image.Image:
    """Abstract background used when the splash art can't be downloaded."""
    rnd = random.Random(seed)
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    for _ in range(9):
        r = rnd.randint(120, 320)
        x, y = rnd.randint(-100, W + 100), rnd.randint(-100, H + 100)
        c = tuple(int(v * rnd.uniform(0.25, 0.7)) for v in accent) + (255,)
        d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    return img.filter(ImageFilter.GaussianBlur(80))


def _placeholder_icon(name: str, size: int, accent) -> Image.Image:
    img = Image.new("RGBA", (size, size), (30, 34, 46, 255))
    ImageDraw.Draw(img).text((size / 2, size / 2), (name[:2] or "?").upper(),
                             font=display(int(size * 0.55)), fill=accent, anchor="mm")
    return img


# ───────────────────────── position icon ─────────────────────────

# Shapes of the League client role icons, on its 34×34 grid. A segment is a point (x, y)
# or a cubic curve ((x1, y1), (x2, y2), (x, y)). "dim" is the rest of the map, drawn faded.
POSITION_SHAPES = {
    "TOP": {
        "lit": [[(4, 4), (4, 28), (9, 23), (9, 9), (23, 9), (28, 4)]],
        "dim": [[(14, 14), (21, 14), (21, 21), (14, 21)],
                [(26, 11), (26, 26), (11, 26), (7, 30), (30, 30), (30, 7)]],
    },
    "JUNGLE": {
        "lit": [[(25, 3), ((22.9, 6.3), (19.9, 9.9), (18, 14.5)), (20, 20), (21, 17),
                 ((21, 12), (22.9, 8.3), (25, 3))],
                [(13, 20), ((11.5, 15.5), (8.2, 13), (4, 11)), ((7.9, 14.1), (8.4, 18.5), (9, 23)), (12.7, 26.3),
                 ((14.2, 27.9), (16.5, 30.5), (17, 31)), ((21.6, 21.6), (13.6, 10.2), (9, 3)),
                 ((11.7, 9.6), (13.7, 13.3), (13, 20))],
                [(21, 25), (21, 27), (25, 23), ((25.6, 18.5), (26.1, 14.1), (30, 11)),
                 ((24.7, 13.5), (22.1, 18.9), (21, 25))]],
    },
    "MIDDLE": {
        "lit": [[(25, 4), (4, 25), (4, 30), (9, 30), (30, 9), (30, 4)]],
        "dim": [[(30, 13), (26, 17), (26, 26), (17, 26), (13, 30), (30, 30)],
                [(17, 8), (21, 4), (4, 4), (4, 21), (8, 17), (8, 8)]],
    },
    "BOTTOM": {
        "lit": [[(30, 6), (25, 11), (25, 25), (11, 25), (6, 30), (30, 30)]],
        "dim": [[(13, 13), (20, 13), (20, 20), (13, 20)],
                [(4, 4), (4, 27), (8, 23), (8, 8), (23, 8), (27, 4)]],
    },
    "UTILITY": {
        "lit": [[(22, 5), (20.8, 3), (13.1, 3), (12, 5), (17, 11)],
                [(17, 14), (16, 13), (13, 28), (17, 31), (21, 28), (18, 13)],
                [(11, 9), (0, 9), ((0, 9), (4.5, 13), (8, 13)), (10, 13), (7, 17), (12, 19), (14, 12)],
                [(23, 9), (34, 9), ((34, 9), (29.5, 13), (26, 13)), (24, 13), (27, 17), (22, 19), (20, 12)]],
    },
}


def _outline(segments, steps: int = 12) -> list[tuple[float, float]]:
    """Points of a closed shape, sampling its curves."""
    points = []
    for seg in segments:
        if isinstance(seg[0], tuple):
            p0, (p1, p2, p3) = points[-1], seg
            for i in range(1, steps + 1):
                t = i / steps
                a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
                points.append(tuple(a * p0[k] + b * p1[k] + c * p2[k] + d * p3[k] for k in (0, 1)))
        else:
            points.append(seg)
    return points


def position_icon(position: str, size: int, color, dim=(95, 100, 116)) -> Image.Image:
    """The role icon from the League client, drawn flat in the card colours (no external images)."""
    scale = 4
    k = size * scale / 34
    img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    shapes = POSITION_SHAPES.get(position, {})
    for part, fill in (("dim", dim), ("lit", color)):
        for shape in shapes.get(part, []):
            d.polygon([(x * k, y * k) for x, y in _outline(shape)], fill=fill)
    return img.resize((size, size), Image.Resampling.LANCZOS)


# ───────────────────────── the card ─────────────────────────

def draw(m: MatchData, dd: DataDragon | None, language: str = "es", meme: Meme | None = None) -> Card:
    """The card, drawn back to front. With an animated meme, every frame of the meme area too."""
    t = i18n.get(language)
    accent = ACCENT[m.result]
    title = t[m.result]

    canvas = _background(m, dd, accent)
    if m.rank:
        _rank(canvas, m.rank, dd, t)
    if meme:
        meme_xy = _meme_position(title)
        _meme_frame(canvas, meme_xy)
        under_meme = canvas.crop(_meme_area(meme_xy, TITLE_SHADOW_REACH))  # to redraw the meme area per frame
    _title(canvas, title, accent)
    _meta(canvas, m, t)
    _champion(canvas, m, dd, accent)
    _player(canvas, m, t)
    _items(canvas, m, dd)
    _stats(canvas, m, t)

    still = canvas.convert("RGB")
    if not meme:
        return Card(still)
    patches = [_meme_patch(under_meme, meme_xy, frame, title, accent) for frame in meme.frames]
    still.paste(patches[0], meme_xy)
    return Card(still, patches, meme_xy, meme.durations)


def _background(m: MatchData, dd: DataDragon | None, accent) -> Image.Image:
    """Champion splash art, darkened so the text stays readable, with the result colour on the left."""
    splash = dd.splash(m.champion_id) if dd else None
    canvas = _cover(splash, (W, H), (0.5, 0.25)) if splash else _placeholder_background(m.champion_id, accent)
    canvas.alpha_composite(_gradient((W, H), 240, 70, BG))
    canvas.alpha_composite(_gradient((W, H), 0, 170, BG, horizontal=False))
    canvas.alpha_composite(_gradient((W, H), 70, 0, accent))  # glow in the result colour
    ImageDraw.Draw(canvas).rectangle((0, 0, 9, H), fill=accent)
    return canvas


def _title(canvas: Image.Image, text: str, accent, origin=(0, 0)) -> None:
    """VICTORIA / DERROTA. origin is where canvas sits on the card when it's a crop of it."""
    xy = (PAD - origin[0], TITLE_BASELINE - origin[1])
    _shadow_text(canvas, xy, text, display(TITLE_SIZE), accent, anchor="ls")


def _meta(canvas: Image.Image, m: MatchData, t: dict) -> None:
    """Queue · duration · date, under the title."""
    date = t["date"].format(month=t["months"][m.ended_at.month - 1], day=m.ended_at.day,
                            time=f"{m.ended_at:%H:%M}")
    queue = t["queue_long"].get(m.queue_id, t["game"]).upper()
    meta = f"{queue}   ·   {m.duration}   ·   {date}"
    font = _fit_font(meta, lambda s: poppins("Medium", s), 20, TEXT_RIGHT - PAD, 14)
    ImageDraw.Draw(canvas).text((PAD + 2, META_Y), meta, font=font, fill=GREY)


def _champion(canvas: Image.Image, m: MatchData, dd: DataDragon | None, accent) -> None:
    """Champion icon with level and position badges."""
    x, y = PAD, ICON_Y
    icon = dd.champion_icon(m.champion_id) if dd else None
    if icon:
        icon = ImageOps.fit(icon, (ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    else:
        icon = _placeholder_icon(m.champion, ICON_SIZE, accent)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x - 4, y - 4, x + ICON_SIZE + 4, y + ICON_SIZE + 4), 22, fill=accent)
    canvas.alpha_composite(_rounded(icon, 18), (x, y))

    def badge(cx, cy, r):
        d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=accent)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BADGE_BG)

    if m.level:
        cx, cy = x + ICON_SIZE - 6, y + ICON_SIZE - 6
        badge(cx, cy, 21)
        d.text((cx, cy + 1), str(m.level), font=poppins("Bold", 19), fill=WHITE, anchor="mm")

    if m.position:
        cx, cy = x + 6, y + ICON_SIZE - 6
        badge(cx, cy, 26)
        canvas.alpha_composite(position_icon(m.position, 40, WHITE), (cx - 20, cy - 20))


def _player(canvas: Image.Image, m: MatchData, t: dict) -> None:
    """Riot ID, champion · position · KDA ratio, and the kills / deaths / assists."""
    x = PAD + ICON_SIZE + 36
    width = TEXT_RIGHT - x
    name_font = _fit_font(m.player, lambda s: poppins("SemiBold", s), NAME_SIZE, width - 110)
    name_baseline = ICON_Y + 34
    _shadow_text(canvas, (x, name_baseline), m.player, name_font, WHITE, anchor="ls", blur=4)
    d = ImageDraw.Draw(canvas)
    if m.tag:
        d.text((x + name_font.getlength(m.player) + 10, name_baseline), f"#{m.tag}",
               font=poppins("Medium", SUBTITLE_SIZE), fill=DARK_GREY, anchor="ls")

    position_text = t["positions"].get(m.position, "")
    ratio = t["perfect"] if m.kda_ratio is None else f"{m.kda_ratio:.2f} KDA"
    subtitle = "   ·   ".join(s for s in (m.champion, position_text, ratio) if s)
    subtitle_font = _fit_font(subtitle, lambda s: poppins("Medium", s), SUBTITLE_SIZE, width, 16)
    d.text((x, name_baseline + NAME_TO_SUBTITLE), subtitle, font=subtitle_font, fill=GREY)

    # KDA with deaths in red
    kda_text = f"{m.kills} / {m.deaths} / {m.assists}"
    kda_font = _fit_font(kda_text, display, 100, width, 60)
    baseline = ICON_Y + 168
    for part, color in ((str(m.kills), WHITE), (" / ", DARK_GREY), (str(m.deaths), DEATHS_RED),
                        (" / ", DARK_GREY), (str(m.assists), WHITE)):
        _shadow_text(canvas, (x, baseline), part, kda_font, color, anchor="ls", blur=5, alpha=140)
        x += kda_font.getlength(part)


def _items(canvas: Image.Image, m: MatchData, dd: DataDragon | None) -> None:
    """The six items and the trinket, slightly apart."""
    slots = []
    for i, item in enumerate((m.items + [0] * 7)[:7]):
        x = PAD + i * (ITEM_SIZE + ITEM_GAP) + (10 if i == 6 else 0)
        img = dd.item(item) if (dd and item) else None
        if img:
            canvas.alpha_composite(_rounded(ImageOps.fit(img, (ITEM_SIZE, ITEM_SIZE)), 8), (x, ITEMS_Y))
        slots.append((x, bool(img)))

    def item_frames(dl: ImageDraw.ImageDraw):
        for x, filled in slots:
            box = (x, ITEMS_Y, x + ITEM_SIZE - 1, ITEMS_Y + ITEM_SIZE - 1)
            if filled:
                dl.rounded_rectangle(box, 8, outline=(255, 255, 255, 50), width=1)
            else:
                dl.rounded_rectangle(box, 8, fill=(255, 255, 255, 14), outline=(255, 255, 255, 40), width=1)

    _translucent(canvas, item_frames)


def _stats(canvas: Image.Image, m: MatchData, t: dict) -> None:
    """The row of boxes at the bottom: CS, damage, gold, vision and kill participation."""
    labels = t["stats"]
    stats = [
        (labels["cs"].format(m.cs_per_min), str(m.cs)),
        (labels["damage"], _short(m.damage)),
        (labels["gold"], _short(m.gold)),
        (labels["vision"], str(m.vision)),
        (labels["kp"], f"{round(m.kill_participation * 100)}%" if m.kill_participation is not None else "–"),
    ]
    box_w = (W - 2 * PAD - STATS_GAP * (len(stats) - 1)) / len(stats)

    def stat_boxes(dl: ImageDraw.ImageDraw):
        for i in range(len(stats)):
            x0 = PAD + i * (box_w + STATS_GAP)
            dl.rounded_rectangle((x0, STATS_Y, x0 + box_w, STATS_Y + STATS_H), 14,
                                 fill=(255, 255, 255, 16), outline=(255, 255, 255, 34), width=1)

    _translucent(canvas, stat_boxes)
    d = ImageDraw.Draw(canvas)
    for i, (label, value) in enumerate(stats):
        x0 = PAD + i * (box_w + STATS_GAP)
        label_font = _fit_font(label, lambda s: poppins("Medium", s), 15, box_w - 28, 11)
        d.text((x0 + 16, STATS_Y + 13), label, font=label_font, fill=DARK_GREY)
        value_font = _fit_font(value, lambda s: poppins("SemiBold", s), 28, box_w - 28, 18)
        d.text((x0 + 16, STATS_Y + 34), value, font=value_font, fill=WHITE)


# ───────────────────────── rank ─────────────────────────

def _rank(canvas: Image.Image, rank: Rank, dd: DataDragon | None, t: dict) -> None:
    """Tier emblem, name and LP, styled like the player's name and the line under it."""
    name = f"{t['tiers'].get(rank.tier, rank.tier)} {rank.division}".strip()
    lp = t["lp"].format(rank.lp)
    column = RANK_RIGHT - RANK_LEFT
    name_font = _fit_font(name, lambda s: poppins("SemiBold", s), NAME_SIZE, column - 2 * RANK_MARGIN)
    lp_font = poppins("Medium", SUBTITLE_SIZE)

    # Centred on the content of the left column: from the top of the title to the bottom of the items
    middle = (TITLE_BASELINE - _cap_height(display(TITLE_SIZE)) + ITEMS_Y + ITEM_SIZE) // 2
    name_offset = EMBLEM_H + EMBLEM_GAP + _cap_height(name_font)
    height = name_offset + NAME_TO_SUBTITLE + lp_font.getbbox(lp, anchor="la")[3]
    top = middle - height // 2

    _halo(canvas, (RANK_CX, middle), (round(column * 1.4), round(height * 1.9)))
    emblem = dd.rank_emblem(rank.tier) if dd else None
    if emblem:
        _emblem(canvas, emblem, top, TIER_COLORS.get(rank.tier, WHITE))
    _centered_text(canvas, RANK_CX, top + name_offset, name, name_font, WHITE)
    _centered_text(canvas, RANK_CX, top + name_offset + NAME_TO_SUBTITLE, lp, lp_font, GREY, anchor="la")


def _halo(canvas: Image.Image, center: tuple[int, int], size: tuple[int, int]) -> None:
    """Darkens the splash art softly around center: strongest in the middle, fading to nothing."""
    fade = Image.radial_gradient("L").resize(size, Image.Resampling.LANCZOS)  # 0 in the middle → 255 at the edge
    shade = Image.new("RGBA", size, BG + (0,))
    shade.putalpha(fade.point(lambda v: int(max(0, 255 - v * 1.25) * HALO_DARKNESS)))
    canvas.alpha_composite(shade, (center[0] - size[0] // 2, center[1] - size[1] // 2))


def _emblem(canvas: Image.Image, img: Image.Image, top: int, glow_color) -> None:
    """The tier crest at a fixed height, centred in the rank column, on a faint glow of its colour."""
    crest = img.crop(img.getchannel("A").getbbox())
    crest = ImageOps.contain(crest, (RANK_RIGHT - RANK_LEFT - 2 * RANK_MARGIN, EMBLEM_H), Image.Resampling.LANCZOS)
    x = RANK_CX - crest.width // 2
    y = top + (EMBLEM_H - crest.height) // 2

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((x, y, x + crest.width, y + crest.height), fill=glow_color + (HALO_GLOW,))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40)))
    _shadow(canvas, crest.getchannel("A"), (x, y + 6), blur=10, alpha=170)
    canvas.alpha_composite(crest, (x, y))


# ───────────────────────── meme ─────────────────────────

def _meme_position(title: str) -> tuple[int, int]:
    """Top-left of the meme: centred on the title's letters and tucked under the last one."""
    _, top, right, bottom = display(TITLE_SIZE).getbbox(title, anchor="ls")
    return PAD + right - MEME_OVERLAP, TITLE_BASELINE + (top + bottom) // 2 - MEME_SIZE // 2


def _meme_area(xy: tuple[int, int], margin: int = 0) -> tuple[int, int, int, int]:
    return xy[0] - margin, xy[1] - margin, xy[0] + MEME_SIZE + margin, xy[1] + MEME_SIZE + margin


def _meme_frame(canvas: Image.Image, xy: tuple[int, int]) -> None:
    """The sticker the meme sits on: a white rounded border with a soft shadow."""
    b = MEME_BORDER
    left, top, right, bottom = _meme_area(xy, b)
    _shadow(canvas, _rounded_mask((right - left, bottom - top), MEME_RADIUS + b), (left, top + 6), blur=8)
    _translucent(canvas, lambda dl: dl.rounded_rectangle((left, top, right - 1, bottom - 1), MEME_RADIUS + b,
                                                         fill=WHITE + (235,)))


def _meme_patch(under: Image.Image, xy: tuple[int, int], picture: Image.Image, title: str, accent) -> Image.Image:
    """One frame of the meme area: the picture on its sticker, with the title redrawn over it.

    under is what lies beneath the picture, cropped TITLE_SHADOW_REACH px around it, so the title's
    blurred shadow comes out exactly as on the rest of the card.
    """
    margin = TITLE_SHADOW_REACH
    patch = under.copy()
    patch.alpha_composite(_rounded(picture, MEME_RADIUS), (margin, margin))
    _title(patch, title, accent, origin=(xy[0] - margin, xy[1] - margin))
    patch = patch.crop((margin, margin, margin + MEME_SIZE, margin + MEME_SIZE))
    return patch.convert("RGB")
