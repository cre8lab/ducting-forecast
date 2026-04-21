"""
Quick sanity-check for the physics module.
Runs offline — no NOAA data needed.
"""

import physics as phys

# Synthetic sounding with a realistic surface duct.
# Strong temperature inversion + sharp humidity drop at 0–300m.
# Required for ducting: dN/dh < -157 N/km → M decreases with height.
# This mirrors typical pre-frontal or post-sunset coastal conditions.

pressures  = [1013, 1005,  995,  980,  960,  940,  920,  900,  870,  840,  800,  750]
heights    = [   0,   100,  200,  300,  500,  700,  900, 1100, 1450, 1800, 2500, 3200]
#              warm humid base → strong inversion at 100-300m + rapid dew-point drop
temps      = [22.0,  26.0, 24.0, 18.0, 13.0, 10.0,  7.0,  4.0,  1.0, -2.0, -7.0, -14.0]
dewpoints  = [21.0,  15.0,  2.0, -2.0, -4.0, -3.0, -2.0, -4.0, -7.0,-12.0,-17.0, -24.0]

profile = phys.compute_profile(pressures, heights, temps, dewpoints)

print("Modified Refractivity Profile:")
print(f"{'Height':>8}  {'N':>8}  {'M':>8}  {'dM/dh':>8}  {'Class'}")
print("-" * 55)
for lv in profile:
    dM = f"{lv.dM_dh:+.1f}" if lv.dM_dh is not None else "   —"
    print(f"{lv.height_m:8.0f}  {lv.N:8.1f}  {lv.M:8.1f}  {dM:>8}  {lv.gradient_class}")

ducts = phys.detect_ducts(profile)
print(f"\nDucts detected: {len(ducts)}")
for d in ducts:
    print(f"  {d.duct_type} duct  {d.base_m:.0f}-{d.top_m:.0f}m  "
          f"dM={d.delta_M:.1f}  traps_n41={d.traps_n41}  "
          f"max_hop={d.max_hop_km:.0f}km  "
          f"f_crit={d.critical_f_MHz:.0f}MHz")

risk = phys.interference_risk(ducts)
print(f"\nRisk: {risk['level'].upper()}  score={risk['score']}")
print(f"  {risk['description']}")

# Spot-check a known N value: standard sea-level (~313 N-units)
N_check = phys.refractivity_N(1013.25, 288.15, 7.5)
print(f"\nStandard sea-level N check: {N_check:.1f}  (expect ~315 N-units)")
