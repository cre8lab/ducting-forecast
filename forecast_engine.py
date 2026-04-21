"""
Forecast engine: orchestrates NOAA data fetching + physics for a given location.

Produces:
  - Current sounding analysis (N/M profile, duct detection)
  - 48-hour ducting forecast (risk score timeline)
  - Path-loss estimates for n41 interference scenarios
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import geography as geo_mod
import noaa_client as noaa
import physics as phys


# ── Main entry points ─────────────────────────────────────────────────────────

def run_current_analysis(lat: float, lon: float) -> dict:
    """
    Fetch the most recent GFS analysis sounding and compute ducting conditions.
    Returns a complete analysis dict ready for the API to return as JSON.
    """
    sounding = noaa.fetch_sounding(lat, lon, fcst_hours=0)

    if not sounding or not sounding.get("levels"):
        return {
            "error": "Could not retrieve sounding from NOAA. Try again shortly.",
            "lat": lat, "lon": lon,
        }

    return _analyse_sounding(sounding, lat, lon)


def run_forecast(lat: float, lon: float, date: Optional[str] = None) -> dict:
    """
    Fetch soundings for a 7-day GFS forecast or a single ERA5 archive day.

    Args:
        date: ISO date string (YYYY-MM-DD).
              Omit / None  → GFS 7-day forecast from now.
              Past date    → ERA5 reanalysis for that calendar day (4 synoptic hours).
    """
    if date and noaa.is_historical(date):
        soundings = noaa.fetch_historical_soundings(lat, lon, date)
        mode      = "historical"
        source    = f"ERA5 Reanalysis via Open-Meteo ({date})"
    else:
        soundings = noaa.fetch_forecast_soundings(lat, lon)
        mode      = "forecast"
        source    = f"NOAA GFS via Open-Meteo ({noaa.GFS_MODEL})"

    if not soundings:
        return {
            "error": "Could not retrieve soundings from Open-Meteo.",
            "lat": lat, "lon": lon,
        }

    timeline = [_analyse_sounding(s, lat, lon) for s in soundings]

    return {
        "lat":           lat,
        "lon":           lon,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mode":          mode,
        "date":          date,
        "source":        source,
        "data_license":  "Open-Meteo is free for non-commercial use. GFS/ERA5 are public domain.",
        "timeline":      timeline,
        "peak_risk":     _peak_risk(timeline),
    }


# ── Analysis helpers ──────────────────────────────────────────────────────────

def _analyse_sounding(sounding: dict, lat: float, lon: float) -> dict:
    """Convert a raw parsed sounding into a full physics analysis."""
    levels_raw = sounding["levels"]

    # Extract columns
    pressures  = [lv["pressure_hPa"] for lv in levels_raw]
    heights    = [lv["height_m"]     for lv in levels_raw]
    temps      = [lv["temp_C"]       for lv in levels_raw]
    dewpoints  = [lv["dewpoint_C"]   for lv in levels_raw]
    winds_dir  = [lv.get("wind_dir") for lv in levels_raw]
    winds_spd  = [lv.get("wind_spd_kt") for lv in levels_raw]

    # Physics — include water body context for Great Lakes enhancement
    geo_context = geo_mod.ducting_environment(lat, lon)
    profile = phys.compute_profile(pressures, heights, temps, dewpoints, winds_dir, winds_spd)
    ducts   = phys.detect_ducts(profile)
    risk    = phys.interference_risk(ducts, geo_context)

    # Serialize profile for JSON (dataclass → dict)
    profile_json = [
        {
            "pressure_hPa":     lv.pressure_hPa,
            "height_m":         lv.height_m,
            "temp_C":           lv.temp_C,
            "dewpoint_C":       lv.dewpoint_C,
            "N":                lv.N,
            "M":                lv.M,
            "dN_dh":            lv.dN_dh,
            "dM_dh":            lv.dM_dh,
            "gradient_class":   lv.gradient_class,
            "wind_dir":         lv.wind_dir,
            "wind_spd_kt":      lv.wind_spd_kt,
        }
        for lv in profile
    ]

    # Surface N₀ (used as a proxy for refractive conditions)
    N0 = profile[0].N if profile else None

    return {
        "fcst_hours":   sounding.get("fcst_hours", 0),
        "valid_time":   sounding.get("valid_time"),
        "source":       sounding.get("source", "GFS"),
        "lat":          lat,
        "lon":          lon,
        "surface_N":    round(N0, 1) if N0 else None,
        "profile":      profile_json,
        "ducts":        risk.get("ducts", []),
        "risk": {
            "score":              risk["score"],
            "level":              risk["level"],
            "description":        risk["description"],
            "n41_ducts":          risk.get("n41_ducts", 0),
            "best_duct":          risk.get("best_duct"),
            "path_loss_dB":       risk.get("path_loss_dB"),
            "free_space_loss_dB": risk.get("free_space_loss_dB"),
            "path_advantage_dB":  risk.get("path_advantage_dB"),
        },
        "water_context":    geo_context,
        "gradient_summary": _gradient_summary(profile),
    }


def _gradient_summary(profile: list[phys.SoundingLevel]) -> dict:
    """Summarise propagation regime distribution across the sounding."""
    counts = {"sub-refractive": 0, "normal": 0, "super-refractive": 0, "ducting": 0}
    for lv in profile:
        if lv.gradient_class in counts:
            counts[lv.gradient_class] += 1
    return counts


def _peak_risk(timeline: list[dict]) -> dict:
    """Find the highest-risk period in the forecast timeline."""
    if not timeline:
        return {"score": 0, "level": "none"}
    peak = max(timeline, key=lambda t: t["risk"]["score"])
    return {
        "score":      peak["risk"]["score"],
        "level":      peak["risk"]["level"],
        "fcst_hours": peak["fcst_hours"],
        "valid_time": peak["valid_time"],
        "description": peak["risk"]["description"],
    }
