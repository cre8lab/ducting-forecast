"""
Geographic context for tropospheric ducting enhancement.

Large water bodies — particularly the Great Lakes — significantly enhance
ducting conditions for several physical reasons:
  - Stable boundary layer over cool water surfaces reduces turbulent mixing
  - Near-surface evaporation ducts (5-40 m) form over open water; these are
    not resolved by GFS standard pressure levels but are nearly always present
  - Smooth water surface provides long fetch for duct propagation
  - Temperature inversions are more persistent over large thermal reservoirs

The Great Lakes are especially relevant to n41 (2496-2690 MHz) interference:
  - They span 200-500 km — well within single-hop ducting range
  - T-Mobile n41 deployment is dense around the Great Lakes cities
  - Summer ducting events routinely cause 300+ km interference paths
"""

from __future__ import annotations
import math

# ── Great Lakes polygon vertices (lat, lon) ───────────────────────────────────
# Clockwise outlines, simplified to ~20-point polygons.
# Accurate enough for ducting zone classification; not survey-grade.

_GREAT_LAKES: dict[str, list[tuple[float, float]]] = {
    # Polygons trace each lake clockwise.  South shore is the US side;
    # north shore is Canadian (Ontario/Quebec) except Lake Michigan (all-US).
    "Lake Superior": [
        # South shore, east to west (Michigan UP then Minnesota)
        (46.50, -84.50), (46.50, -85.00), (46.50, -86.00),
        (46.55, -86.50), (46.70, -87.00), (46.90, -88.00),
        (47.05, -89.00), (47.20, -90.00), (47.45, -90.50),
        (47.50, -91.50), (47.00, -92.00), (46.80, -92.20),
        # Western end (Duluth/Superior area)
        (47.05, -92.50),
        # North shore, west to east (Ontario)
        (47.80, -92.00), (48.30, -91.00), (48.50, -90.00),
        (48.70, -89.00), (48.80, -88.00), (48.80, -87.00),
        (48.70, -86.00), (48.50, -85.50), (48.20, -85.00),
        (47.80, -84.50),
        # Close back to east end
        (46.50, -84.50),
    ],
    "Lake Michigan": [
        # Southern tip near Chicago/Gary area
        (41.50, -87.50),
        # West shore going north (Illinois → Wisconsin)
        (42.00, -87.80), (42.50, -87.90), (43.00, -87.90),
        (43.50, -87.80), (44.00, -87.70), (44.50, -87.50),
        (45.00, -87.40), (45.50, -87.00), (45.80, -86.60),
        # Northern tip (Straits of Mackinac)
        (46.10, -85.80), (46.10, -85.20),
        # East shore going south (Michigan)
        (45.80, -85.20), (45.00, -85.70), (44.50, -86.20),
        (44.00, -86.35), (43.50, -86.45), (43.00, -86.45),
        (42.50, -86.55), (42.00, -86.80), (41.80, -86.80),
        # Back to southern tip
        (41.50, -87.00), (41.50, -87.50),
    ],
    "Lake Huron": [
        # Southeast corner (near Port Huron, MI)
        (43.00, -82.40),
        # East shore, south to north (Michigan)
        (43.50, -82.50), (44.00, -82.80), (44.50, -83.00),
        (45.00, -83.50), (45.50, -84.00), (45.80, -84.30),
        # Northern tip (near Mackinac Straits, connecting to Lake Michigan)
        (46.10, -84.50),
        # North shore, east (Ontario — Georgian Bay excluded for simplicity)
        (46.00, -82.50), (45.50, -81.20), (44.80, -80.50),
        (44.20, -81.00),
        # South shore back east
        (43.70, -81.50), (43.20, -81.90), (43.00, -82.40),
    ],
    "Lake Erie": [
        # Western end (near Toledo, OH)
        (41.38, -83.50),
        # South shore, west to east (Ohio, Pennsylvania, New York)
        (41.50, -82.50), (41.62, -81.50), (41.80, -80.55),
        (42.00, -79.85), (42.22, -79.20), (42.55, -79.00),
        # Eastern end (near Buffalo)
        (42.90, -78.92),
        # North shore, east to west (Ontario)
        (42.80, -79.50), (42.60, -80.50), (42.40, -81.50),
        (42.10, -82.50), (41.75, -83.10),
        # Close
        (41.38, -83.50),
    ],
    "Lake Ontario": [
        # Western end (near Hamilton/Toronto area)
        (43.20, -79.82),
        # South shore, west to east (New York)
        (43.30, -79.05), (43.52, -78.05), (43.72, -77.05),
        (43.85, -76.52), (44.02, -76.22),
        # Eastern end (near Kingston, ON)
        (44.25, -76.45),
        # North shore, east to west (Ontario)
        (44.35, -77.48), (44.25, -78.50), (44.05, -79.10),
        (43.75, -79.55),
        # Close
        (43.20, -79.82),
    ],
}


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _point_in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _min_dist_to_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> float:
    """Minimum distance (km) from a point to any vertex of a polygon."""
    return min(_haversine_km(lat, lon, py, px) for py, px in poly)


# ── Public API ─────────────────────────────────────────────────────────────────

def water_body_at(lat: float, lon: float) -> str | None:
    """Return the Great Lake the point is over, or None if over land."""
    for name, poly in _GREAT_LAKES.items():
        if _point_in_polygon(lat, lon, poly):
            return name
    return None


def nearest_great_lake(lat: float, lon: float) -> tuple[str | None, float]:
    """
    Return (lake_name, distance_km) for the nearest Great Lake.
    Returns distance 0.0 if the point is already over a lake.
    """
    wb = water_body_at(lat, lon)
    if wb:
        return wb, 0.0

    best_name: str | None = None
    best_dist = float("inf")
    for name, poly in _GREAT_LAKES.items():
        d = _min_dist_to_polygon(lat, lon, poly)
        if d < best_dist:
            best_dist = d
            best_name = name

    return best_name, round(best_dist, 1)


def ducting_environment(lat: float, lon: float) -> dict:
    """
    Characterise the ducting environment at a given location.

    Returns:
      over_water        : bool   — point is over a Great Lake
      water_body        : str|None — lake name if within influence zone
      proximity_km      : float  — 0 if over water, else km to nearest lake
      evap_duct         : bool   — whether to inject a synthetic evaporation duct
      score_multiplier  : float  — risk score multiplier (1.0 = no change)
      enhancement_reason: str    — human-readable explanation for the UI
    """
    wb = water_body_at(lat, lon)

    if wb:
        return {
            "over_water":         True,
            "water_body":         wb,
            "proximity_km":       0.0,
            "evap_duct":          True,
            "score_multiplier":   1.35,
            "enhancement_reason": (
                f"Over {wb}: evaporation duct present; stable boundary layer "
                f"enhances surface ducting probability."
            ),
        }

    name, dist = nearest_great_lake(lat, lon)

    # Coastal enhancement zone: 0-100 km from shore
    # Linearly tapers from 1.20 at shore to 1.00 at 100 km
    COASTAL_KM = 100.0
    if name and dist <= COASTAL_KM:
        factor = 1.0 + 0.20 * (1.0 - dist / COASTAL_KM)
        return {
            "over_water":         False,
            "water_body":         name,
            "proximity_km":       dist,
            "evap_duct":          False,
            "score_multiplier":   round(factor, 3),
            "enhancement_reason": (
                f"{dist:.0f} km from {name}: lake-modified boundary layer "
                f"increases ducting probability near shore."
            ),
        }

    return {
        "over_water":         False,
        "water_body":         name,
        "proximity_km":       round(dist, 1) if name else None,
        "evap_duct":          False,
        "score_multiplier":   1.0,
        "enhancement_reason": "",
    }
