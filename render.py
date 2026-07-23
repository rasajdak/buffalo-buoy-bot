"""Render a 'current conditions' card (PNG) from Conditions using Pillow."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config
from buoy import Conditions
from content import stamp, n

W = H = 1080
MARGIN = 72

# palette
BG_TOP = (7, 22, 40)
BG_BOT = (13, 52, 82)
INK = (240, 247, 252)
MUTED = (150, 178, 200)
TILE_BG = (255, 255, 255, 16)  # translucent
TILE_LINE = (255, 255, 255, 40)
ACCENTS = {
    "WAVES": (86, 204, 214),
    "WIND": (120, 200, 255),
    "WATER": (99, 179, 237),
    "AIR": (245, 197, 122),
}

# candidate fonts (macOS + typical Linux VPS), bold then regular
_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
_REG = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def font(size: int, bold=False) -> ImageFont.FreeTypeFont:
    for path in (_BOLD if bold else _REG):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # scalable default (Pillow >=10)


def _gradient(w: int, h: int, top, bot) -> Image.Image:
    base = Image.new("RGB", (w, h), top)
    top_l = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        top_l.putpixel((0, y), tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return top_l.resize((w, h))


def _text(draw, xy, s, fnt, fill, anchor="la"):
    draw.text(xy, s, font=fnt, fill=fill, anchor=anchor)


def _tile(img, box, label, value, sub, accent):
    x0, y0, x1, y1 = box
    overlay = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([0, 0, x1 - x0 - 1, y1 - y0 - 1], radius=28, fill=TILE_BG, outline=TILE_LINE, width=2)
    od.rounded_rectangle([0, 0, 10, y1 - y0 - 1], radius=6, fill=accent + (255,))
    img.paste(overlay, (x0, y0), overlay)
    d = ImageDraw.Draw(img)
    _text(d, (x0 + 40, y0 + 34), label, font(30, bold=True), accent)
    _text(d, (x0 + 38, y0 + 78), value, font(96, bold=True), INK)
    if sub:
        _text(d, (x0 + 40, y1 - 58), sub, font(30), MUTED)


def render_conditions_card(c: Conditions, out_path: Path | None = None) -> Path:
    out_path = Path(out_path) if out_path else config.OUT_DIR / "conditions.png"
    img = _gradient(W, H, BG_TOP, BG_BOT).convert("RGB")
    d = ImageDraw.Draw(img)

    # header
    _text(d, (MARGIN, 64), "BUFFALO BUOY", font(66, bold=True), INK)
    _text(d, (MARGIN, 146), "Lake Erie · off Buffalo, NY", font(34), MUTED)
    when = stamp(c.observed_at) if c.observed_at else "just now"
    _text(d, (MARGIN, 196), f"Conditions · {when}", font(28), (110, 140, 165))

    # 2x2 tiles
    gap = 32
    top = 280
    tw = (W - 2 * MARGIN - gap) // 2
    th = 300
    boxes = {
        "WAVES": (MARGIN, top, MARGIN + tw, top + th),
        "WIND": (MARGIN + tw + gap, top, W - MARGIN, top + th),
        "WATER": (MARGIN, top + th + gap, MARGIN + tw, top + 2 * th + gap),
        "AIR": (MARGIN + tw + gap, top + th + gap, W - MARGIN, top + 2 * th + gap),
    }

    wave_sub = ""
    if c.wave_max_ft is not None:
        wave_sub = f"max {n(c.wave_max_ft,1)} ft"
        if c.wave_period_s:
            wave_sub += f" · {n(c.wave_period_s,0)}s apart"
    air_sub = " · ".join(
        s for s in [
            f"{n(c.pressure_inhg,2)} inHg" if c.pressure_inhg is not None else "",
            f"{n(c.humidity_pct,0)}% hum" if c.humidity_pct is not None else "",
        ] if s
    )

    _tile(img, boxes["WAVES"], "WAVES",
          f"{n(c.wave_sig_ft,1)} ft" if c.wave_sig_ft is not None else "—",
          wave_sub, ACCENTS["WAVES"])
    _tile(img, boxes["WIND"], "WIND",
          f"{n(c.wind_mph,0)} mph" if c.wind_mph is not None else "—",
          f"from the {c.wind_dir}" if c.wind_dir else "", ACCENTS["WIND"])
    _tile(img, boxes["WATER"], "WATER TEMP",
          f"{n(c.water_temp_f,0)}°F" if c.water_temp_f is not None else "—",
          "surface", ACCENTS["WATER"])
    _tile(img, boxes["AIR"], "AIR TEMP",
          f"{n(c.air_temp_f,0)}°F" if c.air_temp_f is not None else "—",
          air_sub, ACCENTS["AIR"])

    # footer
    _text(d, (MARGIN, H - 66), "Data: GLOS Seagull · seagull.glos.org/data-console/666",
          font(26), (110, 140, 165))
    if c.phycocyanin_rfu is not None and c.phycocyanin_rfu >= config.ALGAE_WATCH_RFU:
        _text(d, (W - MARGIN, H - 66), "⚠ algae watch", font(26, bold=True),
              (245, 197, 122), anchor="ra")

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    from buoy import get_conditions
    p = render_conditions_card(get_conditions())
    print("wrote", p)
