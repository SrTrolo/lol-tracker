"""Draws the win / loss card with Pillow."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import i18n
from .match import MatchData
from .riot import DataDragon

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

W, H = 1200, 560
PAD = 48
# Meme panel: top-right area, above the stats row (same layout with or without a meme)
MEME_BOX = (790, 34, W - 34, 428)   # left, top, right, bottom
TEXT_RIGHT = MEME_BOX[0] - 30       # text never goes past this point

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


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mask))
    return img


def _translucent(canvas: Image.Image, draw_fn) -> None:
    """Draw semi-transparent shapes on a separate layer so they blend properly."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    canvas.alpha_composite(layer)


def _shadow_text(canvas: Image.Image, xy, text, font, fill, anchor="la", blur=6, alpha=170):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((xy[0], xy[1] + 3), text, font=font, fill=(0, 0, 0, alpha), anchor=anchor)
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(canvas).text(xy, text, font=font, fill=fill, anchor=anchor)


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

def position_icon(position: str, size: int, color, dim=(95, 100, 116)) -> Image.Image:
    """Mini-map with the matching lane highlighted (drawn in code, no external images)."""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    a, b = int(s * 0.16), s - int(s * 0.16)   # map edges
    w = int(s * 0.085)                        # line width
    gap = int(s * 0.13)

    top = [(a, b - gap), (a, a), (b - gap, a)]
    bot = [(a + gap, b), (b, b), (b, a + gap)]
    mid = [(a + int(s * 0.2), b - int(s * 0.2)), (b - int(s * 0.2), a + int(s * 0.2))]

    def line(points, c):
        d.line(points, fill=c, width=w, joint="curve")
        for x, y in (points[0], points[-1]):
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=c)

    lane = {"TOP": "top", "JUNGLE": "jg", "MIDDLE": "mid", "BOTTOM": "bot", "UTILITY": "sup"}.get(position, "")
    line(top, color if lane == "top" else dim)
    line(bot, color if lane in ("bot", "sup") else dim)
    line(mid, color if lane == "mid" else dim)

    if lane == "jg":  # two "camps", one on each side of mid
        r = int(s * 0.09)
        for cx, cy in ((a + int(s * 0.25), a + int(s * 0.25)), (b - int(s * 0.25), b - int(s * 0.25))):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    if lane == "sup":  # a small "heal" cross next to bot lane
        cx = cy = int(s * 0.68)
        arm, t = int(s * 0.1), int(s * 0.04)
        d.rectangle((cx - arm, cy - t, cx + arm, cy + t), fill=color)
        d.rectangle((cx - t, cy - arm, cx + t, cy + arm), fill=color)

    return img.resize((size, size), Image.Resampling.LANCZOS)


# ───────────────────────── meme panel ─────────────────────────

def _meme_panel(meme: Image.Image, size: tuple[int, int], accent) -> Image.Image:
    w, h = size
    panel = _cover(meme, size).filter(ImageFilter.GaussianBlur(18))
    panel.alpha_composite(Image.new("RGBA", size, (0, 0, 0, 120)))
    inner = ImageOps.contain(meme.convert("RGBA"), (w - 16, h - 16), Image.Resampling.LANCZOS)
    panel.alpha_composite(inner, ((w - inner.width) // 2, (h - inner.height) // 2))
    panel = _rounded(panel, 22)
    ImageDraw.Draw(panel).rounded_rectangle((1, 1, w - 2, h - 2), 22, outline=accent + (255,), width=3)
    return panel


# ───────────────────────── the card ─────────────────────────

def draw(m: MatchData, dd: DataDragon | None, meme: Image.Image | None = None, language: str = "es") -> Image.Image:
    t = i18n.get(language)
    accent = ACCENT[m.result]

    # Background: champion splash art, darkened so the text stays readable
    splash = dd.splash(m.champion_id) if dd else None
    canvas = _cover(splash, (W, H), (0.5, 0.25)) if splash else _placeholder_background(m.champion_id, accent)
    canvas.alpha_composite(_gradient((W, H), 240, 70, BG))
    canvas.alpha_composite(_gradient((W, H), 0, 170, BG, horizontal=False))
    canvas.alpha_composite(_gradient((W, H), 70, 0, accent))  # glow in the result colour
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, 9, H), fill=accent)

    right_edge = TEXT_RIGHT

    # ── Header: VICTORIA / DERROTA ──
    _shadow_text(canvas, (PAD, 136), t[m.result], display(132), accent, anchor="ls")
    date = t["date"].format(month=t["months"][m.ended_at.month - 1], day=m.ended_at.day,
                            time=f"{m.ended_at:%H:%M}")
    queue = t["queue_long"].get(m.queue_id, t["game"]).upper()
    meta = f"{queue}   ·   {m.duration}   ·   {date}"
    d.text((PAD + 2, 152), meta, font=_fit_font(meta, lambda s: poppins("Medium", s), 20,
                                                right_edge - PAD, 14), fill=GREY)

    # ── Champion icon with level and position badges ──
    size, xi, yi = 150, PAD, 204
    icon = dd.champion_icon(m.champion_id) if dd else None
    icon = ImageOps.fit(icon, (size, size), Image.Resampling.LANCZOS) if icon else _placeholder_icon(m.champion, size, accent)
    d.rounded_rectangle((xi - 4, yi - 4, xi + size + 4, yi + size + 4), 22, fill=accent)
    canvas.alpha_composite(_rounded(icon, 18), (xi, yi))

    def badge(cx, cy, r):
        d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=accent)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BADGE_BG)

    if m.level:
        cx, cy = xi + size - 6, yi + size - 6
        badge(cx, cy, 21)
        d.text((cx, cy + 1), str(m.level), font=poppins("Bold", 19), fill=WHITE, anchor="mm")

    if m.position:
        cx, cy = xi + 6, yi + size - 6
        badge(cx, cy, 26)
        canvas.alpha_composite(position_icon(m.position, 40, WHITE), (cx - 20, cy - 20))

    # ── Player, champion, KDA ──
    xt = xi + size + 36
    width = right_edge - xt
    name_font = _fit_font(m.player, lambda s: poppins("SemiBold", s), 40, width - 110)
    name_baseline = yi + 34
    _shadow_text(canvas, (xt, name_baseline), m.player, name_font, WHITE, anchor="ls", blur=4)
    d = ImageDraw.Draw(canvas)
    if m.tag:
        d.text((xt + name_font.getlength(m.player) + 10, name_baseline), f"#{m.tag}",
               font=poppins("Medium", 24), fill=DARK_GREY, anchor="ls")

    position_text = t["positions"].get(m.position, "")
    ratio = t["perfect"] if m.kda_ratio is None else f"{m.kda_ratio:.2f} KDA"
    subtitle = "   ·   ".join(x for x in (m.champion, position_text, ratio) if x)
    d.text((xt, yi + 50), subtitle, font=_fit_font(subtitle, lambda s: poppins("Medium", s), 24, width, 16),
           fill=GREY)

    # KDA with deaths in red
    kda_text = f"{m.kills} / {m.deaths} / {m.assists}"
    kda_font = _fit_font(kda_text, display, 100, width, 60)
    x, baseline = xt, yi + 168
    for part, color in ((str(m.kills), WHITE), (" / ", DARK_GREY), (str(m.deaths), DEATHS_RED),
                        (" / ", DARK_GREY), (str(m.assists), WHITE)):
        _shadow_text(canvas, (x, baseline), part, kda_font, color, anchor="ls", blur=5, alpha=140)
        x += kda_font.getlength(part)

    # ── Items ──
    item_size, item_gap, item_y = 44, 7, 382
    slots = []
    for i, item in enumerate((m.items + [0] * 7)[:7]):
        xo = PAD + i * (item_size + item_gap) + (10 if i == 6 else 0)  # trinket slightly apart
        img = dd.item(item) if (dd and item) else None
        if img:
            canvas.alpha_composite(_rounded(ImageOps.fit(img, (item_size, item_size)), 8), (xo, item_y))
        slots.append((xo, bool(img)))

    def item_frames(dl: ImageDraw.ImageDraw):
        for xo, filled in slots:
            box = (xo, item_y, xo + item_size - 1, item_y + item_size - 1)
            if filled:
                dl.rounded_rectangle(box, 8, outline=(255, 255, 255, 50), width=1)
            else:
                dl.rounded_rectangle(box, 8, fill=(255, 255, 255, 14), outline=(255, 255, 255, 40), width=1)

    _translucent(canvas, item_frames)

    # ── Stats ──
    labels = t["stats"]
    stats = [
        (labels["cs"].format(m.cs_per_min), str(m.cs)),
        (labels["damage"], _short(m.damage)),
        (labels["gold"], _short(m.gold)),
        (labels["vision"], str(m.vision)),
        (labels["kp"], f"{round(m.kill_participation * 100)}%" if m.kill_participation is not None else "–"),
    ]
    box_y, box_h, box_gap = 448, 82, 12
    box_w = (W - 2 * PAD - box_gap * (len(stats) - 1)) / len(stats)

    def stat_boxes(dl: ImageDraw.ImageDraw):
        for i in range(len(stats)):
            x0 = PAD + i * (box_w + box_gap)
            dl.rounded_rectangle((x0, box_y, x0 + box_w, box_y + box_h), 14,
                                 fill=(255, 255, 255, 16), outline=(255, 255, 255, 34), width=1)

    _translucent(canvas, stat_boxes)
    d = ImageDraw.Draw(canvas)
    for i, (label, value) in enumerate(stats):
        x0 = PAD + i * (box_w + box_gap)
        label_font = _fit_font(label, lambda s: poppins("Medium", s), 15, box_w - 28, 11)
        d.text((x0 + 16, box_y + 13), label, font=label_font, fill=DARK_GREY)
        value_font = _fit_font(value, lambda s: poppins("SemiBold", s), 28, box_w - 28, 18)
        d.text((x0 + 16, box_y + 34), value, font=value_font, fill=WHITE)

    # ── Embedded meme ──
    if meme is not None:
        left, top, right, bottom = MEME_BOX
        canvas.alpha_composite(_meme_panel(meme, (right - left, bottom - top), accent), (left, top))

    return canvas.convert("RGB")
