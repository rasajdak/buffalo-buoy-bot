"""Short 'later today' weather outlook (National Weather Service — free, no key).

Anchored to the Buffalo shoreline: the buoy sits over open water, which has no
land gridpoint forecast. The captain only mentions the outlook when something is
genuinely brewing (storms, rain, a real blow, a front), so most posts stay in the
present. Cached to disk so we don't hit NWS every 15 minutes.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import requests

import config

# Buffalo waterfront gridpoint (resolved from api.weather.gov/points/42.8776,-78.8890)
FORECAST_URL = "https://api.weather.gov/gridpoints/BUF/35,46/forecast"
NWS_HEADERS = {
    "User-Agent": "TheBuffaloBuoyBot/1.0 (github.com/rasajdak/buffalo-buoy-bot)",
    "Accept": "application/geo+json",
}
CACHE = config.STATE_DIR / "forecast.json"
CACHE_MIN = 90
# "wind" is excluded — every forecast mentions it; we gauge wind by speed instead.
NOTABLE_WORDS = ("thunder", "storm", "rain", "shower", "snow", "squall",
                 "gust", "advisory", "fog", "chance")
NOTABLE_WIND_MPH = 18
NOTABLE_POP = 30  # % chance of precip


def _max_mph(s: str) -> int:
    nums = [int(x) for x in re.findall(r"\d+", s or "")]
    return max(nums) if nums else 0


def _fetch_periods() -> list:
    last = None
    for _ in range(3):  # NWS gridpoint endpoint 500s/404s intermittently
        r = requests.get(FORECAST_URL, headers=NWS_HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json()["properties"]["periods"]
        last = r.status_code
    raise RuntimeError(f"NWS forecast HTTP {last}")


def _periods() -> list:
    if CACHE.exists():
        d = json.loads(CACHE.read_text())
        ts = dt.datetime.fromisoformat(d["fetched_at"])
        if (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 60 < CACHE_MIN:
            return d["periods"]
    periods = _fetch_periods()
    CACHE.write_text(json.dumps(
        {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "periods": periods}))
    return periods


def get_outlook() -> tuple[str, bool] | None:
    """Return (outlook_text, notable) for the next ~day, or None if unavailable."""
    try:
        periods = _periods()
    except Exception as e:
        print(f"[forecast] unavailable ({e})")
        return None
    if not periods:
        return None
    up = periods[:2]
    text = " ".join(
        f"{p['name']}: {p['shortForecast']}, wind {p['windDirection']} {p['windSpeed']}."
        for p in up
    )
    notable = False
    for p in up:
        blob = (p.get("shortForecast", "") + " " + p.get("detailedForecast", "")).lower()
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
        if (any(w in blob for w in NOTABLE_WORDS)
                or pop >= NOTABLE_POP
                or _max_mph(p.get("windSpeed", "")) >= NOTABLE_WIND_MPH):
            notable = True
    return text, notable


if __name__ == "__main__":
    o = get_outlook()
    print("outlook:", o)
