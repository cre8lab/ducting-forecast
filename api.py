"""
FastAPI server — KD9WXY Troposcatter/Ducting Forecast Tool.

Endpoints:
  GET /                                    → frontend
  GET /api/current?lat=&lon=               → current sounding analysis (GFS hour 0)
  GET /api/forecast?lat=&lon=              → 7-day GFS forecast timeline
  GET /api/forecast?lat=&lon=&date=YYYY-MM-DD → ERA5 archive for a past date
  GET /api/map/stream                      → SSE stream of CONUS grid (all hours)
  GET /api/geocode?q=Green+Bay+WI         → city/state → lat/lon
  GET /api/physics                         → physics reference
"""

import asyncio
import json as json_lib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import forecast_engine as engine
import map_grid
import physics as phys

app = FastAPI(
    title="KD9WXY Tropospheric Ducting Forecast",
    description="Physics-based troposcatter/ducting prediction for 5G n41 and amateur radio",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

FRONTEND_PATH = Path(__file__).parent / "frontend" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def root():
    if not FRONTEND_PATH.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return HTMLResponse(content=FRONTEND_PATH.read_text(encoding="utf-8"))


@app.get("/api/current")
async def current_analysis(
    lat: float = Query(..., ge=-90,   le=90),
    lon: float = Query(..., ge=-180,  le=180),
):
    try:
        result = engine.run_current_analysis(lat, lon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return JSONResponse(content=result)


@app.get("/api/forecast")
async def forecast(
    lat:  float = Query(..., ge=-90,  le=90),
    lon:  float = Query(..., ge=-180, le=180),
    date: str   = Query(None, description="YYYY-MM-DD — omit for GFS 7-day, supply a past date for ERA5 archive"),
):
    try:
        result = engine.run_forecast(lat, lon, date=date)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return JSONResponse(content=result)


@app.get("/api/map/stream")
async def map_stream():
    """
    Server-Sent Events stream of CONUS ducting grid.

    Each message is a JSON object with type 'point' | 'skip' | 'done'.
    Type 'point' includes lat/lon + risk scores for all forecast hours,
    so the client can switch hours instantly without re-fetching.

    Fires 231 parallel GFS requests (one per grid point, 15 workers).
    Each request already covers all forecast hours, so total API calls = 231.
    """
    async def generate():
        points = map_grid.grid_points()
        total  = len(points)
        done   = 0

        loop = asyncio.get_event_loop()

        # Yield a header so the client knows the total count immediately
        yield f"data: {json_lib.dumps({'type': 'start', 'total': total})}\n\n"

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [
                loop.run_in_executor(executor, map_grid.analyse_point_all_hours, lat, lon)
                for lat, lon in points
            ]
            for fut in asyncio.as_completed(futures):
                result = await fut
                done += 1
                if result:
                    yield f"data: {json_lib.dumps({'type': 'point', 'data': result, 'progress': done, 'total': total})}\n\n"
                else:
                    yield f"data: {json_lib.dumps({'type': 'skip', 'progress': done, 'total': total})}\n\n"

        yield f"data: {json_lib.dumps({'type': 'done', 'total': total})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=2)):
    """
    Convert a city/state string to lat/lon using the US Census Bureau geocoder.
    Entirely .gov — no API key required.
    Falls back to Open-Meteo geocoding for non-US lookups.
    """
    import urllib.request, urllib.parse, ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    # US state abbreviation → full name map for result filtering
    US_STATES = {
        "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
        "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
        "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
        "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
        "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi",
        "MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
        "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
        "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
        "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee",
        "TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington",
        "WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"District of Columbia",
    }

    # Parse "City, ST" or "City, State" — search by city name, filter by state
    parts  = [p.strip() for p in q.split(",", 1)]
    city   = parts[0]
    state_hint = parts[1].upper().strip() if len(parts) > 1 else None
    state_full = US_STATES.get(state_hint, state_hint)  # expand abbrev if possible

    # Primary: Open-Meteo geocoding (GeoNames data)
    om_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=10&language=en&format=json"
    try:
        req = urllib.request.Request(om_url, headers={"User-Agent": "kd9wxy-ducting/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            data = json_lib.loads(r.read())
        results = data.get("results", [])
        if state_full and results:
            # Prefer results matching the state hint
            filtered = [r for r in results if state_full.lower() in (r.get("admin1") or "").lower()]
            if filtered:
                results = filtered
        if results:
            hit = results[0]
            label_parts = [p for p in [hit.get("name"), hit.get("admin1"), hit.get("country_code")] if p]
            label = ", ".join(label_parts)
            return {"lat": hit["latitude"], "lon": hit["longitude"], "label": label, "source": "Open-Meteo geocoder"}
    except Exception:
        pass

    # Fallback: US Census Bureau geocoder (works for full street addresses)
    census_url = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        f"?address={urllib.parse.quote(q)}&benchmark=2020&format=json"
    )
    try:
        req = urllib.request.Request(census_url, headers={"User-Agent": "kd9wxy-ducting/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            data = json_lib.loads(r.read())
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            return {"lat": coords["y"], "lon": coords["x"], "label": matches[0]["matchedAddress"], "source": "US Census Bureau"}
    except Exception:
        pass

    raise HTTPException(status_code=404, detail=f"Location not found: {q}")


@app.get("/api/physics")
async def physics_reference():
    return {
        "refractivity_equation": "N = 77.6*P/T + 373246*e/T^2  (ITU-R P.453-14)",
        "modified_refractivity": "M = N + (h/Re)*10^6  (h in km, Re=6371 km)",
        "ducting_condition":     "dM/dh < 0  <->  dN/dh < -157 N/km",
        "gradient_thresholds": {
            "sub_refractive":   "dN/dh > 0",
            "normal":           "-40 < dN/dh <= 0",
            "super_refractive": "-157 < dN/dh <= -40",
            "ducting":          "dN/dh <= -157",
        },
        "n41_band":         {"name": "5G NR n41", "range_MHz": "2496-2690", "center_MHz": phys.N41_CENTER_MHZ},
        "critical_angle":   "theta_c = sqrt(2*|dN|*1e-6)  [radians]",
        "max_hop":          "d = 2*h_duct / theta_c  [km]",
        "critical_freq":    "f_c = c / (2*h*sqrt(2*|dN|*1e-6))  [Hz]",
        "data_source":      "NOAA GFS via Open-Meteo API (public domain)",
        "earth_radius_km":  phys.EARTH_RADIUS_KM,
        "call_sign":        "KD9WXY",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
