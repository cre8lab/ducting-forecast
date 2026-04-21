"""
Atmospheric radio refractivity physics for tropospheric ducting prediction.

Theory (ITU-R P.453-14):
  N = 77.6·P/T + 373246·e/T²          (refractivity, N-units)
  M = N + (h/Rₑ)·10⁶                  (modified refractivity, M-units)
  Ducting: dM/dh < 0  ↔  dN/dh < -157 N/km

For 5G n41 (2496–2690 MHz), ducts as thin as ~50m can trap signals
and enable propagation hundreds of km beyond the horizon.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
EARTH_RADIUS_KM = 6371.0
N41_CENTER_MHZ  = 2593.0   # midpoint of n41 (2496–2690 MHz)

# Standard atmosphere refractivity gradient (N/km)
STANDARD_GRADIENT  = -40.0
DUCTING_THRESHOLD  = -157.0   # dN/dh below this → ducting
SUPER_REFRAC_LOWER = -157.0
SUPER_REFRAC_UPPER = -40.0


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class SoundingLevel:
    pressure_hPa:  float
    height_m:      float
    temp_C:        float
    dewpoint_C:    float
    wind_dir:      Optional[float] = None
    wind_spd_kt:   Optional[float] = None
    # Derived
    N:             float = 0.0
    M:             float = 0.0
    dN_dh:         Optional[float] = None   # N/km
    dM_dh:         Optional[float] = None   # M/km
    gradient_class: str = ""


@dataclass
class Duct:
    base_m:         float
    top_m:          float
    delta_M:        float    # duct strength (M-units drop)
    mean_dN_dh:     float    # mean refractivity gradient (N/km)
    duct_type:      str      # "surface" | "elevated"
    # Derived outputs
    traps_n41:      bool     = False
    max_hop_km:     float    = 0.0
    critical_f_MHz: float    = 0.0


# ── Thermodynamics ────────────────────────────────────────────────────────────
def saturation_vapor_pressure(T_K: float) -> float:
    """
    Tetens formula: es (hPa) as function of temperature.
    Valid for liquid water, T in Kelvin.
    """
    T_C = T_K - 273.15
    return 6.1078 * math.exp(17.2694 * T_C / (T_C + 237.29))


def vapor_pressure_from_dewpoint(Td_K: float) -> float:
    """Water vapor partial pressure from dewpoint (Kelvin) → hPa."""
    return saturation_vapor_pressure(Td_K)


# ── Refractivity ──────────────────────────────────────────────────────────────
def refractivity_N(P_hPa: float, T_K: float, e_hPa: float) -> float:
    """
    Radio refractivity per ITU-R P.453-14.

        N = N_dry + N_wet
        N_dry = 77.6 · P / T
        N_wet = 373246 · e / T²

    Args:
        P_hPa:  total atmospheric pressure (hPa)
        T_K:    temperature (K)
        e_hPa:  water vapor partial pressure (hPa)

    Returns N in N-units (dimensionless × 10⁶).
    """
    N_dry = 77.6 * P_hPa / T_K
    N_wet = 373246.0 * e_hPa / (T_K ** 2)
    return N_dry + N_wet


def modified_refractivity_M(N: float, height_km: float) -> float:
    """
    M = N + (h / Rₑ) × 10⁶

    Modified refractivity removes the geometric effect of Earth's curvature.
    Ducting → dM/dh < 0 (trapped ray).
    """
    return N + (height_km / EARTH_RADIUS_KM) * 1e6


def classify_gradient(dN_dh: float) -> str:
    """Classify propagation regime from refractivity gradient (N/km)."""
    if dN_dh > 0:
        return "sub-refractive"
    elif dN_dh > STANDARD_GRADIENT:
        return "normal"
    elif dN_dh > DUCTING_THRESHOLD:
        return "super-refractive"
    else:
        return "ducting"


# ── Profile computation ───────────────────────────────────────────────────────
def compute_profile(
    pressures_hPa: list[float],
    heights_m:     list[float],
    temps_C:       list[float],
    dewpoints_C:   list[float],
    wind_dirs:     list[Optional[float]] = None,
    wind_spds_kt:  list[Optional[float]] = None,
) -> list[SoundingLevel]:
    """
    Compute full refractivity profile from raw sounding data.

    Returns a list of SoundingLevel objects sorted by ascending height,
    with N, M, and inter-level gradients filled in.
    """
    n = len(pressures_hPa)
    if wind_dirs is None:
        wind_dirs = [None] * n
    if wind_spds_kt is None:
        wind_spds_kt = [None] * n

    levels: list[SoundingLevel] = []
    for P, h, T_C, Td_C, wd, ws in zip(
        pressures_hPa, heights_m, temps_C, dewpoints_C, wind_dirs, wind_spds_kt
    ):
        T_K  = T_C  + 273.15
        Td_K = Td_C + 273.15
        e    = vapor_pressure_from_dewpoint(Td_K)
        N    = refractivity_N(P, T_K, e)
        M    = modified_refractivity_M(N, h / 1000.0)
        levels.append(SoundingLevel(
            pressure_hPa=P, height_m=h,
            temp_C=T_C, dewpoint_C=Td_C,
            wind_dir=wd, wind_spd_kt=ws,
            N=round(N, 2), M=round(M, 2),
        ))

    # Sort by height (soundings should already be ordered but enforce it)
    levels.sort(key=lambda lv: lv.height_m)

    # Compute inter-level gradients
    for i in range(1, len(levels)):
        dh_km = (levels[i].height_m - levels[i - 1].height_m) / 1000.0
        if dh_km > 0:
            dN = levels[i].N - levels[i - 1].N
            dM = levels[i].M - levels[i - 1].M
            levels[i].dN_dh         = round(dN / dh_km, 1)
            levels[i].dM_dh         = round(dM / dh_km, 1)
            levels[i].gradient_class = classify_gradient(levels[i].dN_dh)

    if levels:
        levels[0].gradient_class = "surface"

    return levels


# ── Duct detection ────────────────────────────────────────────────────────────
def detect_ducts(profile: list[SoundingLevel]) -> list[Duct]:
    """
    Scan an M-profile for ducting layers.

    Algorithm:
      1. Walk levels looking for where dM/dh < 0 (duct entry).
      2. Track minimum M reached.
      3. Close duct when M recovers to base value OR gradient turns positive.
      4. Classify and characterise each duct.
    """
    ducts: list[Duct] = []

    in_duct       = False
    base_idx      = 0
    M_at_base     = 0.0
    min_M         = 0.0

    for i in range(1, len(profile)):
        lv = profile[i]
        if lv.dM_dh is None:
            continue

        if not in_duct and lv.dM_dh < 0:
            in_duct   = True
            base_idx  = i - 1
            M_at_base = profile[i - 1].M
            min_M     = profile[i].M

        elif in_duct:
            min_M = min(min_M, lv.M)

            # Duct closes when M returns to base or gradient clearly positive
            if lv.M >= M_at_base or (lv.dM_dh > 5 and lv.M > min_M + 2):
                delta_M = M_at_base - min_M
                if delta_M >= 1.0:       # ignore sub-unit noise
                    ducts.append(_characterise_duct(
                        profile, base_idx, i, M_at_base, delta_M
                    ))
                in_duct = False

    # Handle duct that extends to top of sounding
    if in_duct:
        delta_M = M_at_base - min_M
        if delta_M >= 1.0:
            ducts.append(_characterise_duct(
                profile, base_idx, len(profile) - 1, M_at_base, delta_M
            ))

    return ducts


def _characterise_duct(
    profile:   list[SoundingLevel],
    base_idx:  int,
    top_idx:   int,
    M_at_base: float,
    delta_M:   float,
) -> Duct:
    base_h = profile[base_idx].height_m
    top_h  = profile[top_idx].height_m
    dh_km  = (top_h - base_h) / 1000.0

    # Mean dN/dh across duct layers
    grads = [
        lv.dN_dh for lv in profile[base_idx + 1 : top_idx + 1]
        if lv.dN_dh is not None
    ]
    mean_grad = sum(grads) / len(grads) if grads else DUCTING_THRESHOLD

    duct = Duct(
        base_m=base_h,
        top_m=top_h,
        delta_M=round(delta_M, 1),
        mean_dN_dh=round(mean_grad, 1),
        duct_type="surface" if base_h < 200 else "elevated",
    )

    duct.critical_f_MHz = _critical_frequency_MHz(duct)
    duct.traps_n41      = duct.critical_f_MHz <= N41_CENTER_MHZ
    duct.max_hop_km     = _max_hop_km(duct) if duct.traps_n41 else 0.0

    return duct


# ── Duct propagation physics ──────────────────────────────────────────────────
def _critical_frequency_MHz(duct: Duct) -> float:
    """
    Minimum frequency (MHz) trapped by the duct.

    From waveguide analogy (lowest mode):
        f_c = c / (2 · h · √(2·|ΔN|·10⁻⁶))

    A signal at f > f_c is trapped; at f < f_c it leaks out.
    Lower f_c → duct traps higher frequencies (including n41).
    """
    thickness_m = duct.top_m - duct.base_m
    if thickness_m <= 0:
        return float("inf")

    # Approximate total ΔN from mean gradient and thickness
    delta_N = abs(duct.mean_dN_dh) * (thickness_m / 1000.0)
    if delta_N <= 0:
        return float("inf")

    # Speed of light 3e8 m/s, convert to MHz
    f_c_Hz = (3e8 / (2 * thickness_m)) * math.sqrt(1.0 / (2 * delta_N * 1e-6))
    return round(f_c_Hz / 1e6, 0)


def _max_hop_km(duct: Duct) -> float:
    """
    Single-hop maximum range for a signal trapped in the duct.

    Critical grazing angle θ_c = √(2·|ΔN|·10⁻⁶)  [radians]
    Max hop  d = 2 · h_duct / tan(θ_c) ≈ 2 · h_duct / θ_c

    For n41 at 2.5 GHz, typical hops are 200–600 km in moderate ducts.
    """
    thickness_km = (duct.top_m - duct.base_m) / 1000.0
    delta_N = abs(duct.mean_dN_dh) * thickness_km

    if delta_N <= 0 or thickness_km <= 0:
        return 0.0

    theta_c = math.sqrt(2 * delta_N * 1e-6)   # radians
    if theta_c <= 0:
        return 0.0

    return round(2 * thickness_km / theta_c, 0)


def free_space_loss_dB(freq_MHz: float, dist_km: float) -> float:
    """FSPL = 20·log10(f) + 20·log10(d) + 32.45  (dB)"""
    if dist_km <= 0:
        return 0.0
    return 20 * math.log10(freq_MHz) + 20 * math.log10(dist_km) + 32.45


def ducted_path_loss_dB(freq_MHz: float, dist_km: float, delta_M: float) -> float:
    """
    Approximate path loss for ducted propagation.

    Ducting reduces spreading to approximately cylindrical (1/d decay in field,
    i.e. 20·log10(d) instead of 40·log10(d) for power).

    Additional correction for duct strength based on ITU-R P.452 empirical work:
    reduction ≈ 20·log10(delta_M / 10) dB relative to free-space, capped at -40 dB.
    """
    if dist_km <= 0:
        return 0.0
    fspl = free_space_loss_dB(freq_MHz, dist_km)
    # Ducted propagation: replace second 20·log10(d) with 10·log10(d)
    duct_spreading_gain = 10 * math.log10(dist_km)     # recover one order
    duct_strength_bonus = min(20 * math.log10(max(delta_M, 1) / 5.0), 20.0)
    return fspl - duct_spreading_gain - duct_strength_bonus


# ── Evaporation duct (synthetic, for over-water locations) ────────────────────
# GFS pressure levels don't resolve the near-surface evaporation duct (~5-40 m).
# When over a Great Lake we inject a representative duct based on climatological
# values for the Great Lakes region (ITU-R P.1814, Bruninghaus 2002).
_EVAP_DUCT = Duct(
    base_m=0.0,
    top_m=20.0,          # representative Great Lakes evaporation duct height (range 5-40 m)
    delta_M=4.0,         # conservative M-unit deficit; keeps score moderate when no GFS duct present
    mean_dN_dh=-280.0,   # strong gradient in the evaporation layer
    duct_type="surface",
)
_EVAP_DUCT.critical_f_MHz = _critical_frequency_MHz(_EVAP_DUCT)
_EVAP_DUCT.traps_n41      = _EVAP_DUCT.critical_f_MHz <= N41_CENTER_MHZ
_EVAP_DUCT.max_hop_km     = _max_hop_km(_EVAP_DUCT) if _EVAP_DUCT.traps_n41 else 0.0


# ── Risk scoring ──────────────────────────────────────────────────────────────
def interference_risk(
    ducts: list[Duct],
    geo_context: dict | None = None,
) -> dict:
    """
    Compute 5G n41 interference risk from a list of detected ducts.

    Args:
        ducts:       Ducts detected from the GFS sounding profile.
        geo_context: Optional dict from geography.ducting_environment().
                     When provided, applies water body enhancements:
                     - Injects a synthetic evaporation duct if over a Great Lake.
                     - Scales the final score by geo_context['score_multiplier'].

    Score 0–100; level: none / low / moderate / high / severe.
    """
    geo = geo_context or {}
    multiplier = geo.get("score_multiplier", 1.0)

    # Inject synthetic evaporation duct when over open water
    effective_ducts = list(ducts)
    if geo.get("evap_duct") and not any(d.base_m < 50 and d.traps_n41 for d in ducts):
        effective_ducts.insert(0, _EVAP_DUCT)

    if not effective_ducts:
        return {
            "score": 0, "level": "none",
            "description": "No ducting detected. Standard propagation.",
            "ducts": [],
            "water_context": geo,
        }

    n41_ducts = [d for d in effective_ducts if d.traps_n41]
    all_ducts  = [_duct_summary(d) for d in effective_ducts]

    if not n41_ducts:
        return {
            "score": 5, "level": "low",
            "description": (
                f"{len(effective_ducts)} duct(s) present but too thin or weak "
                f"to trap 2.5 GHz. n41 interference unlikely."
            ),
            "ducts": all_ducts,
            "water_context": geo,
        }

    # Pick strongest n41-capable duct
    best = max(n41_ducts, key=lambda d: d.delta_M)

    # Score: 0-40 from duct strength, 0-30 from hop distance, 0-30 from type
    strength_score = min(40, int(best.delta_M * 4))
    hop_score      = min(30, int(best.max_hop_km / 15))
    type_score     = 20 if best.duct_type == "surface" else 10
    raw_score      = strength_score + hop_score + type_score

    # Apply geographic multiplier (water body enhancement)
    score = min(100, int(raw_score * multiplier))

    level_map = [(80, "severe"), (55, "high"), (30, "moderate"), (0, "low")]
    level = next(lv for threshold, lv in level_map if score >= threshold)

    path_loss  = ducted_path_loss_dB(N41_CENTER_MHZ, best.max_hop_km, best.delta_M) if best.max_hop_km > 0 else None
    fspl       = free_space_loss_dB(N41_CENTER_MHZ, best.max_hop_km) if best.max_hop_km > 0 else None
    path_delta = round(fspl - path_loss, 1) if (path_loss and fspl) else None

    description = (
        f"{best.duct_type.title()} duct: {best.base_m:.0f}-{best.top_m:.0f} m, "
        f"strength dM={best.delta_M:.1f}, "
        f"critical f={best.critical_f_MHz:.0f} MHz, "
        f"max single hop ~{best.max_hop_km:.0f} km"
    )
    if path_delta:
        description += f", path loss {path_delta:.0f} dB below free-space"
    if geo.get("enhancement_reason"):
        description += f". {geo['enhancement_reason']}"

    return {
        "score":              score,
        "level":              level,
        "description":        description,
        "n41_ducts":          len(n41_ducts),
        "best_duct":          _duct_summary(best),
        "ducts":              all_ducts,
        "path_loss_dB":       round(path_loss, 1) if path_loss else None,
        "free_space_loss_dB": round(fspl, 1) if fspl else None,
        "path_advantage_dB":  path_delta,
        "water_context":      geo,
    }


def _duct_summary(d: Duct) -> dict:
    return {
        "type":           d.duct_type,
        "base_m":         d.base_m,
        "top_m":          d.top_m,
        "thickness_m":    round(d.top_m - d.base_m, 0),
        "delta_M":        d.delta_M,
        "mean_dN_dh":     d.mean_dN_dh,
        "gradient_class": classify_gradient(d.mean_dN_dh),
        "traps_n41":      d.traps_n41,
        "critical_f_MHz": d.critical_f_MHz,
        "max_hop_km":     d.max_hop_km,
    }
