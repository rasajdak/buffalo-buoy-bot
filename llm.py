"""Captain's Log caption writer (OpenAI).

Writes the post in the voice of a weathered old Lake Erie sailor, grounded on the
real buoy readings. The historical/local fact is AI-generated (not a canned list)
with two guardrails:
  1) accuracy — the model is told not to invent dates, names, or numbers;
  2) variety  — recently-used facts are tracked in state and fed back as an
     "avoid" list so it doesn't repeat itself.
Falls back to a plain template (using facts.py) if no API key or the call fails.
"""

from __future__ import annotations

import json

import requests

import config
from buoy import Conditions, CONSOLE_URL
from content import stamp, n, HASHTAGS

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
RECENT_FACTS_FILE = config.STATE_DIR / "recent_facts.json"
ANGLE_STATE_FILE = config.STATE_DIR / "fact_angle.json"
RECENT_KEEP = 60  # how many recent fact-topics to remember / avoid

# Rotating "angle" for each post's fact, so topics spread out instead of the model
# reaching for the same famous one every time. The model supplies the specifics.
FACT_ANGLES = [
    "a Lake Erie shipwreck or maritime disaster",
    "the Erie Canal and how it made Buffalo a boomtown",
    "Buffalo's grain elevators and industrial waterfront history",
    "a Lake Erie or Buffalo-harbor lighthouse",
    "fish species and the lake's famous fishery",
    "birds, wildlife, or the lake's ecology",
    "a memorable storm, gale, or seiche on the lake",
    "ice, freezing, and winter on Lake Erie",
    "the Erie people and the lake's early human history",
    "the War of 1812 and the Battle of Lake Erie",
    "Lake Erie's geography, depth, or size records",
    "the Niagara River outflow and the road to Niagara Falls",
    "lake freighters, ore boats, and Great Lakes shipping",
    "Buffalo's lakefront landmarks and neighborhoods",
    "water quality, algae, and the lake's environmental comeback",
    "lighthouses keepers, sailors' lore, and local legend",
    "record waves, temperatures, or weather extremes on the lake",
    "the buoy itself, GLOS, and how the lake is monitored today",
]


def _next_angle() -> str:
    order = []
    if ANGLE_STATE_FILE.exists():
        order = json.loads(ANGLE_STATE_FILE.read_text()).get("remaining", [])
    if not order or max(order) >= len(FACT_ANGLES):
        import random
        order = list(range(len(FACT_ANGLES)))
        random.shuffle(order)
    idx = order.pop()
    ANGLE_STATE_FILE.write_text(json.dumps({"remaining": order}))
    return FACT_ANGLES[idx]

SYSTEM_PROMPT = """\
You are the voice of the Buffalo Buoy — a data buoy anchored in Lake Erie a couple \
miles off Buffalo, New York. You write its Facebook posts as a weathered, good-humored \
old Great Lakes sailor keeping a ship's log. Salty, warm, and vivid, but never corny.

Each post must:
- Open with "Captain's Log" and the date/time you're given.
- Be SHORT: 2 to 4 tight sentences, ~60-110 words (a social caption).
- Use ONLY the real readings provided. Never invent or contradict numbers.
- Ground the mood in the actual conditions (calm, building seas, a stiff blow, warm water...).
- Include exactly ONE genuinely interesting, ACCURATE fact about Buffalo's harbor or \
Lake Erie — its history, geography, ecology, shipping lore, wildlife, or weather. \
Prefer specific, lesser-known facts, and vary the topic from post to post. \
CRITICAL: only state facts you are confident are true. If unsure of a detail, keep it \
general — never fabricate dates, names, statistics, or events.
- Avoid repeating any fact listed under "Recently used facts."
- Plain text only in the post: no markdown, no hashtags, at most one emoji.

Return a JSON object: {"post": "<the caption text>", "fact_topic": "<3-6 word tag of the fact you used>"}."""


def _load_recent() -> list[str]:
    if RECENT_FACTS_FILE.exists():
        return json.loads(RECENT_FACTS_FILE.read_text())
    return []


def _remember(topic: str) -> None:
    if not topic:
        return
    recent = _load_recent()
    recent.append(topic.strip().lower())
    RECENT_FACTS_FILE.write_text(json.dumps(recent[-RECENT_KEEP:]))


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
    from facts import next_fact
    when = stamp(c.observed_at) if c.observed_at else "this hour"
    bits = []
    if c.wave_sig_ft is not None:
        bits.append(f"seas running {n(c.wave_sig_ft,1)} ft")
    if c.wind_mph is not None:
        bits.append(f"wind {n(c.wind_mph,0)} from the {c.wind_dir or 'open water'}")
    if c.water_temp_f is not None:
        bits.append(f"water at {n(c.water_temp_f,0)}°F")
    cond = ", ".join(bits) if bits else "steady as she goes"
    return f"Captain's Log, {when}. Out here off Buffalo: {cond}. {next_fact()} Fair winds. — the Buffalo Buoy"


def captains_log(c: Conditions, view_hint: str = "") -> str:
    """Return the finished caption text (persona body + link + hashtags)."""
    if not config.USE_AI_CAPTIONS:
        return f"{_fallback(c, view_hint)}\n\n{CONSOLE_URL}\n{HASHTAGS}"

    recent = _load_recent()
    angle = _next_angle()
    user = f"Today's buoy readings:\n{build_data_brief(c)}\n"
    user += (
        f"\nTonight's fact must be about: {angle}. Choose a specific, accurate detail "
        "within that topic; if you're not certain of exact specifics, keep it general "
        "rather than inventing dates, names, or numbers.\n"
    )
    if recent:
        user += "\nRecently used facts (do NOT repeat these):\n- " + "\n- ".join(recent[-30:]) + "\n"
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
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        obj = json.loads(content)
        body = obj["post"].strip()
        _remember(obj.get("fact_topic", ""))
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
