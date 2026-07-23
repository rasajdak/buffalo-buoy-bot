"""Human-facing text: post captions, alert messages, formatting helpers.

Keeping all copy in one place so tone stays consistent and easy to tweak.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import config
from buoy import Conditions, CONSOLE_URL, PLATFORM_NAME, PLATFORM_REGION

TZ = ZoneInfo(config.TIMEZONE)

HASHTAGS = "#LakeErie #Buffalo #GreatLakes #BuffaloBuoy"


def local_time(when: dt.datetime) -> dt.datetime:
    return when.astimezone(TZ)


def stamp(when: dt.datetime) -> str:
    """e.g. 'Wed Jul 22, 11:40 PM EDT'"""
    lt = local_time(when)
    return lt.strftime("%a %b ") + str(lt.day) + lt.strftime(", %-I:%M %p %Z")


def n(value, digits=0, dash="—"):
    """Format a number, or a dash if missing."""
    if value is None:
        return dash
    if digits == 0:
        return f"{round(value):d}"
    return f"{value:.{digits}f}"


def conditions_caption(c: Conditions) -> str:
    when = stamp(c.observed_at) if c.observed_at else "just now"
    lines = [
        f"🌊 {PLATFORM_NAME} — {PLATFORM_REGION} conditions",
        f"as of {when}",
        "",
    ]
    if c.wave_sig_ft is not None:
        wave = f"Waves: {n(c.wave_sig_ft,1)} ft"
        if c.wave_max_ft is not None:
            wave += f" (max {n(c.wave_max_ft,1)} ft"
            wave += f", {n(c.wave_period_s,0)}s apart)" if c.wave_period_s else ")"
        lines.append(wave)
    if c.wind_mph is not None:
        wind = f"Wind: {n(c.wind_mph,0)} mph"
        if c.wind_dir:
            wind += f" from the {c.wind_dir}"
        lines.append(wind)
    if c.water_temp_f is not None:
        lines.append(f"Water: {n(c.water_temp_f,0)}°F")
    if c.air_temp_f is not None:
        lines.append(f"Air: {n(c.air_temp_f,0)}°F")

    tail = []
    if c.pressure_inhg is not None:
        tail.append(f"{n(c.pressure_inhg,2)} inHg")
    if c.humidity_pct is not None:
        tail.append(f"{n(c.humidity_pct,0)}% humidity")
    if tail:
        lines += ["", " · ".join(tail)]

    lines += ["", f"Live data: {CONSOLE_URL}", HASHTAGS]
    return "\n".join(lines)


def alert_caption(kind: str, headline: str, c: Conditions) -> str:
    lines = [headline, ""]
    if kind == "waves":
        lines.append(f"Significant waves {n(c.wave_sig_ft,1)} ft, peaking near {n(c.wave_max_ft,1)} ft.")
        if c.wind_mph is not None:
            lines.append(f"Wind {n(c.wind_mph,0)} mph from the {c.wind_dir or '—'}.")
    elif kind == "wind":
        lines.append(f"Wind {n(c.wind_mph,0)} mph from the {c.wind_dir or '—'}.")
        if c.wave_sig_ft is not None:
            lines.append(f"Waves running {n(c.wave_sig_ft,1)} ft.")
    elif kind == "algae":
        lines.append(
            f"Blue-green algae indicator (phycocyanin) is elevated at "
            f"{n(c.phycocyanin_rfu,2)} RFU. This is an early signal, not a confirmed bloom."
        )
    if c.observed_at:
        lines += ["", f"Reading: {stamp(c.observed_at)}"]
    lines += ["", f"Details: {CONSOLE_URL}", HASHTAGS]
    return "\n".join(lines)
