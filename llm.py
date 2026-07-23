"""Captain's Log caption writer (OpenAI).

Writes the post in the voice of a weathered old Lake Erie sailor, as vivid
commentary on the CURRENT conditions — the mood of the lake and what the
readings mean for anyone on the water. No history/trivia. To keep the 15-minute
cadence from repeating, each post is nudged toward a rotating "focus" and recent
angles are fed back as an avoid-list. Falls back to a plain template if there's
no API key or the call fails.
"""

from __future__ import annotations

import json

import requests

import config
from buoy import Conditions, CONSOLE_URL
from content import stamp, n, HASHTAGS

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
RECENT_FILE = config.STATE_DIR / "recent_gists.json"
FOCUS_STATE_FILE = config.STATE_DIR / "commentary_focus.json"
RECENT_KEEP = 40

# Rotating angle so consecutive posts about similar readings still feel fresh.
FOCI = [
    "the sea state — what the waves feel like out here right now",
    "the wind, its direction, and what it's doing to the surface of the lake",
    "the water temperature and what it means for swimmers, anglers, or a dip",
    "the sky and the barometer — what the pressure hints about the hours ahead",
    "the overall mood of the lake right now (glassy, restless, moody, lively)",
    "what kind of day it is for small boats, kayaks, or heading out to fish",
    "the feel of the air and the season out on the water",
    "how the lake is behaving compared to its usual quick-to-chop temperament",
]


def _next_focus() -> str:
    order = []
    if FOCUS_STATE_FILE.exists():
        order = json.loads(FOCUS_STATE_FILE.read_text()).get("remaining", [])
    if not order or max(order) >= len(FOCI):
        import random
        order = list(range(len(FOCI)))
        random.shuffle(order)
    idx = order.pop()
    FOCUS_STATE_FILE.write_text(json.dumps({"remaining": order}))
    return FOCI[idx]


SYSTEM_PROMPT = """\
You are the voice of the Buffalo Buoy — a data buoy anchored in Lake Erie a couple \
miles off Buffalo, New York. You write its Facebook posts as a weathered, good-humored \
old Great Lakes sailor keeping a ship's log. Salty, warm, and vivid, but never corny.

Each post must:
- Open with "Captain's Log" and the date/time you're given.
- Be SHORT: 2 to 4 tight sentences, ~50-90 words.
- Use ONLY the real readings provided. Never invent or contradict a number.
- Paint the fuller picture EVERY time: work in the key conditions you're given — at \
minimum the waves, the wind, AND the water temperature (add air temp or pressure when \
they add something). Don't build a whole post around a single number.
- Be COMMENTARY, not a readout: interpret the conditions — the lake's mood right now and \
what it means for anyone on the water (boaters, anglers, swimmers).
- Treat the given angle as your LENS and emphasis — the thread you pull hardest — not the \
only thing you mention.
- NO history lessons, trivia, dates, or facts about the past. Stay in the present moment.
- Plain text only: no markdown, no hashtags, at most one emoji.

Return a JSON object: {"post": "<the caption text>", "gist": "<3-6 word tag of the angle you took>"}."""


def _load_recent() -> list[str]:
    if RECENT_FILE.exists():
        return json.loads(RECENT_FILE.read_text())
    return []


def _remember(gist: str) -> None:
    if not gist:
        return
    recent = _load_recent()
    recent.append(gist.strip().lower())
    RECENT_FILE.write_text(json.dumps(recent[-RECENT_KEEP:]))


def build_data_brief(c: Conditions) -> str:
    parts = []
    if c.observed_at:
        parts.append(f"Local time: {stamp(c.observed_at)}")
    if c.wave_sig_ft is not None:
        s = f"Waves: {n(c.wave_sig_ft,1)} ft significant"
        if c.wave_max_ft is not None:
            s += f", peaking ~{n(c.wave_max_ft,1)} ft"
        if c.wave_period_s:
            s += f", {n(c.wave_period_s,0)} s apart"
        parts.append(s)
    if c.wind_mph is not None:
        parts.append(f"Wind: {n(c.wind_mph,0)} mph from the {c.wind_dir or '?'}")
    if c.water_temp_f is not None:
        parts.append(f"Water temp: {n(c.water_temp_f,0)} F")
    if c.air_temp_f is not None:
        parts.append(f"Air temp: {n(c.air_temp_f,0)} F")
    if c.pressure_inhg is not None:
        parts.append(f"Pressure: {n(c.pressure_inhg,2)} inHg")
    if c.humidity_pct is not None:
        parts.append(f"Humidity: {n(c.humidity_pct,0)}%")
    if c.phycocyanin_rfu is not None and c.phycocyanin_rfu >= config.ALGAE_WATCH_RFU:
        parts.append(f"Note: blue-green algae indicator elevated ({n(c.phycocyanin_rfu,2)} RFU)")
    return "\n".join(parts) or "Readings temporarily unavailable."


def _fallback(c: Conditions, view_hint: str = "") -> str:
    when = stamp(c.observed_at) if c.observed_at else "this hour"
    bits = []
    if c.wave_sig_ft is not None:
        bits.append(f"seas running {n(c.wave_sig_ft,1)} ft")
    if c.wind_mph is not None:
        bits.append(f"wind {n(c.wind_mph,0)} from the {c.wind_dir or 'open water'}")
    if c.water_temp_f is not None:
        bits.append(f"water at {n(c.water_temp_f,0)}°F")
    if c.air_temp_f is not None:
        bits.append(f"air {n(c.air_temp_f,0)}°F")
    cond = ", ".join(bits) if bits else "steady as she goes"
    return f"Captain's Log, {when}. Out here off Buffalo: {cond}. Fair winds. — the Buffalo Buoy"


def captains_log(c: Conditions, view_hint: str = "") -> str:
    """Return the finished caption text (persona body + link + hashtags)."""
    if not config.USE_AI_CAPTIONS:
        return f"{_fallback(c, view_hint)}\n\n{CONSOLE_URL}\n{HASHTAGS}"

    recent = _load_recent()
    focus = _next_focus()
    user = f"Current buoy readings:\n{build_data_brief(c)}\n"
    user += (f"\nLead with this angle as your lens (but still work in the waves, wind, "
             f"and water temp): {focus}\n")
    if recent:
        user += "\nRecent angles (take a different one):\n- " + "\n- ".join(recent[-12:]) + "\n"
    if view_hint:
        user += f"\nContext: {view_hint}\n"

    try:
        r = requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "temperature": 1.0,
                "max_tokens": 320,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        r.raise_for_status()
        obj = json.loads(r.json()["choices"][0]["message"]["content"])
        body = obj["post"].strip()
        _remember(obj.get("gist", ""))
    except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"[llm] OpenAI call failed ({e}); using fallback caption")
        body = _fallback(c, view_hint)

    return f"{body}\n\n{CONSOLE_URL}\n{HASHTAGS}"


if __name__ == "__main__":
    from buoy import load_snapshot
    c = load_snapshot()
    if c is None:
        print("no snapshot to test with")
    else:
        for i in range(5):
            print(f"\n===== {i+1} =====")
            print(captains_log(c))
