"""PhytoSense++ replay engine: Python mirror of the firmware gate + bounded-memory baseline + persistence rule.
Constants match firmware/src/main.cpp."""
import numpy as np, pandas as pd

RAIL_HI_AVG, RAIL_LO_AVG = 4090.0, 50.0
FLAT_WINDOW, FLAT_STD_MAX, JUMP_MAX = 60, 2.0, 1200.0
BASELINE_N, MIN_BASELINE = 1800, 200

def load(path, start=None):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t")
    if start: d = d[d["t"] >= pd.Timestamp(start)]
    return d.reset_index(drop=True)

def inject(bio, i0, kind, n=120):
    """Return a copy of bio with a synthetic fault of n samples starting at index i0."""
    b = bio.copy(); i1 = min(len(b), i0 + n)
    if kind == "railed": b[i0:i1] = 4095.0
    elif kind == "flatline": b[i0:i1] = b[max(i0 - 1, 0)]
    elif kind == "spike": b[i0:i0 + 3] += 1500.0
    elif kind == "step +6 SD": b[i0:i1] += 6 * np.nanstd(b[max(0, i0 - 1800):i0]) if i0 > 300 else 60
    return b

def run(bio, lo_plus=None, lo_minus=None, z_thr=3.0, persist=10):
    """Causal replay. Returns DataFrame: reason, z, mean, sd, status, alert."""
    n = len(bio)
    reason = np.array(["none"] * n, dtype=object)
    z = np.full(n, np.nan); mean = np.full(n, np.nan); sd = np.full(n, np.nan)
    status = np.array([""] * n, dtype=object); alert = np.zeros(n, bool)
    flat = np.zeros(FLAT_WINDOW); fcount = fhead = 0
    ring = np.zeros(BASELINE_N); head = cnt = 0; s1 = s2 = 0.0
    prev = None; run_len = 0
    for i in range(n):
        x = float(bio[i])
        flat[fhead] = x; fhead = (fhead + 1) % FLAT_WINDOW; fcount = min(fcount + 1, FLAT_WINDOW)
        fstd = flat.std(ddof=1) if fcount == FLAT_WINDOW else 1e9
        contact = bool((lo_plus is not None and lo_plus[i]) or (lo_minus is not None and lo_minus[i]))
        if contact: r = "contact"
        elif x >= RAIL_HI_AVG: r = "rail_hi"
        elif x <= RAIL_LO_AVG: r = "rail_lo"
        elif fstd < FLAT_STD_MAX: r = "flat"
        elif prev is not None and abs(x - prev) > JUMP_MAX: r = "jump"
        else: r = "none"
        prev = x; reason[i] = r
        if r != "none":
            status[i] = "low_confidence"; run_len = 0; continue
        if cnt < MIN_BASELINE:
            status[i] = "cold_start"; run_len = 0
        else:
            m = s1 / cnt; v = max((s2 - cnt * m * m) / (cnt - 1), 0.0); s = np.sqrt(v)
            mean[i], sd[i] = m, s; z[i] = (x - m) / (s + 1e-6)
            run_len = run_len + 1 if abs(z[i]) > z_thr else 0
            alert[i] = run_len >= persist
            status[i] = "deviation" if alert[i] else "ok"
        if cnt == BASELINE_N:                       # ring full: drop oldest
            old = ring[head]; s1 -= old; s2 -= old * old
        else: cnt += 1
        ring[head] = x; head = (head + 1) % BASELINE_N; s1 += x; s2 += x * x
    return pd.DataFrame({"reason": reason, "z": z, "mean": mean, "sd": sd, "status": status, "alert": alert})
