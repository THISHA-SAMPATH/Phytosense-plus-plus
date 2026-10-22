"""Shared, explicitly documented helpers for the revised research analyses."""
from pathlib import Path
import numpy as np
import pandas as pd
from collections import deque

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "out" / "revised"
REPORTS = ROOT / "reports"
FILES = [DATA / "preflight_test.csv", DATA / "preflight_90min.csv", DATA / "trial_v7.csv", DATA / "phytosense_trial_log.csv"]

def prepare_dirs():
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

def load(path):
    d = pd.read_csv(path, low_memory=False)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed", errors="coerce")
    d = d.dropna(subset=["t"]).sort_values("t", kind="stable")
    # Duplicate timestamps are coalesced deterministically: median numeric sensor values,
    # max for leads-off and n_sat, and first categorical/status value.
    numeric = [c for c in d.select_dtypes(include="number").columns if c not in ("lo_plus", "lo_minus", "n_sat")]
    agg = {c: "median" for c in numeric}
    for c in ("lo_plus", "lo_minus", "n_sat"):
        if c in d: agg[c] = "max"
    for c in d.select_dtypes(include="object").columns:
        if c != "wall_clock_time": agg[c] = "first"
    d = d.groupby("t", as_index=False, sort=True).agg(agg)
    d["wall_clock_time"] = d["t"].astype(str)
    return d

def firmware_gate(d):
    x = d.bioelectric_raw.to_numpy(float)
    lo = (d.lo_plus.fillna(0).to_numpy(float) != 0) | (d.lo_minus.fillna(0).to_numpy(float) != 0)
    reasons = np.full(len(d), "none", object)
    flat = []
    prev = None
    for i, v in enumerate(x):
        flat.append(v)
        if len(flat) > 60: flat.pop(0)
        if lo[i]: r = "contact"
        elif v >= 4090 or ("n_sat" in d and float(d.n_sat.iloc[i]) >= 5): r = "rail_hi"
        elif v <= 50: r = "rail_lo"
        elif len(flat) == 60 and np.std(flat, ddof=1) < 2: r = "flat"
        elif prev is not None and abs(v-prev) > 1200: r = "jump"
        else: r = "none"
        reasons[i] = r
        prev = v
    return reasons

class MeanRing:
    def __init__(self, n=1800): self.n=n; self.q=deque(); self.s1=0.0; self.s2=0.0
    def push(self, x):
        x=float(x)
        if len(self.q)==self.n:
            old=self.q.popleft(); self.s1-=old; self.s2-=old*old
        self.q.append(x); self.s1+=x; self.s2+=x*x
    def stats(self):
        n=len(self.q); m=self.s1/n
        return float(m), float(np.sqrt(max((self.s2-self.s1*m)/(n-1),0))) if n>1 else 0.0
