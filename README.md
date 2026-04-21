# KD9WXY Tropospheric Ducting Forecast

Physics-based troposcatter/ducting prediction for **5G n41 (2496–2690 MHz)** and amateur radio propagation.

## Live Tool
**[cre8lab.github.io/ducting-forecast](https://cre8lab.github.io/ducting-forecast)**

## What it does
- Fetches **NOAA GFS** vertical profile data (temperature, dewpoint, pressure vs. altitude)
- Computes atmospheric radio refractivity **N** and modified refractivity **M** per **ITU-R P.453-14**
- Detects tropospheric ducts where **dM/dh < 0** (equivalent to dN/dh < −157 N/km)
- Determines whether each duct can trap **2.5 GHz signals** (n41 band)
- Estimates **maximum single-hop distance** and path loss advantage vs. free-space
- Generates a **CONUS thematic heatmap** showing ducting risk across 231 grid points
- 48-hour forecast with hour-by-hour risk timeline

## Physics
| Formula | Meaning |
|---------|---------|
| `N = 77.6·P/T + 373246·e/T²` | Radio refractivity (ITU-R P.453-14) |
| `M = N + (h/Rₑ)·10⁶` | Modified refractivity (Earth curvature corrected) |
| `dM/dh < 0` | **Ducting condition** — ray is trapped |
| `f_c = c/(2h·√(2\|ΔN\|·10⁻⁶))` | Minimum frequency trapped by duct |
| `d = 2·h / θ_c` | Max single-hop range |

For n41 at 2.5 GHz, ducted signals can reach 200–600+ km with path loss 20–40 dB below free-space.

## Data Source
[Open-Meteo API](https://open-meteo.com) — serves **NOAA GFS** model output (US Government public domain).  
No API key required. No backend server needed.

## Deploy to GitHub Pages
```bash
git init
git add index.html README.md
git commit -m "Initial deploy"
git remote add origin https://github.com/cre8lab/ducting-forecast.git
git push -u origin main
```
Then in your GitHub repo: **Settings → Pages → Source: main branch → Save**

Your site will be live at `https://cre8lab.github.io/ducting-forecast/`

---
*KD9WXY — Licensed Amateur Radio Operator*
