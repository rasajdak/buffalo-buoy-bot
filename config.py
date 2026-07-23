"""Configuration + tiny .env loader (no external deps)."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, # comments, optional quotes."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Facebook ---
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v23.0")

# If no token/page configured, everything runs in dry-run automatically.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes") or not (
    FB_PAGE_ID and FB_PAGE_TOKEN
)

# --- OpenAI (Captain's Log caption writer) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# If no key, captions fall back to a plain template (bot still runs).
USE_AI_CAPTIONS = bool(OPENAI_API_KEY)

# --- Webcam video (public S3, overwritten each daylight hour) ---
VIDEO_URL = os.environ.get(
    "VIDEO_URL",
    "https://seagull-webcams.s3.us-east-2.amazonaws.com/BSU2/BSU2_latest.mp4",
)

# --- Presentation ---
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

# --- Posting window (local hours, 24h). Outside this, `tick` stays quiet. ---
# Default 6:00–22:00 local. Set ACTIVE_START=0 / ACTIVE_END=24 for around-the-clock.
ACTIVE_START = int(_f("ACTIVE_START", 6))
ACTIVE_END = int(_f("ACTIVE_END", 22))
STATE_DIR = Path(os.environ.get("STATE_DIR", BASE_DIR / "state"))
OUT_DIR = Path(os.environ.get("OUT_DIR", BASE_DIR / "out"))

# --- Alert thresholds (friendly units) ---
# Wave significant height, feet
WAVE_NOTABLE_FT = _f("WAVE_NOTABLE_FT", 3.0)
WAVE_BIG_FT = _f("WAVE_BIG_FT", 5.0)
WAVE_HUGE_FT = _f("WAVE_HUGE_FT", 8.0)
# Wind, mph
WIND_BREEZY_MPH = _f("WIND_BREEZY_MPH", 20.0)
WIND_STRONG_MPH = _f("WIND_STRONG_MPH", 30.0)
WIND_GALE_MPH = _f("WIND_GALE_MPH", 39.0)
# Phycocyanin (blue-green algae indicator), RFU — tune once we see a bloom baseline
ALGAE_WATCH_RFU = _f("ALGAE_WATCH_RFU", 1.0)
ALGAE_ALERT_RFU = _f("ALGAE_ALERT_RFU", 3.0)
# Data staleness guard: skip posting if newest reading older than this (minutes)
MAX_DATA_AGE_MIN = _f("MAX_DATA_AGE_MIN", 180.0)
# Re-alert cooldown (hours) once an alert has fired at a given level
ALERT_COOLDOWN_HOURS = _f("ALERT_COOLDOWN_HOURS", 6.0)

STATE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
