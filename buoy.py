"""
Buffalo Buoy data layer.

Pulls the latest observations for GLOS Seagull platform 666 (Buffalo Buoy, BSU2)
from the public Seagull ERDDAP server and normalizes them into friendly units.

ERDDAP is public, needs no auth, and returns clean JSON. We read the rolling
"latest" dataset and, for each variable, take the most recent non-null value
(different sensors report on different cadences, so a single row is not enough).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import requests

import config

ERDDAP_BASE = "https://seagull-erddap.glos.org/erddap/tabledap"
ERDDAP_URL = f"{ERDDAP_BASE}/obs_666_latest.json"
ERDDAP_THERMISTOR_URL = f"{ERDDAP_BASE}/obs_666_thermistor_latest.json"
PLATFORM_NAME = "Buffalo Buoy"
PLATFORM_REGION = "Lake Erie"
CONSOLE_URL = "https://seagull.glos.org/data-console/666"

REQUEST_TIMEOUT = 30


class NoDataError(RuntimeError):
    """Raised when ERDDAP returns no rows (a data gap or reload)."""


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


def get_conditions(url: str = ERDDAP_URL) -> Conditions:
    """Fetch and normalize the latest conditions.

    Primary source is obs_666_latest. If it is empty we still try the
    thermistor dataset so we can at least report water temperature.
    Raises NoDataError only if *everything* is empty.
    """
    try:
        raw = fetch_latest_raw(url)
    except NoDataError:
        raw = {}
    if "sea_surface_temperature" not in raw:
        try:  # thermistor dataset carries water temperature during main-sensor gaps
            traw = fetch_latest_raw(ERDDAP_THERMISTOR_URL)
            for k, v in traw.items():
                raw.setdefault(k, v)
        except NoDataError:
            pass
    if not raw:
        raise NoDataError("no data from any obs_666 dataset")

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

    # water
    if (v := val("sea_surface_temperature")) is not None:
        c.water_temp_f = k_to_f(v)
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
        "sea_surface_temperature", "air_temperature",
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


def get_conditions_cached(url: str = ERDDAP_URL) -> tuple[Conditions, bool]:
    """Return (conditions, is_live). Falls back to the cached snapshot on a gap."""
    try:
        c = get_conditions(url)
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
