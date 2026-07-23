"""Webcam video poller.

The buoy webcam publishes a single overwriting file:
    https://seagull-webcams.s3.us-east-2.amazonaws.com/BSU2/BSU2_latest.mp4
(~16s, 1080p H.264). It is replaced at the top of each daylight hour and NOT
archived, so we detect a new clip via ETag/Last-Modified and download it before
it's overwritten.
"""

from __future__ import annotations

import datetime as dt
import json
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import config

STATE_FILE = config.STATE_DIR / "video_state.json"
REQUEST_TIMEOUT = 60


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1))


def head() -> dict:
    r = requests.head(config.VIDEO_URL, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return {
        "etag": r.headers.get("ETag"),
        "last_modified": r.headers.get("Last-Modified"),
        "length": int(r.headers.get("Content-Length", 0)),
    }


def last_modified_dt(meta: dict) -> dt.datetime | None:
    lm = meta.get("last_modified")
    return parsedate_to_datetime(lm) if lm else None


def check_new_video(download=True) -> Path | None:
    """Return path to a freshly downloaded clip if S3 has a new one, else None."""
    meta = head()
    state = _load_state()
    if meta["etag"] and meta["etag"] == state.get("etag"):
        return None  # already handled this clip
    if not download:
        return None

    out = config.OUT_DIR / "BSU2_latest.mp4"
    with requests.get(config.VIDEO_URL, timeout=REQUEST_TIMEOUT, stream=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)

    state.update(meta)
    state["downloaded_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _save_state(state)
    return out


if __name__ == "__main__":
    print("HEAD:", head())
    p = check_new_video()
    print("new clip:", p or "none (already seen latest)")
