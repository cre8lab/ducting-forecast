"""
NOAA/GFS and ERA5 data client for tropospheric sounding profiles.

Data sources (both via Open-Meteo, free, no API key):
  GFS forecast  — api.open-meteo.com        — up to 7 days ahead, ~0.25° resolution
  ERA5 archive  — archive-api.open-meteo.com — 1979-present (5-day lag), ~0.25° resolution

Pressure levels: 1000→300 hPa (~0–9 km altitude)
Surface level:   2 m temperature, dewpoint, surface pressure added as lowest level.
"""

import json
import ssl
import urllib.request
import urllib.parse
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

# Windows sometimes has stale root certificate bundles.
# This tool is a local research utility; bypassing cert validation is acceptable here.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

FCST_BASE  = "https://api.open-meteo.com/v1/forecast"
ARCH_BASE  = "https://archive-api.open-meteo.com/v1/archive"
GFS_MODEL  = "gfs_seamless"

# Pressure levels to request (hPa), surface → aloft
PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 600, 500, 400, 300]

# Default forecast sample points (every 12 h for 7 days = 15 soundings)
DEFAULT_FCST_HOURS = [0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120, 132, 144, 156, 168]

# ERA5 archive synoptic hours (00/06/12/18 UTC)
HIST_HOURS = [0, 6, 12, 18]

# ERA5 availability lag: archive is typically 5 days behind
ERA5_LAG_DAYS = 5


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def is_historical(date_str: str | None) -> bool:
    """True if date_str is before today's UTC date (use ERA5 archive)."""
    if not date_str:
        return False
    return date_str < _today()


def _fetch_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "n41-ducting-forecast/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def _pressure_vars() -> list[str]:
    """Variable names for all pressure levels."""
    names = []
    for lv in PRESSURE_LEVELS:
        names += [f"temperature_{lv}hPa", f"dewpoint_{lv}hPa", f"geopotential_height_{lv}hPa"]
    return names


def _build_fcst_url(lat: float, lon: float, days: int = 7) -> str:
    vars_list = _pressure_vars() + ["temperature_2m", "dewpoint_2m", "surface_pressure"]
    params = {
        "latitude":      f"{lat:.4f}",
        "longitude":     f"{lon:.4f}",
        "hourly":        ",".join(vars_list),
        "models":        GFS_MODEL,
        "forecast_days": str(days),
        "timezone":      "UTC",
    }
    return FCST_BASE + "?" + urllib.parse.urlencode(params)


def _build_arch_url(lat: float, lon: float, date_str: str) -> str:
    vars_list = _pressure_vars() + ["temperature_2m", "dewpoint_2m", "surface_pressure"]
    params = {
        "latitude":   f"{lat:.4f}",
        "longitude":  f"{lon:.4f}",
        "start_date": date_str,
        "end_date":   date_str,
        "hourly":     ",".join(vars_list),
        "timezone":   "UTC",
    }
    return ARCH_BASE + "?" + urllib.parse.urlencode(params)


def _extract_sounding(
    hourly:    dict,
    h_idx:     int,
    lat:       float,
    lon:       float,
    source:    str,
    elevation: float = 0.0,
) -> Optional[dict]:
    """Extract one vertical sounding from an hourly data block."""
    times  = hourly.get("time", [])
    levels = []

    # Surface 2 m level (best near-surface anchor for the M-profile)
    T2  = hourly.get("temperature_2m",  [None] * (h_idx + 1))[h_idx]
    Td2 = hourly.get("dewpoint_2m",     [None] * (h_idx + 1))[h_idx]
    Ps  = hourly.get("surface_pressure",[None] * (h_idx + 1))[h_idx]
    if T2 is not None and Td2 is not None and Ps is not None and -90 <= T2 <= 60:
        levels.append({
            "pressure_hPa": float(Ps),
            "height_m":     float(elevation) + 2.0,
            "temp_C":       float(T2),
            "dewpoint_C":   float(Td2) if Td2 >= -90 else float(T2) - 25,
        })

    for lv_hPa in PRESSURE_LEVELS:
        T  = hourly.get(f"temperature_{lv_hPa}hPa",        [None] * (h_idx + 1))[h_idx]
        Td = hourly.get(f"dewpoint_{lv_hPa}hPa",           [None] * (h_idx + 1))[h_idx]
        H  = hourly.get(f"geopotential_height_{lv_hPa}hPa",[None] * (h_idx + 1))[h_idx]

        if T is None or Td is None or H is None:
            continue
        if not (-90 <= T <= 60):
            continue
        # Skip levels below the surface 2 m entry
        if levels and H <= levels[0]["height_m"] + 5:
            continue

        levels.append({
            "pressure_hPa": float(lv_hPa),
            "height_m":     float(H),
            "temp_C":       float(T),
            "dewpoint_C":   float(Td) if Td >= -90 else float(T) - 25,
        })

    if len(levels) < 4:
        return None

    return {
        "fcst_hours":  h_idx,
        "valid_time":  times[h_idx] if h_idx < len(times) else None,
        "source":      source,
        "lat":         lat,
        "lon":         lon,
        "elevation_m": elevation,
        "levels":      levels,
    }


# ── Public fetch functions ────────────────────────────────────────────────────

def fetch_forecast_soundings(
    lat:   float,
    lon:   float,
    hours: list[int] | None = None,
    days:  int = 7,
) -> list[dict]:
    """
    Fetch GFS 7-day forecast soundings.

    Args:
        hours: hour indices to sample (default: every 12 h for 7 days).
        days:  forecast window to request from Open-Meteo (1-16).
    """
    if hours is None:
        hours = DEFAULT_FCST_HOURS

    url = _build_fcst_url(lat, lon, days=days)
    raw = _fetch_json(url)
    hourly    = raw.get("hourly", {})
    elevation = raw.get("elevation", 0.0)
    source    = f"NOAA GFS via Open-Meteo ({GFS_MODEL})"

    soundings = []
    for h_idx in hours:
        if h_idx >= len(hourly.get("time", [])):
            continue
        s = _extract_sounding(hourly, h_idx, lat, lon, source, elevation)
        if s:
            soundings.append(s)
    return soundings


def fetch_historical_soundings(
    lat:      float,
    lon:      float,
    date_str: str,
    hours:    list[int] | None = None,
) -> list[dict]:
    """
    Fetch ERA5 reanalysis soundings for a specific past date (YYYY-MM-DD).

    ERA5 archive is available from 1979-01-01 through ~5 days ago.
    """
    if hours is None:
        hours = HIST_HOURS

    url = _build_arch_url(lat, lon, date_str)
    raw = _fetch_json(url)
    hourly    = raw.get("hourly", {})
    elevation = raw.get("elevation", 0.0)
    source    = f"ERA5 Reanalysis via Open-Meteo ({date_str})"

    soundings = []
    for h_idx in hours:
        if h_idx >= len(hourly.get("time", [])):
            continue
        s = _extract_sounding(hourly, h_idx, lat, lon, source, elevation)
        if s:
            soundings.append(s)
    return soundings


def fetch_sounding(lat: float, lon: float, fcst_hours: int = 0) -> Optional[dict]:
    """Fetch a single GFS sounding at the given forecast offset."""
    soundings = fetch_forecast_soundings(lat, lon, hours=[fcst_hours], days=7)
    return soundings[0] if soundings else None
