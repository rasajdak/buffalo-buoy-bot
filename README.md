# Buffalo Buoy → Facebook bot

Auto-posts conditions and webcam clips from the **Buffalo Buoy** (GLOS Seagull
platform 666, Lake Erie) to a Facebook Page, written in the voice of an old
Lake Erie sailor keeping a "Captain's Log."

## What it posts
- **`log`** — a conditions card (waves / wind / water & air temp) + a Captain's Log
  caption: sailor-voice commentary interpreting the live conditions.
- **`video`** — the buoy's ~16s webcam clip whenever S3 publishes a new one, with a
  matching caption. (The clip lives at a single overwriting URL and is *not*
  archived, so we grab each new one before it's replaced.)

## Data sources (all public, no scraping)
- Conditions: Seagull ERDDAP `obs_666_latest` (JSON). Resilient to gaps — falls
  back to the thermistor dataset, then to the last cached reading.
- Video: `https://seagull-webcams.s3.us-east-2.amazonaws.com/BSU2/BSU2_latest.mp4`
  (1080p H.264). New-clip detection via ETag/Last-Modified.

## Setup
```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill in values (see below)
chmod 600 .env
```

`.env` keys:
- `FB_PAGE_ID`, `FB_PAGE_TOKEN` — never-expiring Page token (already provisioned).
- `OPENAI_API_KEY` — enables the AI Captain's Log voice. Without it, posts use a
  clean plain-text template (bot still runs).
- `OPENAI_MODEL` — default `gpt-4o-mini`.
- `TIMEZONE` — default `America/New_York`.
- Alert thresholds — see `config.py`.

If `FB_PAGE_TOKEN` is unset, everything runs in **DRY RUN** automatically.

## Run
```bash
./.venv/bin/python main.py both --dry-run   # print, don't post
./.venv/bin/python main.py video            # post webcam clip if new
./.venv/bin/python main.py log              # post a conditions card + log
```

## Schedule (VPS cron, times local)
```cron
*/15 6-21 * * *  cd /path/to/buoy-bot && ./.venv/bin/python main.py video >> state/cron.log 2>&1
0 8,13,19 * * *  cd /path/to/buoy-bot && ./.venv/bin/python main.py log   >> state/cron.log 2>&1
```
`video` runs often through daylight to catch each new clip; `log` runs 3×/day.

## Files
| file | role |
|------|------|
| `buoy.py` | ERDDAP fetch + unit conversion + snapshot cache |
| `video.py` | webcam-clip poller / downloader |
| `llm.py` | OpenAI Captain's Log writer — commentary on current conditions (+ template fallback) |
| `render.py` | conditions card (PNG) |
| `content.py` | formatting + non-AI caption/alert text |
| `facebook.py` | Graph API posting (photo/video/text), DRY_RUN-aware |
| `main.py` | CLI orchestrator |

## Not yet wired
- Threshold **alerts** (big waves / gales / algae) — config + copy exist in
  `config.py` / `content.py`; the trigger loop is a small future add.
