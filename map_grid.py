"""
CONUS-wide ducting grid for thematic map view.

Defines a 2.5° × 3° grid across the continental US (231 points).
Each grid point fetches one Open-Meteo GFS call covering all 7-day
forecast hours, so the full map costs 231 API calls regardless of
how many hours are displayed.

Designed for streaming: analyse_point_all_hours is thread-safe and
synchronous — call it from asyncio.run_in_executor for parallelism.
"""

from __future__ import annotations
from typing import Optional

import geography as geo_mod
import noaa_client as noaa
import physics as phys

# ── CONUS grid definition ─────────────────────────────────────────────────────
LAT_MIN, LAT_MAX, LAT_STEP =  25.0, 50.0, 2.5
LON_MIN, LON_MAX, LON_STEP = -125.0, -65.0, 3.0

FORECAST_HOURS = [0, 12, 24, 36, 48, 72, 96, 120, 144, 168]   # every 12 h for 7 days


def grid_points() -> list[tuple[float, float]]:
    """Return all (lat, lon) grid points for CONUS."""
    pts = []
    lat = LAT_MIN
    while lat <= LAT_MAX + 0.01:
        lon = LON_MIN
        while lon <= LON_MAX + 0.01:
            pts.append((round(lat, 1), round(lon, 1)))
            lon += LON_STEP
        lat += LAT_STEP
    return pts


# ── Per-point analysis ────────────────────────────────────────────────────────
def analyse_point_all_hours(lat: float, lon: float) -> Optional[dict]:
    """
    Fetch one GFS sounding (covers 48 hours) and compute n41 ducting risk
    for each forecast hour.  Returns None on any failure.

    This function is intentionally synchronous and thread-safe.
    """
    try:
        soundings = noaa.fetch_forecast_soundings(lat, lon, hours=FORECAST_HOURS)
        if not soundings:
            return None

        hours_data: dict[str, dict] = {}

        for s in soundings:
            h = s["fcst_hours"]
            levels_raw = s.get("levels", [])
            if len(levels_raw) < 4:
                continue

            pressures  = [lv["pressure_hPa"] for lv in levels_raw]
            heights    = [lv["height_m"]     for lv in levels_raw]
            temps      = [lv["temp_C"]       for lv in levels_raw]
            dewpoints  = [lv["dewpoint_C"]   for lv in levels_raw]

            geo_context = geo_mod.ducting_environment(lat, lon)
            profile = phys.compute_profile(pressures, heights, temps, dewpoints)
            ducts   = phys.detect_ducts(profile)
            risk    = phys.interference_risk(ducts, geo_context)

            hours_data[str(h)] = {
                "score":       risk["score"],
                "level":       risk["level"],
                "n41_ducts":   risk.get("n41_ducts", 0),
                "description": risk["description"],
                "best_duct":   risk.get("best_duct"),
                "over_water":  geo_context.get("over_water", False),
                "water_body":  geo_context.get("water_body"),
            }

        if not hours_data:
            return None

        return {"lat": lat, "lon": lon, "hours": hours_data}

    except Exception:
        return None
