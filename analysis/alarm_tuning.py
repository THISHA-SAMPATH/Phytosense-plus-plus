r"""Alarm tuning: false alarms/hour vs catch rate for z-threshold x persistence.
Run from repo root:  python analysis\alarm_tuning.py
Output: out/alarm_tuning.txt, out/alarm_tuning.png
- Clean data = post-fix recordings (Oct 18 07:33 onward + v7 trial + preflight), first 30 min of each dropped.
- False alarms/h = alarm onsets per hour on that data (NOT labelled; real environmental events also count).
- Catch rate = synthetic step anomalies (+m SD, 60 s) injected every 40 min. SYNTHETIC, say so in the report.
"""
import numpy as np, pandas as pd, matplotlib, os
matplotlib.use("Agg"); import matplotlib.pyplot as plt

def load(path, start=None, end=None):
    d = pd.read_csv(path); d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t").set_index("t")
    if start: d = d[start:]
    if end: d = d[:end]
    b = d["bioelectric_raw"].resample("1s").mean().interpolate(limit=3)  # fill missed seconds
    return b.iloc[1800:]          # drop first 30 min (settling / cold start)

SEGS = [load("data/phytosense_trial_log.csv", "2026-10-18 07:30"),
        load("data/trial_v7.csv"), load("data/preflight_90min.csv")]
W, GUARD = 1800, 60
THR = [3, 4, 5, 6, 8]; PERS = [1, 5, 10, 30, 60]; MAGS = [4, 6, 10]

def zscore(b):
    g = (b < 4090) & (b > 50) & (b.diff().abs() < 1200)
    bg = b.where(g)
    m = bg.shift(GUARD).rolling(W, min_periods=300).mean()
    s = bg.shift(GUARD).rolling(W, min_periods=300).std()
    return (bg - m) / (s + 1e-6), s

def alarms(z, thr, pers):
    hit = (z.abs() > thr).astype(float)
    a = hit.rolling(pers).min() == 1
    return a

def onsets(a): return (a & ~a.shift(1, fill_value=False))

# precompute: clean z per segment, and injected z per (segment, magnitude)
CLEAN = [zscore(b)[0] for b in SEGS]
INJ = {}
for m in MAGS:
    for i, b in enumerate(SEGS):
        sd = b.rolling(W, min_periods=300).std()
        bi = b.copy(); ev = [t for t in b.index[2400::2400] if not np.isnan(sd.get(t, np.nan))]
        for t0 in ev:
            bi[t0:t0 + pd.Timedelta("60s")] += m * sd[t0]
        INJ[(m, i)] = (zscore(bi)[0], ev)

rows = []
for thr in THR:
    for pers in PERS:
        n_on, hrs = 0, 0.0
        for z in CLEAN:
            a = alarms(z, thr, pers).loc[z.first_valid_index():]
            n_on += onsets(a).sum(); hrs += len(a) / 3600
        row = {"thr": thr, "pers_s": pers, "false_alarms_per_h": n_on / hrs}
        for m in MAGS:
            caught = tot = 0; lat = []
            for i in range(len(SEGS)):
                z, ev = INJ[(m, i)]; a = alarms(z, thr, pers)
                for t0 in ev:
                    w = a[t0:t0 + pd.Timedelta("300s")]; tot += 1
                    if w.any(): caught += 1; lat.append((w[w].index[0] - t0).total_seconds())
            row[f"catch_{m}sd"] = caught / max(tot, 1); row[f"lat_{m}sd"] = np.median(lat) if lat else np.nan
            row["n_events"] = tot
        rows.append(row)
df = pd.DataFrame(rows)
os.makedirs("out", exist_ok=True)
txt = df.round(2).to_string(index=False); open("out/alarm_tuning.txt", "w").write(txt); print(txt)
fig, ax = plt.subplots(figsize=(7, 5))
for pers, g in df.groupby("pers_s"):
    ax.plot(g["false_alarms_per_h"], g["catch_6sd"], "o-", label=f"persist {pers}s")
ax.set_xscale("symlog"); ax.set_xlabel("false alarms / hour (clean data)"); ax.set_ylabel("catch rate, +6 SD step (synthetic)")
ax.legend(); plt.tight_layout(); plt.savefig("out/alarm_tuning.png", dpi=130)