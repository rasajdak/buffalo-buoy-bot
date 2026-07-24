"""Out-of-band alerting for failures the bot can't fix itself.

The classic case: Meta puts an identity-confirmation checkpoint on the Page, so
every publish returns Graph error 368 and the bot goes quiet for days without
anyone noticing. This module turns that into a push: it emails you (if SMTP is
configured in .env), and always prints a loud banner to the cron log and records
`state/alerts.json`.

De-duped: a persistent failure notifies at most once per ALERT_RENOTIFY_HOURS, so
you get one heads-up (plus a daily-ish reminder) instead of an email every 15 min.
`clear()` wipes the record once publishing recovers, so the *next* incident alerts
fresh. Nothing in here is allowed to raise — alerting must never crash the bot.
"""

from __future__ import annotations

import datetime as dt
import json
import smtplib
from email.message import EmailMessage

import config

_STATE = config.STATE_DIR / "alerts.json"
_BAR = "!" * 64


def _load() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(state: dict) -> None:
    try:
        _STATE.write_text(json.dumps(state, indent=2))
    except OSError as e:
        print(f"[ALERT] could not write {_STATE}: {e}")


def _send_email(subject: str, body: str) -> bool:
    """Send via SMTP if configured. Returns True if an email actually went out."""
    if not (config.SMTP_HOST and config.ALERT_EMAIL_TO):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM or config.SMTP_USER or config.ALERT_EMAIL_TO
    msg["To"] = config.ALERT_EMAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASS)
        s.send_message(msg)
    return True


def alert(key: str, subject: str, body: str, cooldown_hours: float | None = None) -> None:
    """Raise an alert identified by `key`. Safe to call every tick: emails at most
    once per cooldown window, always leaves a banner in the log."""
    cooldown = config.ALERT_RENOTIFY_HOURS if cooldown_hours is None else cooldown_hours
    now = dt.datetime.now(dt.timezone.utc)
    state = _load()
    rec = state.get(key, {})

    due = True
    last = rec.get("last_notified")
    if last:
        try:
            due = (now - dt.datetime.fromisoformat(last)).total_seconds() >= cooldown * 3600
        except ValueError:
            due = True

    # Always leave a visible trail in the cron log, notified or not.
    print("\n" + _BAR)
    print(f"[ALERT] {subject}")
    print(body)

    rec["last_seen"] = now.isoformat()
    rec.setdefault("first_seen", now.isoformat())

    if not due:
        print(f"[ALERT] already notified within {cooldown:.0f}h — not re-sending")
        print(_BAR + "\n")
        state[key] = rec
        _save(state)
        return

    sent = False
    try:
        sent = _send_email(subject, body)
    except Exception as e:  # noqa: BLE001 — alerting must never crash the bot
        print(f"[ALERT] email send failed: {e}")
    if sent:
        print(f"[ALERT] emailed {config.ALERT_EMAIL_TO}")
    else:
        print("[ALERT] email not sent — set SMTP_HOST/SMTP_USER/SMTP_PASS/ALERT_EMAIL_TO "
              "in .env to get notified off-server")
    print(_BAR + "\n")

    rec["last_notified"] = now.isoformat()
    state[key] = rec
    _save(state)


def clear(key: str) -> None:
    """Clear an alert once its condition recovers, so it can notify fresh next time."""
    state = _load()
    if key in state:
        del state[key]
        _save(state)
        print(f"[ALERT] cleared '{key}' — condition recovered")
