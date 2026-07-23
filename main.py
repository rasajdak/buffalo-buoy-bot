"""Buffalo Buoy → Facebook bot. CLI orchestrator.

Commands:
  tick    The scheduler entry (run every 15 min): post the new webcam video if
          S3 has one, otherwise post a text Captain's Log. Quiet outside the
          active hours window.
  video   Post the webcam clip if there's a new one (no text fallback).
  text    Post a text-only Captain's Log now.
  log     Post a conditions *card* (image) + Captain's Log caption.

Global:
  --dry-run   Force no-post mode (also automatic when no FB token is set).
  --force     Ignore the active-hours window (for `tick`).

Typical cron (VPS, local time):
  */15 * * * *  cd /path/to/buoy-bot && ./.venv/bin/python main.py tick >> state/cron.log 2>&1
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

import config
from buoy import get_conditions_cached, NoDataError, Conditions
from llm import captains_log
import render
import facebook
import video


def _conditions_or_skip(label: str):
    """Return (Conditions, is_live) or None if we should skip (stale/no data)."""
    try:
        c, is_live = get_conditions_cached()
    except NoDataError:
        print(f"[{label}] no data (live gap + no cache) — skipping")
        return None
    age = c.age_minutes()
    if age is not None and age > config.MAX_DATA_AGE_MIN:
        print(f"[{label}] freshest reading {age:.0f} min old (> {config.MAX_DATA_AGE_MIN:.0f}) — skipping")
        return None
    if not is_live:
        print(f"[{label}] live feed empty; using last cached reading")
    return c, is_live


def do_text() -> int:
    got = _conditions_or_skip("text")
    if not got:
        return 0
    c, _ = got
    caption = captains_log(c)
    print(f"[text] posted: {facebook.post_text(caption)}")
    return 0


def do_log() -> int:
    got = _conditions_or_skip("log")
    if not got:
        return 0
    c, _ = got
    card = render.render_conditions_card(c)
    caption = captains_log(c)
    print(f"[log] posted: {facebook.post_photo(card, caption)}")
    return 0


def _post_video(clip) -> int:
    try:
        c, _ = get_conditions_cached()
    except NoDataError:
        c = Conditions()
    caption = captains_log(
        c,
        view_hint="This post is a fresh ~15-second webcam clip looking out from the buoy across Lake Erie.",
    )
    res = facebook.post_video(clip, caption, title="Buffalo Buoy — live look at Lake Erie")
    print(f"[video] posted: {res}")
    return 0


def do_video() -> int:
    clip = video.check_new_video()
    if clip is None:
        print("[video] no new clip since last check")
        return 0
    print(f"[video] new clip downloaded: {clip}")
    return _post_video(clip)


def do_tick(force: bool) -> int:
    now = dt.datetime.now(ZoneInfo(config.TIMEZONE))
    if not force and not (config.ACTIVE_START <= now.hour < config.ACTIVE_END):
        print(f"[tick] {now:%H:%M} outside active window "
              f"{config.ACTIVE_START:02d}:00–{config.ACTIVE_END:02d}:00 — quiet")
        return 0
    clip = video.check_new_video()
    if clip is not None:
        print(f"[tick] new webcam clip — posting video ({clip})")
        return _post_video(clip)
    print("[tick] no new clip — posting text log")
    return do_text()


def main() -> int:
    ap = argparse.ArgumentParser(description="Buffalo Buoy Facebook bot")
    ap.add_argument("command", choices=["tick", "video", "text", "log"])
    ap.add_argument("--dry-run", action="store_true", help="force no-post mode")
    ap.add_argument("--force", action="store_true", help="ignore active-hours window (tick)")
    args = ap.parse_args()

    if args.dry_run:
        config.DRY_RUN = True
    mode = "DRY RUN" if config.DRY_RUN else "LIVE"
    ai = config.OPENAI_MODEL if config.USE_AI_CAPTIONS else "template (no OpenAI key)"
    print(f"— Buffalo Buoy bot [{mode}] · captions: {ai} —")

    return {
        "tick": lambda: do_tick(args.force),
        "video": do_video,
        "text": do_text,
        "log": do_log,
    }[args.command]()


if __name__ == "__main__":
    sys.exit(main())
