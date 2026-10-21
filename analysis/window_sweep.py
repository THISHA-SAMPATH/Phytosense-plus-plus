r"""Baseline window-size sweep for the bounded-memory claim.
Run from repo root:  python analysis\window_sweep.py      (needs dashboard\engine.py)
Output: out/window_sweep.txt, out/window_sweep.png
Uses the firmware-mirror engine (gate + ring baseline + persistence). z>3, persistence 10, baseline updated every good sample.
False alarms/h = alarm onsets per hour on unlabelled post-fix recordings (first 30 min of each dropped).
Catch rate = synthetic +m SD steps (60 samples) injected every 2400 samples. SYNTHETIC - say so in the report."""
import os, sys, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard"))
import engine

WINDOWS = [60, 120, 300, 600, 1200, 1800, 3600, 7200]     # samples (~seconds)
MAGS = [4, 6, 10]; WARM = 1800; Z, PERS = 3.0, 10
SEGS = [("data/phytosense_trial_log.csv", "2026-10-18 07:33"), ("data/trial_v7.csv", None), ("data/preflight_90min.csv", None)]
D = [engine.load(f, s) for f, s in SEGS]

def onsets(a): return int((a & ~np.roll(a, 1)).sum())

rows = []
for W in WINDOWS:
    engine.BASELINE_N = W; engine.MIN_BASELINE = min(200, W)
    n_on, hrs = 0, 0.0
    caught = {m: 0 for m in MAGS}; tot = {m: 0 for m in MAGS}; lat = {m: [] for m in MAGS}
    for d in D:
        bio = d["bioelectric_raw"].values.astype(float); lp, lm = d["lo_plus"].values, d["lo_minus"].values
        r = engine.run(bio, lp, lm, Z, PERS); a = r["alert"].values[WARM:]
        n_on += onsets(a); hrs += len(a) / 3600
        ev = list(range(2400, len(bio) - 400, 2400))
        for m in MAGS:
            bi = bio.copy()
            for i0 in ev: bi[i0:i0 + 60] += m * np.std(bio[i0 - 1800:i0])
            a2 = engine.run(bi, lp, lm, Z, PERS)["alert"].values
            for i0 in ev:
                w = a2[i0:i0 + 300]; tot[m] += 1
                if w.any(): caught[m] += 1; lat[m].append(int(np.argmax(w)))
    row = {"window_samples": W, "window_min": round(W / 60, 1), "ring_bytes": W * 4, "false_alarms_per_h": round(n_on / hrs, 2)}
    for m in MAGS:
        row[f"catch_{m}sd_%"] = round(100 * caught[m] / max(tot[m], 1)); row[f"latency_{m}sd_s"] = float(np.median(lat[m])) if lat[m] else np.nan
    row["n_events"] = tot[MAGS[0]]; rows.append(row)
df = pd.DataFrame(rows)
os.makedirs("out", exist_ok=True)
txt = df.to_string(index=False); open("out/window_sweep.txt", "w").write(txt); print(txt)
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].plot(df["window_min"], df["catch_6sd_%"], "o-", label="+6 SD"); ax[0].plot(df["window_min"], df["catch_4sd_%"], "s-", label="+4 SD")
ax[0].set_xscale("log"); ax[0].set_xlabel("baseline window (min)"); ax[0].set_ylabel("catch rate % (synthetic)"); ax[0].legend()
ax[1].plot(df["window_min"], df["false_alarms_per_h"], "o-", c="tab:red"); ax[1].set_xscale("log"); ax[1].set_xlabel("baseline window (min)")
ax[1].set_ylabel("false alarms / hour"); ax2 = ax[1].twinx(); ax2.plot(df["window_min"], df["ring_bytes"] / 1024, "k--"); ax2.set_ylabel("ring buffer KB")
plt.tight_layout(); plt.savefig("out/window_sweep.png", dpi=130)