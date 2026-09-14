"""
PhytoSense++ — Stage 4: Personalized Bounded-Memory Baseline Model

This is the core patent mechanism, demonstrated offline against real trial
data before being ported to firmware:

  1. PERSONALIZED, BOUNDED-MEMORY BASELINE:
     A fixed-size rolling window (not a growing, ever-larger history) tracks
     this specific plant's own recent "normal" signal. Memory footprint stays
     constant regardless of how long the device has been running.

  2. CONFIDENCE-GATED UPDATES:
     The baseline is only updated using readings where electrode contact was
     good (lo_plus=0 AND lo_minus=0). A low-confidence reading is still
     logged and checked for deviation, but never allowed to corrupt the
     learned baseline.

  3. DEVIATION / EVENT FLAGGING:
     A reading is flagged as a deviation when it falls more than
     DEVIATION_THRESHOLD standard deviations from the current rolling
     baseline mean, using ONLY the baseline as computed up to that point
     (causal — never looks into the future).

Inputs:
  - bioelectric_denoised.csv  (wall_clock_time, bioelectric_raw, bioelectric_denoised)
  - phytosense_trial_log.csv  (for lo_plus/lo_minus contact-quality gating)

Output:
  - baseline_model_results.csv  (per-sample baseline, deviation flag)
  - baseline_model_verification.png (plot around the known damage event)
"""

import pandas as pd
import numpy as np

# ---- Config (bounded-memory window + sensitivity) ----
BASELINE_WINDOW_SECONDS = 30 * 60   # 30-minute rolling window = the "bounded memory"
DEVIATION_THRESHOLD_STD = 3.0       # flag a reading > 3 std from rolling baseline
MIN_BASELINE_SAMPLES = 200          # cold-start threshold, matches firmware's COLD_START_THRESHOLD

DAMAGE_TIME = pd.Timestamp("2026-09-12 21:30:00")

# ---- Load ----
den = pd.read_csv("../data/bioelectric_denoised.csv")
den["wall_clock_time"] = pd.to_datetime(den["wall_clock_time"])

raw = pd.read_csv("../data/phytosense_trial_log.csv")
raw["wall_clock_time"] = pd.to_datetime(raw["wall_clock_time"])

# Bring contact-quality (lo_plus/lo_minus) onto the denoised timeline via nearest match
contact = raw[["wall_clock_time", "lo_plus", "lo_minus"]].sort_values("wall_clock_time")
den = den.sort_values("wall_clock_time")
den = pd.merge_asof(den, contact, on="wall_clock_time", direction="nearest", tolerance=pd.Timedelta("2s"))
den["lo_plus"] = den["lo_plus"].fillna(1)   # treat unmatched rows as bad-contact, safest default
den["lo_minus"] = den["lo_minus"].fillna(1)
den["contact_ok"] = (den["lo_plus"] == 0) & (den["lo_minus"] == 0)

# Resample onto a clean, uniform 1-second grid (mean where multiple samples share a second)
den = den.set_index("wall_clock_time")
uniform = den[["bioelectric_denoised", "contact_ok"]].resample("1s").mean()
uniform["contact_ok"] = uniform["contact_ok"] >= 0.5   # majority-good within that second
uniform["bioelectric_denoised"] = uniform["bioelectric_denoised"].interpolate(limit=5)
uniform = uniform.dropna(subset=["bioelectric_denoised"])

# ---- Bounded-memory personalized baseline (causal rolling stats over GOOD-CONTACT samples only) ----
# Confidence gating: replace bad-contact samples with NaN before rolling, so they never
# influence the learned baseline mean/std — this is the "confidence-gated update" mechanism.
gated_signal = uniform["bioelectric_denoised"].where(uniform["contact_ok"])

baseline_mean = gated_signal.rolling(f"{BASELINE_WINDOW_SECONDS}s", min_periods=MIN_BASELINE_SAMPLES).mean()
baseline_std  = gated_signal.rolling(f"{BASELINE_WINDOW_SECONDS}s", min_periods=MIN_BASELINE_SAMPLES).std()

uniform["baseline_mean"] = baseline_mean
uniform["baseline_std"] = baseline_std
uniform["baseline_ready"] = uniform["baseline_mean"].notna()

# ---- Deviation flagging (cold-start / low-confidence / ok / deviation) ----
def classify(row):
    if not row["contact_ok"]:
        return "low_confidence"
    if not row["baseline_ready"]:
        return "cold_start"
    z = abs(row["bioelectric_denoised"] - row["baseline_mean"]) / (row["baseline_std"] + 1e-6)
    return "deviation" if z > DEVIATION_THRESHOLD_STD else "ok"

uniform["status"] = uniform.apply(classify, axis=1)
uniform["z_score"] = (uniform["bioelectric_denoised"] - uniform["baseline_mean"]) / (uniform["baseline_std"] + 1e-6)

uniform.to_csv("../data/baseline_model_results.csv")

print("Status counts:")
print(uniform["status"].value_counts())
print()

# ---- Check specifically around the known damage event ----
window = uniform.loc[DAMAGE_TIME - pd.Timedelta(minutes=10): DAMAGE_TIME + pd.Timedelta(minutes=60)]
dev_rows = window[window["status"] == "deviation"]
print(f"Deviation-flagged rows in the 10-min-before to 60-min-after damage window: {len(dev_rows)} / {len(window)}")
if len(dev_rows) > 0:
    first_dev = dev_rows.index[0]
    delay = (first_dev - DAMAGE_TIME).total_seconds()
    print(f"First deviation flagged at: {first_dev}  ({delay:+.0f} seconds relative to damage timestamp)")
    print(f"Max |z-score| in window: {window['z_score'].abs().max():.2f}")
else:
    print("No deviation flagged in this window at current threshold.")