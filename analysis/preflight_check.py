"""
PhytoSense++ — preflight go/no-go check.

Run on a 2-3 hour log recorded with the electrode ON THE PLANT, before you start
the real multi-day trial:

    python analysis/preflight_check.py path/to/preflight_log.csv [planned_trial_hours]

The pass/fail lines are proposed criteria (not standards): adjust them if you
have a reason, but write the reason down.
"""

import sys
import numpy as np
import pandas as pd

RAIL = 4090.0
FLOOR = 50.0

if len(sys.argv) < 2:
    print("Usage: python preflight_check.py <csv> [planned_trial_hours]")
    sys.exit(1)

path = sys.argv[1]
planned_h = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

df = pd.read_csv(path)
df["t"] = pd.to_datetime(df["wall_clock_time"], format="mixed")
df = df.drop_duplicates("t").sort_values("t").set_index("t")
bio = df["bioelectric_raw"].astype(float)
soil = df["soil_raw"].astype(float)

hours = (df.index[-1] - df.index[0]).total_seconds() / 3600
m = bio.resample("1min").median().dropna()
sm = soil.resample("1min").median().reindex(m.index)

rail_frac = float((bio >= RAIL).mean())
t_h = (m.index - m.index[0]).total_seconds() / 3600
slope = float(np.polyfit(t_h, m.values, 1)[0]) if len(m) > 10 else float("nan")
last = float(m.iloc[-60:].median())
med = float(bio.median())
noise = bio.resample("1s").mean().interpolate(limit=5).rolling(60).std().median()
corr = float(m.corr(sm)) if sm.notna().sum() > 10 else float("nan")
resets = int((df["uptime_ms"].diff() < 0).sum())

if slope > 1e-6:
    h_to_rail = (RAIL - last) / slope
else:
    h_to_rail = float("inf")
if slope < -1e-6:
    h_to_floor = (last - FLOOR) / (-slope)
else:
    h_to_floor = float("inf")

print(f"rows={len(df)}  span={hours:.1f} h  median={med:.0f}  last-hour median={last:.0f}")
print(f"drift={slope:+.1f} counts/h  typical 60 s SD={noise:.1f}  soil-vs-bio corr={corr:+.2f}  reboots={resets}")
if "gate_reason" in df.columns:
    print("gate reasons:", df["gate_reason"].value_counts().to_dict())

checks = [
    ("log is at least 2 h long",                    hours >= 2.0),
    ("railed samples < 1 %",                        rail_frac < 0.01),
    ("baseline sits mid-scale (1000-3000)",         1000 <= med <= 3000),
    (f"projected time to rail > {planned_h:.0f} h",  h_to_rail > planned_h),
    (f"projected time to floor > {planned_h:.0f} h", h_to_floor > planned_h),
    ("soil channel not tracking bio (|r| < 0.9)",   (not np.isnan(corr)) and abs(corr) < 0.9),
    ("no unexplained reboots",                      resets == 0),
]
ok = True
for name, passed in checks:
    print(("PASS  " if passed else "FAIL  ") + name)
    ok = ok and passed
print("\nVERDICT:", "GO - start the trial" if ok else "NO-GO - fix the failed items first")
print("Note: the drift estimate from a short log is rough; a longer preflight is better.")