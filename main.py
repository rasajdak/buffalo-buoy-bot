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
import json
import sys
from zoneinfo import ZoneInfo

import config
from buoy import get_conditions_cached, NoDataError, Conditions
from content import stamp
from llm import captains_log
import render
import facebook
import notify
import video

LAST_POST_FILE = config.STATE_DIR / "last_posted_reading.json"

# Graph error codes that mean "a human must act" — publishing stays broken until
# then, so we push an alert instead of dying silently in the cron log.
#   368 = identity checkpoint / Page Publishing Authorization
#   190 = access token expired or revoked
FATAL_PUBLISH_CODES = {368, 190}


def _blocked_body(e: facebook.GraphError) -> str:
    if e.code == 368:
        what = (
            "Facebook is requiring identity confirmation before the Page can publish "
            "again. Open the Facebook MOBILE APP as the Page admin and follow the prompt "
            "(check Notifications, Settings → Account Center → identity confirmation, and "
            "the Page's Professional dashboard). No redeploy or token change is needed — "
            "posting resumes on its own within 15 min once you clear it."
        )
    elif e.code == 190:
        what = (
            "The Facebook Page access token is no longer valid (expired or revoked). "
            "Generate a fresh non-expiring Page token and update FB_PAGE_TOKEN in "
            "/opt/buffalo-buoy/.env, then it'll resume."
        )
    else:
        what = "Publishing to the Page failed in a way that needs a look."
    return (
        f"{what}\n\n"
        f"Graph API said: {e.fb_message}\n"
        f"(code {e.code}, subcode {e.subcode})\n\n"
        f"The bot keeps trying every 15 min; you'll get at most one alert per "
        f"{config.ALERT_RENOTIFY_HOURS:.0f}h until it recovers."
    )


def _time_context() -> tuple[str, bool]:
    """(daypart phrase, is-final-post-of-day) from the current local time.

    The last active slot is the :45 of the final active hour (cadence 15,45), so
    the goodnight fires there.
    """
    now = dt.datetime.now(ZoneInfo(config.TIMEZONE))
    h = now.hour
    if h < 11:
        daypart = "morning — the day just getting going"
    elif h < 15:
        daypart = "midday, sun high"
    elif h < 18:
        daypart = "late afternoon"
    elif h < 21:
        daypart = "evening, the day winding down"
    else:
        daypart = "late evening, near nightfall"
    sign_off = (h == config.ACTIVE_END - 1 and now.minute >= 30)
    return daypart, sign_off


def _reading_is_new(c) -> bool:
    """True unless we've already posted this exact buoy reading (by observed_at)."""
    if c.observed_at is None or not LAST_POST_FILE.exists():
        return True
    try:
        last = json.loads(LAST_POST_FILE.read_text()).get("observed_at")
    except (json.JSONDecodeError, OSError):
        return True
    return last != c.observed_at.isoformat()


def _mark_posted(c) -> None:
    """Record the reading we just posted (skipped in dry-run so tests are side-effect-free)."""
    if config.DRY_RUN or c.observed_at is None:
        return
    LAST_POST_FILE.write_text(json.dumps({"observed_at": c.observed_at.isoformat()}))


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


def do_text(force: bool = False) -> int:
    got = _conditions_or_skip("text")
    if not got:
        return 0
    c, _ = got
    if not force and not _reading_is_new(c):
        print(f"[text] reading unchanged since last post ({stamp(c.observed_at)}) — skipping")
        return 0
    daypart, sign_off = _time_context()
    caption = captains_log(c, daypart=daypart, sign_off=sign_off)
    print(f"[text] posted: {facebook.post_text(caption)}")
    _mark_posted(c)
    return 0


def do_log(force: bool = False) -> int:
    got = _conditions_or_skip("log")
    if not got:
        return 0
    c, _ = got
    if not force and not _reading_is_new(c):
        print(f"[log] reading unchanged since last post ({stamp(c.observed_at)}) — skipping")
        return 0
    card = render.render_conditions_card(c)
    daypart, sign_off = _time_context()
    caption = captains_log(c, daypart=daypart, sign_off=sign_off)
    print(f"[log] posted: {facebook.post_photo(card, caption)}")
    _mark_posted(c)
    return 0


def _post_video(clip) -> int:
    try:
        c, _ = get_conditions_cached()
    except NoDataError:
        c = Conditions()
    daypart, sign_off = _time_context()
    caption = captains_log(
        c,
        view_hint="This post is a fresh ~15-second webcam clip looking out from the buoy across Lake Erie.",
        daypart=daypart, sign_off=sign_off,
    )
    res = facebook.post_video(clip, caption, title="Buffalo Buoy — live look at Lake Erie")
    print(f"[video] posted: {res}")
    _mark_posted(c)  # so the next text tick won't parrot the same reading
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
    ap.add_argument("--force", action="store_true",
                    help="post regardless of hours window / unchanged-reading skip")
    args = ap.parse_args()

    if args.dry_run:
        config.DRY_RUN = True
    mode = "DRY RUN" if config.DRY_RUN else "LIVE"
    ai = config.OPENAI_MODEL if config.USE_AI_CAPTIONS else "template (no OpenAI key)"
    print(f"— Buffalo Buoy bot [{mode}] · captions: {ai} —")

    try:
        return {
            "tick": lambda: do_tick(args.force),
            "video": do_video,
            "text": lambda: do_text(args.force),
            "log": lambda: do_log(args.force),
        }[args.command]()
    except facebook.GraphError as e:
        if e.code in FATAL_PUBLISH_CODES:
            notify.alert(
                facebook.PUBLISH_BLOCKED,
                subject=f"Buffalo Buoy bot: publishing blocked (Graph error {e.code})",
                body=_blocked_body(e),
            )
            return 1
        raise  # transient/unknown Graph errors keep the old loud-traceback behavior


if __name__ == "__main__":
    sys.exit(main())
