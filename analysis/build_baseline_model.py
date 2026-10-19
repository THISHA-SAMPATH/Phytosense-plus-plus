"""
PhytoSense++ - Personalized bounded-memory baseline + gating ablation (v3)
--------------------------------------------------------------------------
Usage:
  python build_baseline_model.py <trial_csv> <bioelectric_denoised.csv> [out_dir]

Two baselines are run on the SAME recording AND the SAME signal (raw ADC) so the
effect of the gate is measurable and not confounded by filtering:
  GATED   : fixed 30-min window, learns only from samples that pass the quality
            gate (same rules as firmware: contact | rail_hi | rail_lo | flat | jump).
  UNGATED : same window and threshold, learns from every sample, gate ignored.

Both are causal: each sample is scored against the baseline built from the
samples BEFORE it (shift(1)), then added. Deviation = |z| > 3.

Outputs: baseline_model_results.csv, ablation_summary.txt, baseline_ablation.png.
Event markers come from the 'event' column of the log (nothing date-hard-coded).

Read the numbers honestly:
  - With a no-stress recording, every deviation is a FALSE ALARM; real lead-time
    needs a log with a timed stimulus.
  - The gate only helps if the log contains bad samples to reject. If gate_reason
    is 'none' on every row, gated and ungated will behave almost identically.
  - Seconds with no logged sample (recording gaps) count as "not good", so the
    gated arm scores fewer seconds than the ungated arm. Compare deviation counts
    and scored hours, not only the per-hour rate.
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

WINDOW_S = 30 * 60        # bounded memory = 30 min, same as firmware (1800 samples)
MIN_SAMPLES = 200         # cold start, same as firmware
Z_THRESH = 3.0
RAIL_HI = 4090.0
RAIL_LO = 50.0


def good_mask(df):
    if "gate_reason" in df.columns:
        return (df["gate_reason"] == "none") & (df["bioelectric_raw"] < RAIL_HI)
    return ((df["bioelectric_raw"] < RAIL_HI) & (df["bioelectric_raw"] > RAIL_LO)
            & (df["lo_plus"] == 0) & (df["lo_minus"] == 0))


def causal_z(sig):
    """z of each sample vs. the rolling window of PREVIOUS non-NaN samples."""
    r = sig.rolling(f"{WINDOW_S}s", min_periods=MIN_SAMPLES)
    mean = r.mean().shift(1)
    std = r.std().shift(1)
    return (sig - mean) / (std + 1e-6), mean.notna()


def main():
    if len(sys.argv) < 3:
        print("Usage: python build_baseline_model.py <trial_csv> <bioelectric_denoised.csv> [out_dir]")
        sys.exit(1)
    raw_path, den_path = sys.argv[1], sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "."
    os.makedirs(out_dir, exist_ok=True)

    raw = pd.read_csv(raw_path, low_memory=False)
    raw["t"] = pd.to_datetime(raw["wall_clock_time"], format="mixed")
    raw = raw.drop_duplicates("t").sort_values("t").set_index("t")
    raw["good"] = good_mask(raw.reset_index()).to_numpy()

    den = pd.read_csv(den_path)
    den["t"] = pd.to_datetime(den["wall_clock_time"], format="mixed")
    den = den.set_index("t")["bioelectric_denoised"]

    grid = pd.DataFrame(index=raw["bioelectric_raw"].resample("1s").mean().index)
    grid["raw"] = raw["bioelectric_raw"].resample("1s").mean()
    grid["good"] = raw["good"].resample("1s").mean().reindex(grid.index).fillna(0) >= 0.5
    # FIX: log timestamps carry milliseconds, so resample onto the 1 s grid
    # (a plain reindex matches almost nothing and leaves the denoised column empty)
    grid["den"] = den.resample("1s").mean().reindex(grid.index)

    # GATED: raw signal on good samples only (NaN elsewhere = never learned, never scored)
    gated_sig = grid["raw"].where(grid["good"])
    # UNGATED: same raw signal, every sample, gate ignored
    ungated_sig = grid["raw"].interpolate(limit=5)

    grid["z_gated"], grid["ready_gated"] = causal_z(gated_sig)
    grid["z_ungated"], grid["ready_ungated"] = causal_z(ungated_sig)

    def status(row):
        if not row["good"] or pd.isna(row["raw"]):
            return "low_confidence"
        if not row["ready_gated"] or pd.isna(row["z_gated"]):
            return "cold_start"
        return "deviation" if abs(row["z_gated"]) > Z_THRESH else "ok"

    grid["status_gated"] = grid.apply(status, axis=1)
    grid["dev_ungated"] = grid["ready_ungated"] & (grid["z_ungated"].abs() > Z_THRESH)
    grid["dev_gated"] = grid["status_gated"] == "deviation"
    grid.to_csv(os.path.join(out_dir, "baseline_model_results.csv"))

    # events
    events = pd.DataFrame(columns=["t", "event"])
    if "event" in raw.columns:
        e = raw[raw["event"].notna() & (raw["event"].astype(str).str.strip() != "")]
        events = pd.DataFrame({"t": e.index, "event": e["event"].astype(str).values})
    stim = events[events["event"].str.contains("leaf_damage|water_withheld", case=False)]
    first_stim = stim["t"].min() if len(stim) else None

    lines = []
    total_h = len(grid) / 3600
    lines.append(f"Recording span: {total_h:.2f} h on a 1 s grid")
    lines.append(f"Samples passing gate: {grid['good'].mean()*100:.1f}%   (discarded: {(~grid['good']).mean()*100:.1f}%)")
    lines.append(f"Gate reasons in log: {raw['gate_reason'].value_counts().to_dict() if 'gate_reason' in raw.columns else 'not in this log (fallback gate used)'}")
    lines.append(f"Memory: fixed {WINDOW_S} s window (<= {WINDOW_S} samples), independent of run length")

    def per_hour(mask_dev, mask_scored):
        h = mask_scored.sum() / 3600
        return (mask_dev.sum() / h) if h > 0 else float("nan"), int(mask_dev.sum()), h

    if first_stim is None:
        scope = grid.index == grid.index  # whole recording
        lines.append("No stimulus event in the log -> whole recording treated as NO-STRESS; every deviation = false alarm.")
    else:
        scope = grid.index < first_stim
        lines.append(f"First stimulus event at {first_stim}; false alarms counted BEFORE it.")

    sc_g = scope & grid["ready_gated"].to_numpy() & grid["good"].to_numpy()
    sc_u = scope & grid["ready_ungated"].to_numpy()
    rate_g, n_g, h_g = per_hour(grid["dev_gated"].to_numpy() & scope, sc_g)
    rate_u, n_u, h_u = per_hour(grid["dev_ungated"].to_numpy() & scope, sc_u)
    lines.append(f"GATED   : {n_g} deviations over {h_g:.2f} h scored -> {rate_g:.2f} false alarms/h")
    lines.append(f"UNGATED : {n_u} deviations over {h_u:.2f} h scored -> {rate_u:.2f} false alarms/h")

    for _, ev in events.iterrows():
        t0 = ev["t"]
        w = grid.loc[t0: t0 + pd.Timedelta(minutes=60)]
        if len(w) == 0:
            continue
        fg = w.index[w["dev_gated"]]
        fu = w.index[w["dev_ungated"]]
        lg = f"{(fg[0]-t0).total_seconds():.0f} s" if len(fg) else "none in 60 min"
        lu = f"{(fu[0]-t0).total_seconds():.0f} s" if len(fu) else "none in 60 min"
        lines.append(f"Event '{ev['event']}' @ {t0}: first deviation gated={lg}, ungated={lu}")

    summary = "\n".join(lines)
    print(summary)
    with open(os.path.join(out_dir, "ablation_summary.txt"), "w") as f:
        f.write(summary + "\n")

    fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    ax[0].plot(grid.index, grid["raw"], lw=0.4, alpha=0.5, label="raw")
    ax[0].plot(grid.index, grid["den"], lw=0.8, label="denoised (reference only)")
    ax[0].legend(); ax[0].set_ylabel("ADC counts")
    ax[1].plot(grid.index, grid["z_ungated"], lw=0.4, alpha=0.6, label="z ungated")
    ax[1].plot(grid.index, grid["z_gated"], lw=0.6, label="z gated")
    ax[1].axhline(Z_THRESH, color="k", ls=":"); ax[1].axhline(-Z_THRESH, color="k", ls=":")
    ax[1].set_ylim(-15, 15); ax[1].legend(); ax[1].set_ylabel("z-score")
    for _, ev in events.iterrows():
        for a in ax:
            a.axvline(ev["t"], color="red", ls="--", lw=0.8)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "baseline_ablation.png"), dpi=150)
    plt.close()


if __name__ == "__main__":
    main()