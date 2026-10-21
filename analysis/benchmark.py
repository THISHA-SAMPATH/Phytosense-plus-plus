"""
Stream-level benchmark for PhytoSense++ detectors.

Protocol (fixed, no tuning on test data):
  1. Split each log into contiguous segments (time gap > GAP_S starts a new one).
  2. Inject fixed synthetic events into the raw stream (step, sustained, drift, spike, rail).
  3. Gate: contact / rail / flat / jump checks (mirrors firmware thresholds).
  4. Reference update + detector, causal, gated samples only.
  5. Score per event (detected? latency? fraction of the event alerted?) and
     false alarms per hour on the un-injected stream.
  6. Bootstrap over RECORDING DAYS (not samples) for 95% confidence intervals.

Run from repo root:  python analysis/benchmark.py
Outputs (out/): bench_events.csv, bench_summary.csv, bench_cost.csv
Injected events are SYNTHETIC and are labelled as such everywhere.
"""
import os, math
import numpy as np
import pandas as pd

FILES = ["data/preflight_90min.csv", "data/trial_v7.csv", "data/phytosense_trial_log.csv"]
GAP_S = 10            # new segment if the gap between rows exceeds this (seconds)
SKIP_S = 1800         # ignore the first 30 min of each segment (cold start)
MIN_GOOD_H = 1.0      # a segment must offer at least this many usable hours
EVENT_LEAD_S = 600    # first event starts this long after SKIP_S
EVENT_SPACING_S = 2400
GUARD_S = 120         # an alert counts for an event if it falls within event + GUARD_S
BOOT_B = 2000
RNG = np.random.default_rng(0)

# --- firmware-mirrored constants (main.cpp) ---
BASE_N, MIN_N = 1800, 200
Z_THR, PERSIST = 3.0, 10
RESET_S = 900         # frozen detectors re-learn after this many consecutive deviating samples
CU_K, CU_H = 0.5, 8.0           # CUSUM reference value and decision threshold (in SD units)
PH_DELTA, PH_LAMBDA = 0.5, 10.0 # Page-Hinkley tolerance and threshold (in SD units)

EVENTS = [("step", 6, 60), ("sustained", 3, 600), ("sustained", 4, 600),
          ("sustained", 6, 600), ("drift", 6, 1800), ("spike", 10, 3), ("rail", 0, 60)]
DETECTORS = ["baseline", "freeze", "winsor", "cusum", "ph"]
DET_LABEL = {"baseline": "firmware baseline", "freeze": "freeze-on-deviation",
             "winsor": "winsorised update", "cusum": "CUSUM (on z)", "ph": "Page-Hinkley (on z)"}


# ---------------- loading and segmenting ----------------
def load_segments(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t").reset_index(drop=True)
    bio = d["bioelectric_raw"].to_numpy(float)
    lo = ((d["lo_plus"].fillna(0).astype(int) | d["lo_minus"].fillna(0).astype(int)).to_numpy(bool)
          if "lo_plus" in d.columns else np.zeros(len(d), bool))
    gap = d["t"].diff().dt.total_seconds().fillna(0).to_numpy()
    seg = np.cumsum(gap > GAP_S)
    segs = []
    for s in np.unique(seg):
        m = (seg == s) & ~np.isnan(bio)
        if m.sum() < SKIP_S + 600:
            continue
        day = d["t"].iloc[np.where(seg == s)[0][0]].date().isoformat()
        segs.append(dict(bio=bio[m], lo=lo[m], day=day, src=os.path.basename(path)))
    return segs


# ---------------- gate (firmware thresholds, single-sample version) ----------------
def gate(x, lo):
    n = len(x)
    good = np.ones(n, bool)
    flat = np.zeros(60); fh = fc = 0; prev = None
    for i in range(n):
        v = x[i]
        flat[fh] = v; fh = (fh + 1) % 60; fc = min(fc + 1, 60)
        fstd = flat.std(ddof=1) if fc == 60 else 1e9
        if lo[i]:                                   r = "contact"
        elif v >= 4090:                             r = "rail_hi"
        elif v <= 50:                               r = "rail_lo"
        elif fstd < 2.0:                            r = "flat"
        elif prev is not None and abs(v - prev) > 1200: r = "jump"
        else:                                       r = "none"
        prev = v
        if r != "none":
            good[i] = False
    return good


# ---------------- injection (synthetic, labelled) ----------------
def inject(x, sd, kind, mag, dur, n):
    y = x.copy(); events = []
    t = SKIP_S + EVENT_LEAD_S
    while t + dur + GUARD_S < n:
        if kind in ("step", "sustained", "spike"):
            y[t:t + dur] += mag * sd
        elif kind == "drift":
            y[t:t + dur] += mag * sd * np.linspace(0, 1, dur)
        elif kind == "rail":
            y[t:t + dur] = 4095.0
        events.append((t, dur))
        t += EVENT_SPACING_S
    return y, events


# ---------------- reference (bounded-memory ring, running sums) ----------------
class Ring:
    def __init__(self, N):
        self.N = N; self.buf = np.zeros(N); self.reset()
    def reset(self):
        self.h = 0; self.c = 0; self.s1 = 0.0; self.s2 = 0.0
    def stats(self):
        m = self.s1 / self.c
        v = max((self.s2 - self.c * m * m) / (self.c - 1), 0.0)
        return m, math.sqrt(v)
    def push(self, x):
        if self.c == self.N:
            old = self.buf[self.h]; self.s1 -= old; self.s2 -= old * old
        else:
            self.c += 1
        self.buf[self.h] = x; self.h = (self.h + 1) % self.N
        self.s1 += x; self.s2 += x * x


# ---------------- detectors (causal, gated samples only) ----------------
def detect(x, good, method, p=None):
    p = p or {}
    CU_H_ = p.get("h", CU_H); PH_L_ = p.get("lam", PH_LAMBDA)
    n = len(x); alert = np.zeros(n, bool)
    R = Ring(BASE_N)
    run = 0; frozen = 0
    Sp = Sn = 0.0
    Pp = Pn = minPp = minPn = 0.0
    for i in range(n):
        if not good[i]:
            run = 0; Sp = Sn = 0.0; Pp = Pn = minPp = minPn = 0.0
            continue
        v = x[i]
        if R.c < MIN_N:
            R.push(v); continue
        m, s = R.stats()
        z = (v - m) / (s + 1e-6)

        if method in ("baseline", "winsor"):
            run = run + 1 if abs(z) > Z_THR else 0
            alert[i] = run >= PERSIST
            if method == "baseline":
                R.push(v)
            else:
                R.push(min(max(v, m - 3 * s), m + 3 * s))
            continue

        if method == "freeze":
            run = run + 1 if abs(z) > Z_THR else 0
            alert[i] = run >= PERSIST
            dev = run > 0
        elif method == "cusum":
            Sp = max(0.0, Sp + z - CU_K); Sn = max(0.0, Sn - z - CU_K)
            alert[i] = (Sp > CU_H_) or (Sn > CU_H_)
            dev = max(Sp, Sn) > CU_H_ / 2
        elif method == "ph":
            Pp += z - PH_DELTA; minPp = min(minPp, Pp)
            Pn += -z - PH_DELTA; minPn = min(minPn, Pn)
            up, dn = Pp - minPp, Pn - minPn
            alert[i] = (up > PH_L_) or (dn > PH_L_)
            dev = max(up, dn) > PH_L_ / 2

        frozen = frozen + 1 if dev else 0
        if dev and frozen > RESET_S:            # re-learn: accept the new level as normal
            R.reset(); R.push(v)
            run = 0; Sp = Sn = 0.0; Pp = Pn = minPp = minPn = 0.0; frozen = 0
            alert[i] = False
        elif not dev:
            R.push(v)
        # dev and not timed out: reference frozen, do not push
    return alert


# ---------------- scoring ----------------
def score_events(alert, clean_alert, events, good, kind, mag):
    out = []
    for (t, dur) in events:
        a = alert[t:t + dur + GUARD_S]
        hit = bool(a.any())
        bg = bool(clean_alert[t:t + dur + GUARD_S].any())   # same window, no injected event
        out.append(dict(kind=kind, mag=mag, hit=hit, bg_hit=bg,
                        latency=float(np.argmax(a)) if hit else np.nan,
                        frac=float(alert[t:t + dur].mean()),
                        gate_pass=float(good[t:t + dur].mean())))
    return out


def onsets(alert):
    return int(np.sum(alert & ~np.r_[False, alert[:-1]]))


def param_grid():
    return {"baseline": [{}], "freeze": [{}], "winsor": [{}],
            "cusum": [{"h": h} for h in (8, 16, 32, 64)],
            "ph": [{"lam": l} for l in (10, 20, 40, 80)]}


def pname(method, p):
    return method if not p else f"{method}({','.join(f'{k}={v}' for k, v in p.items())})"


def main():
    os.makedirs("out", exist_ok=True)
    segs = []
    for f in FILES:
        segs += load_segments(f)
    segs = [s for s in segs if gate(s["bio"][:SKIP_S + 600], s["lo"][:SKIP_S + 600]).sum() > 0]

    # usable segments and a fixed day split: alternate days (sorted) into TUNE and TEST
    usable = []
    for si, s in enumerate(segs):
        g = gate(s["bio"], s["lo"])
        if g[SKIP_S:].sum() / 3600 >= MIN_GOOD_H:
            usable.append((si, s, g))
    days = sorted({(s["src"], s["day"]) for _, s, _ in usable})
    tune_days = set(days[0::2]); test_days = set(days[1::2])
    print(f"usable segments: {len(usable)}  days: {len(days)}  tune: {len(tune_days)}  test: {len(test_days)}")
    print("tune days:", sorted(tune_days)); print("test days:", sorted(test_days))

    ev_rows, fa_rows = [], []
    grid = param_grid()
    for si, s, good_clean in usable:
        x, lo = s["bio"], s["lo"]
        d = (s["src"], s["day"]); split = "tune" if d in tune_days else "test"
        sd = np.std(x[:SKIP_S][good_clean[:SKIP_S]]) if good_clean[:SKIP_S].sum() > 200 else np.std(x)
        clean_alerts = {}
        for method, plist in grid.items():
            for p in plist:
                a = detect(x, good_clean, method, p); a[:SKIP_S] = False
                clean_alerts[(method, tuple(p.items()))] = a
                fa_rows.append(dict(split=split, src=d[0], day=d[1], detector=pname(method, p),
                                    onsets=onsets(a), hours=good_clean[SKIP_S:].sum() / 3600))
        for kind, mag, dur in EVENTS:
            y, ev = inject(x, sd, kind, mag, dur, len(x))
            if not ev: continue
            good = gate(y, lo)
            for method, plist in grid.items():
                for p in plist:
                    a = detect(y, good, method, p)
                    ca = clean_alerts[(method, tuple(p.items()))]
                    for r in score_events(a, ca, ev, good, kind, mag):
                        ev_rows.append(dict(split=split, src=d[0], day=d[1], detector=pname(method, p), **r))
        print(f"  {d[0]} {d[1]} ({split}) done")

    ev = pd.DataFrame(ev_rows); fa = pd.DataFrame(fa_rows)
    ev.to_csv("out/bench_events.csv", index=False)
    fa.to_csv("out/bench_fa.csv", index=False)

    # ---------- choose CUSUM / PH thresholds on TUNE days only ----------
    # objective: mean excess detection over step, sustained 4/6, drift 6, spike 10 (not rail),
    # among settings whose clean false-alarm rate on TUNE days is <= 1 per hour.
    chosen = {}
    tune_ev = ev[(ev.split == "tune") & (ev.kind != "rail")].copy()
    tune_ev["excess"] = tune_ev.hit.astype(float) - tune_ev.bg_hit.astype(float)
    tune_fa = fa[fa.split == "tune"].groupby("detector").agg(o=("onsets", "sum"), h=("hours", "sum"))
    tune_fa["rate"] = tune_fa.o / tune_fa.h
    for method in ("cusum", "ph"):
        cands = [pname(method, p) for p in grid[method]]
        ok = [c for c in cands if c in tune_fa.index and tune_fa.loc[c, "rate"] <= 1.0]
        if not ok:
            print(f"WARNING: no {method} setting meets the 1 FA/h budget on TUNE days; "
                  f"falling back to the lowest-FA setting")
            best = min(cands, key=lambda c: tune_fa.loc[c, "rate"] if c in tune_fa.index else 1e9)
        else:
            best = max(ok, key=lambda c: tune_ev[tune_ev.detector == c].excess.mean()
                       if (tune_ev.detector == c).any() else -9)
        chosen[method] = best
    for m in ("baseline", "freeze", "winsor"):
        chosen[m] = m
    print("\nchosen on TUNE days:", chosen)

    # ---------- test-day summary with bootstrap over days ----------
    te_ev = ev[(ev.split == "test") & ev.detector.isin(chosen.values())].copy()
    te_ev["excess"] = te_ev.hit.astype(float) - te_ev.bg_hit.astype(float)
    te_fa = fa[(fa.split == "test") & fa.detector.isin(chosen.values())]
    test_day_list = sorted({(r.src, r.day) for r in te_ev.itertuples()} | {(r.src, r.day) for r in te_fa.itertuples()})

    def boot_rows(det, kind, mag, sub):
        per = [sub[(sub.src == a) & (sub.day == b)] for a, b in test_day_list]
        per = [g for g in per if len(g)]
        def pooled(idx):
            g = pd.concat([per[i] for i in idx])
            lat = g.latency.dropna()
            return (g.hit.mean(), g.bg_hit.mean(), g.excess.mean(),
                    lat.median() if len(lat) else np.nan, g.frac.mean())
        base = np.array(pooled(range(len(per))), float)
        boots = np.array([pooled(RNG.integers(0, len(per), len(per))) for _ in range(BOOT_B)], float)
        lo, hi = np.nanpercentile(boots, 2.5, axis=0), np.nanpercentile(boots, 97.5, axis=0)
        return dict(detector=det, kind=kind, mag_sd=mag, n_events=len(sub), n_days=len(per),
                    detect_rate=base[0], detect_ci=f"[{lo[0]:.2f}, {hi[0]:.2f}]",
                    background_rate=base[1], excess=base[2], excess_ci=f"[{lo[2]:.2f}, {hi[2]:.2f}]",
                    median_latency_s=base[3], alerted_frac=base[4])

    summ = []
    for det in chosen.values():
        for kind, mag, _ in EVENTS:
            if kind == "rail":
                pass
            sub = te_ev[(te_ev.detector == det) & (te_ev.kind == kind) & (te_ev.mag == mag)]
            if len(sub): summ.append(boot_rows(det, kind, mag, sub))
        sub = te_fa[te_fa.detector == det]
        per = [sub[(sub.src == a) & (sub.day == b)] for a, b in test_day_list]
        per = [g for g in per if len(g)]
        def fa_rate(idx):
            g = pd.concat([per[i] for i in idx]); return g.onsets.sum() / g.hours.sum()
        base = fa_rate(range(len(per)))
        boots = [fa_rate(RNG.integers(0, len(per), len(per))) for _ in range(BOOT_B)]
        summ.append(dict(detector=det, kind="clean", mag_sd=0, n_events=int(sub.onsets.sum()),
                         n_days=len(per), fa_per_h=round(base, 3),
                         fa_ci=f"[{np.percentile(boots,2.5):.2f}, {np.percentile(boots,97.5):.2f}]"))
    summary = pd.DataFrame(summ)
    summary.to_csv("out/bench_summary.csv", index=False)

    # ---------- cost (counted from the algorithms, no hardware needed) ----------
    cost = pd.DataFrame([
        dict(detector="firmware baseline", state_bytes=BASE_N * 4, ops_per_sample="~3N = 5400 (sum and sum-of-squares recomputed each sample, as in main.cpp)"),
        dict(detector="freeze-on-deviation", state_bytes=BASE_N * 4 + 16 + 4, ops_per_sample="~15 (running sums, freeze counter)"),
        dict(detector="winsorised update", state_bytes=BASE_N * 4 + 16, ops_per_sample="~15 (running sums, two clips)"),
        dict(detector="CUSUM", state_bytes=BASE_N * 4 + 16 + 12, ops_per_sample="~15 (running sums, two accumulators)"),
        dict(detector="Page-Hinkley", state_bytes=BASE_N * 4 + 16 + 20, ops_per_sample="~15 (running sums, four accumulators)"),
    ])
    cost.to_csv("out/bench_cost.csv", index=False)

    print("\n== test-day summary (excess = detect rate - background rate in same windows) ==")
    print(summary.to_string(index=False))
    print("\n== all parameter settings, tune+test (clean FA per hour) ==")
    print(fa.groupby(["split", "detector"]).apply(lambda g: round(g.onsets.sum() / g.hours.sum(), 2)).unstack(0).to_string())


if __name__ == "__main__":
    main()
