"""
Stream-level benchmark for PhytoSense++ detectors, leave-one-day-out.

Detectors: firmware baseline, winsorised update, freeze-on-deviation (fixed 900-sample
re-learn), CUSUM, Page-Hinkley, and the stability-based re-learn rule (accept a new level
only if it persists beyond T >= 600 s; release a deviation if the level returns within BAND SD).
Event kinds: step, sustained (transient, 3/4/6 SD), drift, spike, rail (transient by design),
permanent (shift from onset to end of recording). Amplitudes use a robust scale (MAD) and events
whose shifted samples would reach the ADC rails are dropped and counted.

Protocol
  1. Load each CSV and split into contiguous segments at gaps > GAP_S seconds.
  2. Keep segments with >= MIN_GOOD_H usable hours after SKIP_S.
  3. Gate with firmware thresholds (single-sample version).
  4. Clean stream: each detector runs causally on gated samples; alerts give
     the false-alarm rate per day.
  5. Injected stream: SYNTHETIC events (labelled) are added at fixed positions.
     A hit is an alert inside the event window (+GUARD_S). The background is the
     clean-stream alert in the same window, so excess = hit - background.
  6. Leave-one-day-out: for each day, CUSUM h and Page-Hinkley lambda are chosen
     on the other days (highest mean excess among settings with <= FA_BUDGET
     false alarms per hour; lowest-FA setting if none qualifies), then applied
     to the held-out day.
  7. Pooled results over held-out days; 95% CI by bootstrap over days.

Run from repo root:  python analysis/benchmark.py
Outputs go to out/. Injected events are SYNTHETIC.
"""
import os, math, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

FILES = ["data/preflight_90min.csv", "data/trial_v7.csv", "data/phytosense_trial_log.csv"]
GAP_S = 10
SKIP_S = 1800
MIN_GOOD_H = 1.0
EVENT_LEAD_S = 600
EVENT_SPACING_S = 2400
GUARD_S = 120
BOOT_B = 2000
FA_BUDGET = 1.0
RNG = np.random.default_rng(0)

# firmware-mirrored constants (main.cpp)
BASE_N, MIN_N = 1800, 200
Z_THR, PERSIST = 3.0, 10
RESET_S = 900
CU_K = 0.5
PH_DELTA = 0.5

CUSUM_H = (8, 16, 32, 64, 128, 256, 512)
PH_LAM = (10, 20, 40, 80, 160, 320, 640)
FIXED = ["baseline", "freeze", "winsor"]
ADAPTIVE = ["cusum", "ph", "stable"]

# Existing kinds are TRANSIENT: the shift starts at t and returns to baseline after dur seconds.
# "permanent" is PERMANENT: the shift starts once per segment and never returns within the recording.
EVENTS = [("step", 6, 60), ("sustained", 3, 600), ("sustained", 4, 600),
          ("sustained", 6, 600), ("drift", 6, 1800), ("spike", 10, 3), ("rail", 0, 60),
          ("permanent", 6, 0)]

CONFIGS = [dict(family=m, setting=m, method=m, params={}) for m in FIXED]
CONFIGS += [dict(family="cusum", setting=f"cusum(h={h})", method="cusum", params={"h": h}) for h in CUSUM_H]
CONFIGS += [dict(family="ph", setting=f"ph(lam={l})", method="ph", params={"lam": l}) for l in PH_LAM]
CONFIGS += [dict(family="stable", setting=f"stable(band={b},T={T})", method="stable",
                 params={"band": b, "T": T, "W": 60}) for b in (1.0, 2.0) for T in (600, 900, 1800)]   # T >= longest transient (600 s)


def load_segments(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t").reset_index(drop=True)
    bio = d["bioelectric_raw"].to_numpy(float)
    lo = (d["lo_plus"].fillna(0).astype(int) | d["lo_minus"].fillna(0).astype(int)).to_numpy(bool)
    gap = d["t"].diff().dt.total_seconds().fillna(0).to_numpy()
    seg = np.cumsum(gap > GAP_S)
    segs = []
    for s in np.unique(seg):
        idx = np.where(seg == s)[0]
        m = ~np.isnan(bio[idx])
        if m.sum() < SKIP_S + 600:
            continue
        day = d["t"].iloc[idx[0]].date().isoformat()
        segs.append(dict(bio=bio[idx][m], lo=lo[idx][m], day=day, src=os.path.basename(path)))
    return segs


def gate(x, lo):
    n = len(x)
    good = np.ones(n, bool)
    flat = np.zeros(60); fh = fc = 0; prev = None
    for i in range(n):
        v = x[i]
        flat[fh] = v; fh = (fh + 1) % 60; fc = min(fc + 1, 60)
        fstd = flat.std(ddof=1) if fc == 60 else 1e9
        if lo[i]:                                       r = "contact"
        elif v >= 4090:                                 r = "rail_hi"
        elif v <= 50:                                   r = "rail_lo"
        elif fstd < 2.0:                                r = "flat"
        elif prev is not None and abs(v - prev) > 1200: r = "jump"
        else:                                           r = "none"
        prev = v
        if r != "none":
            good[i] = False
    return good


def inject(x, sd, kind, mag, dur, n):
    if kind == "permanent":
        t = SKIP_S + EVENT_LEAD_S
        if t + GUARD_S + 600 >= n:          # need at least 10 min after onset to score
            return x.copy(), []
        y = x.copy(); y[t:] += mag * sd
        return y, [(t, n - t - GUARD_S)]
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



def detect_stable(x, good, p):
    """Stability-based re-learn rule.
    Entry: same as freeze (|z| > Z_THR for PERSIST consecutive gated samples).
    While in deviation the baseline is frozen and the mean of the last W samples
    (counted from onset) is compared with the baseline:
      - if it is back within BAND SD of the baseline -> TRANSIENT: resume normal.
      - if it is still outside BAND after more than T samples -> PERMANENT:
        accept the recent level as the new baseline (cold restart, as freeze does).
    Alerts are raised while in deviation and not yet resolved."""
    band = p["band"]; T = p["T"]; W = p.get("W", 60)
    n = len(x); alert = np.zeros(n, bool)
    R = Ring(BASE_N); run = 0
    dev = False; dev_len = 0
    recent = np.zeros(W); rh = 0; rc = 0
    for i in range(n):
        if not good[i]:
            run = 0
            continue
        v = x[i]
        if R.c < MIN_N:
            R.push(v); continue
        m, s = R.stats()
        z = (v - m) / (s + 1e-6)
        if not dev:
            run = run + 1 if abs(z) > Z_THR else 0
            if run >= PERSIST:
                dev = True; dev_len = 0; rh = 0; rc = 0
                alert[i] = True
            else:
                R.push(v)
            continue
        # in deviation: baseline frozen, track post-onset samples
        dev_len += 1
        recent[rh] = v; rh = (rh + 1) % W; rc = min(rc + 1, W)
        if rc < 10:
            alert[i] = True
            continue
        rm = recent[:rc].mean()
        rz = (rm - m) / (s + 1e-6)
        if abs(rz) < band:                       # transient: level returned
            dev = False; run = 0; R.push(v)
            continue
        if dev_len > T:                          # permanent: accept new level
            R.reset()
            for u in recent[:rc]:
                R.push(u)
            dev = False; run = 0
            continue
        alert[i] = True
    return alert

def detect(x, good, method, p=None):
    p = p or {}
    if method == "stable":
        return detect_stable(x, good, p)
    h = p.get("h", 0.0); lam = p.get("lam", 0.0)
    n = len(x); alert = np.zeros(n, bool)
    R = Ring(BASE_N); run = 0; frozen = 0
    Sp = Sn = 0.0; Pp = Pn = minPp = minPn = 0.0
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
            R.push(v if method == "baseline" else min(max(v, m - 3 * s), m + 3 * s))
            continue
        if method == "freeze":
            run = run + 1 if abs(z) > Z_THR else 0
            alert[i] = run >= PERSIST
            dev = run > 0
        elif method == "cusum":
            Sp = max(0.0, Sp + z - CU_K); Sn = max(0.0, Sn - z - CU_K)
            alert[i] = (Sp > h) or (Sn > h)
            dev = max(Sp, Sn) > h / 2
        else:  # page-hinkley
            Pp += z - PH_DELTA; minPp = min(minPp, Pp)
            Pn += -z - PH_DELTA; minPn = min(minPn, Pn)
            up, dn = Pp - minPp, Pn - minPn
            alert[i] = (up > lam) or (dn > lam)
            dev = max(up, dn) > lam / 2
        frozen = frozen + 1 if dev else 0
        if dev and frozen > RESET_S:          # re-learn after a long deviation
            R.reset(); R.push(v)
            run = 0; Sp = Sn = 0.0; Pp = Pn = minPp = minPn = 0.0; frozen = 0
            alert[i] = False
        elif not dev:
            R.push(v)
        # dev and not timed out: reference frozen
    return alert


def score_events(alert, clean_alert, events, good, kind, mag):
    out = []
    for (t, dur) in events:
        a = alert[t:t + dur + GUARD_S]
        hit = bool(a.any())
        bg = bool(clean_alert[t:t + dur + GUARD_S].any())
        out.append(dict(kind=kind, mag=mag, hit=hit, bg_hit=bg,
                        latency=float(np.argmax(a)) if hit else np.nan,
                        frac=float(alert[t:t + dur].mean())))
    return out


def onsets(alert):
    return int(np.sum(alert & ~np.r_[False, alert[:-1]]))


def main():
    os.makedirs("out", exist_ok=True)
    segs = []
    for f in FILES:
        segs += load_segments(f)
    usable = []
    for s in segs:
        g = gate(s["bio"], s["lo"])
        if g[SKIP_S:].sum() / 3600 >= MIN_GOOD_H:
            usable.append((s, g))
    days = sorted({f"{s['src']}|{s['day']}" for s, _ in usable})
    print(f"usable segments: {len(usable)}  days: {len(days)}")
    for d in days:
        print("  ", d)

    ev_rows, fa_rows = [], []
    dropped_rail = {}
    for s, good_clean in usable:
        x, lo = s["bio"], s["lo"]
        key = f"{s['src']}|{s['day']}"
        ref = x[:SKIP_S][good_clean[:SKIP_S]]
        if len(ref) > 200:
            sd = 1.4826 * np.median(np.abs(ref - np.median(ref)))   # robust scale (MAD)
        else:
            sd = 1.4826 * np.median(np.abs(x - np.median(x)))
        clean = {}
        for cfg in CONFIGS:
            a = detect(x, good_clean, cfg["method"], cfg["params"]); a[:SKIP_S] = False
            clean[cfg["setting"]] = a
            fa_rows.append(dict(key=key, family=cfg["family"], setting=cfg["setting"],
                                onsets=onsets(a), hours=good_clean[SKIP_S:].sum() / 3600))
        for kind, mag, dur in EVENTS:
            y, evs = inject(x, sd, kind, mag, dur, len(x))
            if kind != "rail":
                keep = [(t, d_) for (t, d_) in evs if y[t:t + d_].max() < 4090 and y[t:t + d_].min() > 50]
                dropped_rail[(kind, mag)] = dropped_rail.get((kind, mag), 0) + (len(evs) - len(keep))
                evs = keep
            if not evs:
                continue
            good = gate(y, lo)
            for cfg in CONFIGS:
                a = detect(y, good, cfg["method"], cfg["params"])
                for r in score_events(a, clean[cfg["setting"]], evs, good, kind, mag):
                    ev_rows.append(dict(key=key, family=cfg["family"], setting=cfg["setting"], **r))
        print(f"  {key}: done")

    print("events dropped because the shifted signal would hit the ADC rails:", dropped_rail)
    ev = pd.DataFrame(ev_rows); fa = pd.DataFrame(fa_rows)
    ev["excess"] = ev.hit.astype(float) - ev.bg_hit.astype(float)
    ev.to_csv("out/bench_events.csv", index=False)
    fa.to_csv("out/bench_fa.csv", index=False)

    # ---------- leave-one-day-out selection ----------
    fold_rows, sel_ev, sel_fa = [], [], []
    for held in days:
        train = set(days) - {held}
        choice = {f: f for f in FIXED}
        for fam in ADAPTIVE:
            names = [c["setting"] for c in CONFIGS if c["family"] == fam]
            tf = fa[(fa.family == fam) & fa.key.isin(train)].groupby("setting")[["onsets", "hours"]].sum()
            rate = (tf.onsets / tf.hours).reindex(names)
            te = ev[(ev.family == fam) & ev.key.isin(train) & ~ev.kind.isin(["rail", "permanent"])]
            mexc = te.groupby("setting").excess.mean().reindex(names)
            ok = [n for n in names if rate[n] <= FA_BUDGET]
            if ok:
                best = max(ok, key=lambda n: mexc[n] if not np.isnan(mexc[n]) else -9)
                fb = False
            else:
                best = min(names, key=lambda n: rate[n]); fb = True
            choice[fam] = best
            fold_rows.append(dict(held_out=held, family=fam, chosen=best,
                                  fallback_no_setting_meets_budget=fb,
                                  train_fa_per_h=round(float(rate[best]), 3)))
        for st in choice.values():
            sel_ev.append(ev[(ev.setting == st) & (ev.key == held)])
            sel_fa.append(fa[(fa.setting == st) & (fa.key == held)])

    sel_ev = pd.concat(sel_ev, ignore_index=True); sel_fa = pd.concat(sel_fa, ignore_index=True)
    folds = pd.DataFrame(fold_rows); folds.to_csv("out/bench_folds.csv", index=False)
    print("\nselection per held-out day:")
    print(folds.to_string(index=False))

    # ---------- pooled metrics with day-level bootstrap ----------
    def boot(groups, fn):
        point = fn(pd.concat(groups))
        boots = np.array([fn(pd.concat([groups[i] for i in RNG.integers(0, len(groups), len(groups))]))
                          for _ in range(BOOT_B)], float)
        return point, np.nanpercentile(boots, 2.5, axis=0), np.nanpercentile(boots, 97.5, axis=0)

    def ev_stats(g):
        lat = g.latency.dropna()
        return np.array([g.hit.astype(float).mean(), g.bg_hit.astype(float).mean(), g.excess.mean(),
                         np.median(lat) if len(lat) else np.nan, g.frac.mean()], float)

    def fa_stat(g):
        return np.array([g.onsets.sum() / g.hours.sum()], float)

    summ = []
    for fam in FIXED + ADAPTIVE:
        for kind, mag, _ in EVENTS:
            sub = sel_ev[(sel_ev.family == fam) & (sel_ev.kind == kind) & (sel_ev.mag == mag)]
            if sub.empty:
                continue
            groups = [g for g in (sub[sub.key == d] for d in days) if len(g)]
            pt, lo_, hi_ = boot(groups, ev_stats)
            summ.append(dict(family=fam, kind=kind, mag_sd=mag, n_events=len(sub), n_days=len(groups),
                             detect_rate=round(pt[0], 3), background_rate=round(pt[1], 3),
                             excess=round(pt[2], 3), excess_ci_lo=round(lo_[2], 3), excess_ci_hi=round(hi_[2], 3),
                             median_latency_s=pt[3], alerted_frac=round(pt[4], 3),
                             alerted_frac_ci_lo=round(lo_[4], 3), alerted_frac_ci_hi=round(hi_[4], 3),
                             fa_per_h=np.nan, fa_ci_lo=np.nan, fa_ci_hi=np.nan))
        sub = sel_fa[sel_fa.family == fam]
        groups = [g for g in (sub[sub.key == d] for d in days) if len(g)]
        pt, lo_, hi_ = boot(groups, fa_stat)
        summ.append(dict(family=fam, kind="clean", mag_sd=0, n_events=int(sub.onsets.sum()), n_days=len(groups),
                         fa_per_h=round(pt[0], 3), fa_ci_lo=round(lo_[0], 3), fa_ci_hi=round(hi_[0], 3)))
    summary = pd.DataFrame(summ)
    summary.to_csv("out/bench_summary.csv", index=False)

    # ---------- cost estimate (counted from the algorithms, not measured on the board) ----------
    cost = pd.DataFrame([
        dict(detector="firmware baseline", state_bytes=BASE_N * 4, ops_per_sample="~3N (sum and sum-of-squares recomputed each sample, as in main.cpp)"),
        dict(detector="freeze-on-deviation", state_bytes=BASE_N * 4 + 16 + 4, ops_per_sample="~15 (running sums, freeze counter)"),
        dict(detector="winsorised update", state_bytes=BASE_N * 4 + 16, ops_per_sample="~15 (running sums, two clips)"),
        dict(detector="CUSUM", state_bytes=BASE_N * 4 + 16 + 12, ops_per_sample="~15 (running sums, two accumulators)"),
        dict(detector="Page-Hinkley", state_bytes=BASE_N * 4 + 16 + 20, ops_per_sample="~15 (running sums, four accumulators)"),
        dict(detector="stability re-learn rule", state_bytes=BASE_N * 4 + 16 + 4 + 8 * 60 + 8, ops_per_sample="~15 (running sums, window of 60 samples: ~60 adds per sample while in deviation)"),
    ])
    cost.to_csv("out/bench_cost.csv", index=False)

    pd.set_option("display.width", 250)
    print("\n== leave-one-day-out summary ==")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()