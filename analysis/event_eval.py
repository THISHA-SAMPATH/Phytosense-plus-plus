r"""Event-level check around the two leaf-cut events. Run from repo root:
    python analysis\event_eval.py
Outputs: out/event_<name>.png and out/event_eval.txt
Method: causal 30-min baseline (mean/SD of past samples, excluding the last 60 s), z-score each second,
alarm = |z|>3 for >=10 consecutive seconds. Rails/flat/jumps are dropped first (same thresholds as firmware)."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt, os

EVENTS = {   # name: (event_start, event_end, plot_from, plot_to)
 "sep12_leafcut": ("2026-09-12 21:30:00", "2026-09-12 21:30:00", "2026-09-12 20:30", "2026-09-12 22:30"),
 "oct18_leafcut": ("2026-10-18 07:20:00", "2026-10-18 07:30:00", "2026-10-18 07:25", "2026-10-18 09:30"),
}
d = pd.read_csv("data/phytosense_trial_log.csv")
d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
d = d.sort_values("t").set_index("t")
b = d["bioelectric_raw"].resample("1s").mean()
good = (b < 4090) & (b > 50) & (b.diff().abs() < 1200)
bg = b.where(good)
W = 1800
mean = bg.shift(60).rolling(W, min_periods=200).mean()
sd = bg.shift(60).rolling(W, min_periods=200).std()
z = (bg - mean) / (sd + 1e-6)
hit = (z.abs() > 3).astype(float)
alarm = hit.rolling(10).min() == 1

out = []
os.makedirs("out", exist_ok=True)
for name, (s, e, p0, p1) in EVENTS.items():
    s, e = pd.Timestamp(s), pd.Timestamp(e)
    seg = bg[p0:p1]
    pre = alarm[s - pd.Timedelta("60min"):s]
    post = alarm[e:e + pd.Timedelta("30min")]
    first = post[post].index.min() if post.any() else None
    out.append(f"== {name} (event {s.time()}-{e.time()}) ==")
    out.append(f"data in plot window: {seg.notna().sum()} s, first sample {seg.first_valid_index()}")
    if seg.first_valid_index() is not None and seg.first_valid_index() > s:
        out.append("NO PRE-EVENT DATA: logging started after the event. Detection latency cannot be computed.")
    out.append(f"alarm-seconds in the 60 min before event: {int(pre.sum())}")
    out.append(f"alarm-seconds in the 30 min after event: {int(post.sum())}")
    out.append("first alarm after event: " + (f"{first} (+{(first-e).total_seconds():.0f}s)" if first is not None else "none within 30 min"))
    fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    ax[0].plot(seg.index, seg.values, lw=.4, alpha=.5, label="raw 1 s")
    ax[0].plot(seg.index, seg.rolling(30, min_periods=5).median(), lw=1.2, label="30 s median")
    ax[0].axvspan(s, e if e > s else s + pd.Timedelta("20s"), color="red", alpha=.25, label="leaf cut")
    ax[0].set_ylabel("ADC counts"); ax[0].legend(); ax[0].set_title(name)
    ax[1].plot(z[p0:p1].index, z[p0:p1].clip(-10, 10), lw=.5); ax[1].axhline(3, c="r", ls="--"); ax[1].axhline(-3, c="r", ls="--")
    ax[1].set_ylabel("z (clipped)")
    plt.tight_layout(); plt.savefig(f"out/event_{name}.png", dpi=130); plt.close()
txt = "\n".join(out); open("out/event_eval.txt", "w").write(txt); print(txt)