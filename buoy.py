"""
Buffalo Buoy data layer.

Pulls the latest observations for the Buffalo Buoy (GLOS Seagull dataset 666,
BSU2) and normalizes them into friendly units.

Two sources, tried in order:
  1) the live Seagull app API (`seagull-api.glos.org`) — same feed the web
     console uses, ~20-30 min fresh. WAF-protected, so we send browser-like
     headers. Values arrive as {parameter_id: observations}; we map ids -> CF
     standard names via /v1/parameters (cached to disk).
  2) the ERDDAP mirror (`seagull-erddap.glos.org`) — public, stable, but lags
     ~45 min. Used as an automatic fallback.
Both yield a dict {standard_name: (value, time_iso)} in SI units, normalized
by the same code path.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Optional

import requests

import config

# --- live app API (fresher) ---
APP_BASE = "https://seagull-api.glos.org/api"
APP_OBS_DATASET_ID = 666
APP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
    "Origin": "https://seagull.glos.org",
    "Referer": "https://seagull.glos.org/",
}
PARAM_MAP_CACHE = config.STATE_DIR / "param_map.json"

# --- ERDDAP mirror (stable fallback) ---
ERDDAP_BASE = "https://seagull-erddap.glos.org/erddap/tabledap"
ERDDAP_URL = f"{ERDDAP_BASE}/obs_666_latest.json"
ERDDAP_THERMISTOR_URL = f"{ERDDAP_BASE}/obs_666_thermistor_latest.json"

PLATFORM_NAME = "Buffalo Buoy"
PLATFORM_REGION = "Lake Erie"
CONSOLE_URL = "https://seagull.glos.org/data-console/666"

REQUEST_TIMEOUT = 30


class NoDataError(RuntimeError):
    """Raised when a source returns no usable observations (gap/reload)."""


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
def k_to_f(k: float) -> float:
    return (k - 273.15) * 9 / 5 + 32


def k_to_c(k: float) -> float:
    return k - 273.15


def ms_to_mph(ms: float) -> float:
    return ms * 2.2369362920544


def ms_to_kn(ms: float) -> float:
    return ms * 1.9438444924406


def m_to_ft(m: float) -> float:
    return m * 3.280839895


def pa_to_inhg(pa: float) -> float:
    return pa / 3386.389


_COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def deg_to_compass(deg: float) -> str:
    return _COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


# ---------------------------------------------------------------------------
# Raw fetch
# ---------------------------------------------------------------------------
def fetch_latest_raw(url: str = ERDDAP_URL) -> dict:
    """Return {column_name: (value, time_iso)} of most-recent non-null per column.

    Raises NoDataError when the (rolling) dataset is currently empty — ERDDAP
    signals this with a 404 whose body says 'nRows = 0'.
    """
    r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"Accept": "application/json"})
    if r.status_code == 404 and "nRows = 0" in r.text:
        raise NoDataError(f"{url}: dataset currently empty")
    r.raise_for_status()
    table = r.json()["table"]
    cols = table["columnNames"]
    rows = table["rows"]
    if not rows:
        raise NoDataError(f"{url}: no rows")
    time_idx = cols.index("time")

    latest: dict[str, tuple] = {}
    for row in rows:  # rows are in ascending time order
        t = row[time_idx]
        for i, name in enumerate(cols):
            v = row[i]
            if v is None:
                continue
            prev = latest.get(name)
            if prev is None or t >= prev[1]:
                latest[name] = (v, t)
    return latest


def _erddap_raw() -> dict:
    """ERDDAP fallback: obs_666_latest, backfilled by the thermistor dataset."""
    try:
        raw = fetch_latest_raw(ERDDAP_URL)
    except NoDataError:
        raw = {}
    if "sea_surface_temperature" not in raw:
        try:
            for k, v in fetch_latest_raw(ERDDAP_THERMISTOR_URL).items():
                raw.setdefault(k, v)
        except NoDataError:
            pass
    if not raw:
        raise NoDataError("ERDDAP: no data from any obs_666 dataset")
    return raw


# ---------------------------------------------------------------------------
# Live app API (fresher than ERDDAP)
# ---------------------------------------------------------------------------
def _param_map(refresh: bool = False) -> dict:
    """{parameter_id: standard_name} for the buoy, cached to disk."""
    if not refresh and PARAM_MAP_CACHE.exists():
        return {int(k): v for k, v in json.loads(PARAM_MAP_CACHE.read_text()).items()}
    r = requests.get(f"{APP_BASE}/v1/parameters?obsDatasetId={APP_OBS_DATASET_ID}",
                     headers=APP_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    m = {p["parameter_id"]: p["standard_name"]
         for p in r.json() if p.get("standard_name")}
    PARAM_MAP_CACHE.write_text(json.dumps(m))
    return m


def fetch_app_latest() -> dict:
    """Live app feed -> {standard_name: (value, time_iso)}.

    /v2/obs-latest returns every dataset; we keep dataset 666. For a standard
    name reported at multiple depths (e.g. the thermistor chain), we keep the
    shallowest reading. Raises NoDataError if the dataset/params are missing.
    """
    r = requests.get(f"{APP_BASE}/v2/obs-latest?platformId={APP_OBS_DATASET_ID}",
                     headers=APP_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    ours = [d for d in r.json() if d.get("obs_dataset_id") == APP_OBS_DATASET_ID]
    if not ours:
        raise NoDataError("app API: dataset 666 not present")

    pmap = _param_map()
    ids = [p["parameter_id"] for p in ours[0]["parameters"]]
    if not any(i in pmap for i in ids):  # ids changed upstream -> refresh cache once
        pmap = _param_map(refresh=True)

    best: dict[str, tuple] = {}  # name -> (value, ts_iso, depth)
    for par in ours[0]["parameters"]:
        name = pmap.get(par["parameter_id"])
        obs = par.get("observations") or []
        if not name or not obs:
            continue
        o = obs[-1]
        depth = o.get("depth") or 0.0
        ts = dt.datetime.fromtimestamp(o["timestamp"], dt.timezone.utc).isoformat()
        prev = best.get(name)
        if prev is None or depth < prev[2]:
            best[name] = (o["value"], ts, depth)
    if not best:
        raise NoDataError("app API: no mappable parameters")
    return {k: (v[0], v[1]) for k, v in best.items()}


# ---------------------------------------------------------------------------
# Normalized conditions
# ---------------------------------------------------------------------------
@dataclass
class Conditions:
    observed_at: Optional[dt.datetime] = None  # newest timestamp among core sensors
    # waves
    wave_sig_ft: Optional[float] = None
    wave_max_ft: Optional[float] = None
    wave_period_s: Optional[float] = None
    wave_dir_deg: Optional[float] = None
    # wind
    wind_mph: Optional[float] = None
    wind_kn: Optional[float] = None
    wind_dir_deg: Optional[float] = None
    # water
    water_temp_f: Optional[float] = None
    turbidity: Optional[float] = None
    do_mg_l: Optional[float] = None
    # air
    air_temp_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    pressure_inhg: Optional[float] = None
    # water quality
    chlorophyll_rfu: Optional[float] = None
    phycocyanin_rfu: Optional[float] = None
    # bookkeeping
    _times: dict = field(default_factory=dict, repr=False)

    @property
    def wind_dir(self) -> Optional[str]:
        return deg_to_compass(self.wind_dir_deg) if self.wind_dir_deg is not None else None

    @property
    def wave_dir(self) -> Optional[str]:
        return deg_to_compass(self.wave_dir_deg) if self.wave_dir_deg is not None else None

    def age_minutes(self) -> Optional[float]:
        if self.observed_at is None:
            return None
        now = dt.datetime.now(dt.timezone.utc)
        return (now - self.observed_at).total_seconds() / 60


def _parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def get_conditions() -> Conditions:
    """Fetch and normalize the latest conditions.

    Tries the live app API first (fresher); on any failure falls back to the
    ERDDAP mirror. Raises NoDataError only if both are unavailable/empty.
    """
    raw = None
    try:
        raw = fetch_app_latest()
    except (NoDataError, requests.RequestException) as e:
        print(f"[buoy] live app API unavailable ({e}); falling back to ERDDAP")
    if not raw:
        raw = _erddap_raw()  # raises NoDataError if it too is empty

    def val(name):
        return raw[name][0] if name in raw else None

    c = Conditions()
    c._times = {k: v[1] for k, v in raw.items()}

    # waves
    if (v := val("sea_surface_wave_significant_height")) is not None:
        c.wave_sig_ft = m_to_ft(v)
    if (v := val("sea_surface_wave_maximum_height")) is not None:
        c.wave_max_ft = m_to_ft(v)
    c.wave_period_s = val("sea_surface_wave_period_at_variance_spectral_density_maximum")
    c.wave_dir_deg = val("sea_surface_wave_from_direction")

    # wind
    if (v := val("wind_speed")) is not None:
        c.wind_mph = ms_to_mph(v)
        c.wind_kn = ms_to_kn(v)
    c.wind_dir_deg = val("wind_from_direction")

    # water  (ERDDAP: sea_surface_temperature · app API: sea_water_temperature)
    _wt = val("sea_surface_temperature")
    if _wt is None:
        _wt = val("sea_water_temperature")
    if _wt is not None:
        c.water_temp_f = k_to_f(_wt)
    c.turbidity = val("sea_water_turbidity")
    if (v := val("mass_concentration_of_oxygen_in_sea_water")) is not None:
        c.do_mg_l = v * 1000.0  # kg/m^3 -> mg/L

    # air
    if (v := val("air_temperature")) is not None:
        c.air_temp_f = k_to_f(v)
    c.humidity_pct = val("relative_humidity")
    if (v := val("air_pressure_at_mean_sea_level")) is not None:
        c.pressure_inhg = pa_to_inhg(v)

    # water quality
    c.chlorophyll_rfu = val("chlorophyll_fluorescence")
    c.phycocyanin_rfu = val("phycocyanin_fluorescence")

    # freshest timestamp among the core sensors we actually post
    core = [
        "sea_surface_wave_significant_height", "wind_speed",
        "sea_surface_temperature", "sea_water_temperature", "air_temperature",
    ]
    stamps = [_parse_time(raw[n][1]) for n in core if n in raw]
    if stamps:
        c.observed_at = max(stamps)

    return c


_SNAPSHOT_FIELDS = [
    "wave_sig_ft", "wave_max_ft", "wave_period_s", "wave_dir_deg",
    "wind_mph", "wind_kn", "wind_dir_deg", "water_temp_f", "turbidity",
    "do_mg_l", "air_temp_f", "humidity_pct", "pressure_inhg",
    "chlorophyll_rfu", "phycocyanin_rfu",
]


def save_snapshot(c: Conditions, path=None) -> None:
    import json
    path = path or (config.STATE_DIR / "last_conditions.json")
    data = {f: getattr(c, f) for f in _SNAPSHOT_FIELDS}
    data["observed_at"] = c.observed_at.isoformat() if c.observed_at else None
    path.write_text(json.dumps(data, indent=1))


def load_snapshot(path=None) -> Optional[Conditions]:
    import json
    path = path or (config.STATE_DIR / "last_conditions.json")
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    c = Conditions()
    for f in _SNAPSHOT_FIELDS:
        setattr(c, f, data.get(f))
    if data.get("observed_at"):
        c.observed_at = _parse_time(data["observed_at"])
    return c


def get_conditions_cached() -> tuple[Conditions, bool]:
    """Return (conditions, is_live). Falls back to the cached snapshot on a gap."""
    try:
        c = get_conditions()
        save_snapshot(c)
        return c, True
    except (NoDataError, requests.RequestException):
        cached = load_snapshot()
        if cached is None:
            raise
        return cached, False


if __name__ == "__main__":
    from pprint import pprint
    try:
        c = get_conditions()
        pprint(c)
        print("age (min):", round(c.age_minutes(), 1) if c.age_minutes() is not None else None)
    except NoDataError as e:
        print("NO LIVE DATA:", e)
