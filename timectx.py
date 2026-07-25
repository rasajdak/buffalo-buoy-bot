"""Rich time-awareness for the Captain's Log.

Assembles a labelled context block — weekday/weekend, season, sun position
(pre-dawn, first light, golden hour, after dark), and holidays — so each post
knows exactly *when* it's going out. Sunrise/sunset are computed offline (NOAA
sunrise equation) for the buoy's location; no extra dependency, no API.
"""

from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

import config

LAT, LON = 42.8467, -78.9032  # the buoy, in Lake Erie off Buffalo
TZ = ZoneInfo(config.TIMEZONE)


# ---------------------------------------------------------------------------
# Sunrise / sunset (NOAA / "Almanac" algorithm)
# ---------------------------------------------------------------------------
def _sun_event(date: dt.date, is_rise: bool) -> dt.datetime | None:
    zenith = 90.833  # official sunrise/sunset, accounts for refraction + sun radius
    N = date.timetuple().tm_yday
    lng_hour = LON / 15.0
    t = N + (((6 if is_rise else 18) - lng_hour) / 24)
    M = (0.9856 * t) - 3.289
    L = (M + 1.916 * math.sin(math.radians(M))
         + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    RA += ((L // 90) * 90) - ((RA // 90) * 90)  # put RA in same quadrant as L
    RA /= 15
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_H = ((math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(LAT)))
             / (cos_dec * math.cos(math.radians(LAT))))
    if cos_H > 1 or cos_H < -1:
        return None  # sun never rises / never sets that day
    H = (360 - math.degrees(math.acos(cos_H))) if is_rise else math.degrees(math.acos(cos_H))
    H /= 15
    T = H + RA - (0.06571 * t) - 6.622
    ut = (T - lng_hour) % 24
    base = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)
    guess = base + dt.timedelta(hours=ut)
    # UT is modulo 24 and can land a day off (e.g. evening-local sunset is early-
    # morning UTC); snap so the event falls on `date` in local time.
    guess += dt.timedelta(days=(date - guess.astimezone(TZ).date()).days)
    return guess


def sun_times(date: dt.date) -> tuple[dt.datetime | None, dt.datetime | None]:
    sr = _sun_event(date, True)
    ss = _sun_event(date, False)
    return (sr.astimezone(TZ) if sr else None, ss.astimezone(TZ) if ss else None)


def _sun_phase(now: dt.datetime, sr: dt.datetime | None, ss: dt.datetime | None) -> str:
    if sr is None or ss is None:
        return "hard to say where the sun sits today"
    mins = lambda d: (now - d).total_seconds() / 60
    if now < sr - dt.timedelta(minutes=45):
        return "well before dawn, still dark on the water"
    if now < sr:
        return "first light coming, sky beginning to grey"
    if mins(sr) < 50:
        return "just after sunrise — first light on the water"
    if now < ss - dt.timedelta(minutes=70):
        # daytime: crude morning/midday/afternoon by fraction of daylight
        frac = (now - sr) / (ss - sr)
        return ("morning sun climbing" if frac < 0.38
                else "midday, sun high" if frac < 0.62
                else "afternoon light, sun past its peak")
    if now < ss:
        return "golden hour — sun getting low, the day winding down"
    if mins(ss) < 55:
        return "dusk, sun just set, light fading fast"
    return "night, dark out on the lake"


# ---------------------------------------------------------------------------
# Calendar context
# ---------------------------------------------------------------------------
def _season(date: dt.date) -> str:
    m = date.month
    return {
        12: "early winter", 1: "the deep of winter", 2: "late winter",
        3: "early spring", 4: "spring", 5: "late spring",
        6: "early summer", 7: "high summer", 8: "the dog days of late summer",
        9: "early fall", 10: "autumn", 11: "late fall",
    }[m]


def _holiday(date: dt.date) -> str | None:
    m, d, wd = date.month, date.day, date.weekday()  # Mon=0
    fixed = {(1, 1): "New Year's Day", (7, 4): "Independence Day",
             (10, 31): "Halloween", (11, 11): "Veterans Day",
             (12, 24): "Christmas Eve", (12, 25): "Christmas",
             (12, 31): "New Year's Eve"}
    if (m, d) in fixed:
        return fixed[(m, d)]
    if m == 5 and wd == 0 and d >= 25:
        return "Memorial Day"
    if m == 9 and wd == 0 and d <= 7:
        return "Labor Day"
    if m == 11 and wd == 3 and 22 <= d <= 28:
        return "Thanksgiving"
    return None


def build(now: dt.datetime | None = None,
          first_of_day: bool = False, last_of_day: bool = False) -> str:
    now = now or dt.datetime.now(TZ)
    sr, ss = sun_times(now.date())
    lines = [f"Now: {now:%A, %B %-d, %-I:%M %p %Z}"]
    lines.append("Weekend" if now.weekday() >= 5 else "A weekday")
    lines.append(f"Season: {_season(now.date())}")
    if sr and ss:
        lines.append(f"Sunrise {sr:%-I:%M %p}, sunset {ss:%-I:%M %p} — {_sun_phase(now, sr, ss)}")
    else:
        lines.append(f"Sun: {_sun_phase(now, sr, ss)}")
    h = _holiday(now.date())
    if h:
        lines.append(f"Holiday: {h}")
    if first_of_day:
        lines.append("This is the FIRST post of the day.")
    if last_of_day:
        lines.append("This is the LAST post of the day.")
    return "\n".join(f"- {x}" for x in lines)


if __name__ == "__main__":
    today = dt.datetime.now(TZ)
    sr, ss = sun_times(today.date())
    print("sunrise:", sr and sr.strftime("%-I:%M %p"), "| sunset:", ss and ss.strftime("%-I:%M %p"))
    print("\ncontext block now:\n" + build(first_of_day=False, last_of_day=False))
