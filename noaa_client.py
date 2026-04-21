"""
NOAA/GFS data client for tropospheric sounding profiles.

Data source: Open-Meteo API (https://open-meteo.com)
  - Free, no API key required
  - Ingests NOAA GFS (Global Forecast System) model output
  - Returns vertical profiles (T, Td, H) at 12 pressure levels
  - 48-hour forecast, 1-hour time steps, ~0.25° resolution

The underlying atmospheric model (GFS) is produced by NOAA/NCEP
and is in the public domain as a US Government work.

Pressure levels available: 1000→300 hPa (~0–9 km)
"""

import json
import ssl
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

# Windows sometimes has stale root certificate bundles.
# This tool is a local research utility; bypassing cert validation is acceptable here.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

API_BASE = "https://api.open-meteo.com/v1/forecast"
GFS_MODEL = "gfs_seamless"   # NOAA GFS + high-res GFS ensemble

# Pressure levels to request (hPa), ordered surface → aloft
PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 600, 500, 400, 300]


def _fetch_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "n41-ducting-forecast/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def _build_url(lat: float, lon: float) -> str:
    vars_list = []
    for lv in PRESSURE_LEVELS:
        vars_list += [
            f"temperature_{lv}hPa",
            f"dewpoint_{lv}hPa",
            f"geopotential_height_{lv}hPa",
        ]

    params = {
        "latitude":     f"{lat:.4f}",
        "longitude":    f"{lon:.4f}",
        "hourly":       ",".join(vars_list),
        "models":       GFS_MODEL,
        "forecast_days": "2",
        "timezone":     "UTC",
    }
    return API_BASE + "?" + urllib.parse.urlencode(params)


def fetch_forecast_soundings(
    lat: float,
    lon: float,
    hours: list[int] = None,
) -> list[dict]:
    """
    Fetch GFS vertical profile data for (lat, lon) and reshape into
    a list of per-hour sounding dicts suitable for the physics engine.

    Returns soundings at hour indices specified in `hours`
    (default: [0, 6, 12, 18, 24, 30, 36, 42, 47]).
    """
    if hours is None:
        hours = [0, 6, 12, 18, 24, 30, 36, 42, 47]

    url = _build_url(lat, lon)
    raw = _fetch_json(url)

    hourly = raw.get("hourly", {})
    times  = hourly.get("time", [])

    soundings = []
    for h_idx in hours:
        if h_idx >= len(times):
            continue
        s = _extract_sounding(hourly, h_idx, lat, lon)
        if s and len(s["levels"]) >= 4:
            soundings.append(s)

    return soundings


def fetch_sounding(lat: float, lon: float, fcst_hours: int = 0) -> Optional[dict]:
    """
    Fetch a single sounding at the given forecast offset.
    """
    soundings = fetch_forecast_soundings(lat, lon, hours=[fcst_hours])
    return soundings[0] if soundings else None


def _extract_sounding(hourly: dict, h_idx: int, lat: float, lon: float) -> dict:
    """
    Extract one vertical sounding from the hourly data array at index h_idx.
    """
    levels = []
    times  = hourly.get("time", [])

    for lv_hPa in PRESSURE_LEVELS:
        t_key  = f"temperature_{lv_hPa}hPa"
        td_key = f"dewpoint_{lv_hPa}hPa"
        h_key  = f"geopotential_height_{lv_hPa}hPa"

        T  = hourly.get(t_key,  [None] * (h_idx + 1))[h_idx]
        Td = hourly.get(td_key, [None] * (h_idx + 1))[h_idx]
        H  = hourly.get(h_key,  [None] * (h_idx + 1))[h_idx]

        if T is None or Td is None or H is None:
            continue

        # Sanity bounds
        if not (-90 <= T <= 60):
            continue
        if not (-90 <= Td <= T + 1):
            Td = T - 25   # fallback: assume 25°C dewpoint depression

        levels.append({
            "pressure_hPa": float(lv_hPa),
            "height_m":     float(H),
            "temp_C":       float(T),
            "dewpoint_C":   float(Td),
        })

    valid_time = times[h_idx] if h_idx < len(times) else None

    return {
        "fcst_hours":    h_idx,
        "valid_time":    valid_time,
        "source":        f"NOAA GFS via Open-Meteo ({GFS_MODEL})",
        "lat":           lat,
        "lon":           lon,
        "levels":        levels,
        "request_url":   _build_url(lat, lon),
    }
