"""
Environment-compensated baseline (offline evaluation).

Idea: the bioelectric signal drifts with temperature, humidity and pressure
(logged on-device by DHT11 and BMP280). Before the baseline and detector see
the signal, a linear model of the environment is subtracted:

    residual = bio - (beta0 + (env - mu) . beta)

The model is fitted on the TRAINING days only (leave-one-day-out), using gated
samples with valid environment readings. The gate still runs on the raw signal.
Compensation uses only the same-sample environment, so it is causal.

Compared (fixed settings, no threshold tuning):
    raw baseline, compensated baseline, raw freeze, compensated freeze.

Run from repo root:  python analysis/env_compensated.py
Requires analysis/benchmark.py in the same folder.
Events are SYNTHETIC.
"""
import os, sys, warnings
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchmark as B
warnings.filterwarnings("ignore")

COVS = ["temp_c", "humidity_pct", "pressure_hpa"]
BOOT_B = 2000
RNG = np.random.default_rng(0)
EVENTS = [("step", 6, 60), ("sustained", 4, 600), ("sustained", 6, 600)]
METHODS = [("raw", "baseline"), ("comp", "baseline"), ("raw", "freeze"), ("comp", "freeze")]


def load_env_segments(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t").reset_index(drop=True)
    bio = d["bioelectric_raw"].to_numpy(float)
    lo = (d["lo_plus"].fillna(0).astype(int) | d["lo_minus"].fillna(0).astype(int)).to_numpy(bool)
    X = np.column_stack([pd.to_numeric(d[c], errors="coerce").to_numpy(float) for c in COVS])
    # same plausibility limits as the firmware (main.cpp)
    X[:, 0] = np.where((X[:, 0] < -10) | (X[:, 0] > 60), np.nan, X[:, 0])
    X[:, 1] = np.where((X[:, 1] < 0) | (X[:, 1] > 100), np.nan, X[:, 1])
    X[:, 2] = np.where((X[:, 2] < 850) | (X[:, 2] > 1100), np.nan, X[:, 2])
    gap = d["t"].diff().dt.total_seconds().fillna(0).to_numpy()
    seg = np.cumsum(gap > B.GAP_S)
    segs = []
    for s in np.unique(seg):
        idx = np.where(seg == s)[0]
        m = ~np.isnan(bio[idx])
        if m.sum() < B.SKIP_S + 600:
            continue
        segs.append(dict(bio=bio[idx][m], lo=lo[idx][m], X=X[idx][m],
                         day=d["t"].iloc[idx[0]].date().isoformat(), src=os.path.basename(path)))
    return segs


def fit_env(train):
    Xs, ys = [], []
    for s in train:
        ok = B.gate(s["bio"], s["lo"]) & ~np.isnan(s["X"]).any(1)
        Xs.append(s["X"][ok]); ys.append(s["bio"][ok])
    X = np.vstack(Xs); y = np.concatenate(ys)
    mu = X.mean(0)
    A = np.column_stack([np.ones(len(X)), X - mu])
    beta = np.linalg.lstsq(A, y, rcond=None)[0]
    return mu, beta, len(y)


def residual(s, mu, beta):
    X = np.where(np.isnan(s["X"]), mu, s["X"])
    pred = np.column_stack([np.ones(len(X)), X - mu]) @ beta
    return s["bio"] - (pred - beta[0])


def onsets(a):
    return B.onsets(a)


def main():
    os.makedirs("out", exist_ok=True)
    segs = []
    for f in B.FILES:
        segs += load_env_segments(f)
    usable = [s for s in segs if B.gate(s["bio"], s["lo"])[B.SKIP_S:].sum() / 3600 >= B.MIN_GOOD_H]
    nan_frac = np.mean([np.isnan(s["X"]).any(1).mean() for s in usable])
    days = sorted({f"{s['src']}|{s['day']}" for s in usable})
    print(f"usable segments: {len(usable)}  days: {len(days)}  fraction of samples missing env: {nan_frac:.3f}")

    rows = []
    fits = []
    for held in days:
        train = [s for s in usable if f"{s['src']}|{s['day']}" not in (held,)]
        test = [s for s in usable if f"{s['src']}|{s['day']}" == held]
        mu, beta, n_fit = fit_env(train)
        fits.append(dict(held_out=held, n_fit_samples=n_fit,
                         **{f"beta_{c}": round(b, 4) for c, b in zip(COVS, beta[1:])}))
        for s in test:
            raw = s["bio"]; lo = s["lo"]
            good = B.gate(raw, lo)
            sd = np.std(raw[:B.SKIP_S][good[:B.SKIP_S]]) if good[:B.SKIP_S].sum() > 200 else np.std(raw)
            res = residual(s, mu, beta)
            signals = {"raw": raw, "comp": res}
            clean = {}
            for src, meth in METHODS:
                x = signals[src]
                a = B.detect(x, good, meth); a[:B.SKIP_S] = False
                clean[(src, meth)] = a
                rows.append(dict(day=held, source=src, method=meth, kind="clean", mag=0,
                                 n_events=0, hit=np.nan, frac=np.nan, onsets=onsets(a),
                                 hours=good[B.SKIP_S:].sum() / 3600))
            for kind, mag, dur in EVENTS:
                # inject on the same residual scale, with the same absolute size (sd from raw)
                _, evs = B.inject(res, sd, kind, mag, dur, len(raw))
                if not evs:
                    continue
                y_res, _ = B.inject(res, sd, kind, mag, dur, len(raw))
                delta = y_res - res
                y_raw = raw + delta
                good_inj = B.gate(y_raw, lo)
                for src, meth in METHODS:
                    x = y_raw if src == "raw" else y_res
                    a = B.detect(x, good_inj, meth)
                    ca = clean[(src, meth)]
                    for (t, d_) in evs:
                        w = a[t:t + d_ + B.GUARD_S]
                        rows.append(dict(day=held, source=src, method=meth, kind=kind, mag=mag,
                                         n_events=1, hit=bool(w.any()),
                                         frac=float(a[t:t + d_].mean()),
                                         onsets=0, hours=0.0, bg=bool(ca[t:t + d_ + B.GUARD_S].any())))
        print(f"  held out {held}: env fit on {n_fit} samples")

    R = pd.DataFrame(rows)
    R.to_csv("out/env_rows.csv", index=False)
    pd.DataFrame(fits).to_csv("out/env_fits.csv", index=False)

    def boot(groups, fn):
        point = fn(pd.concat(groups))
        bs = np.array([fn(pd.concat([groups[i] for i in RNG.integers(0, len(groups), len(groups))]))
                       for _ in range(BOOT_B)], float)
        return point, np.nanpercentile(bs, 2.5, axis=0), np.nanpercentile(bs, 97.5, axis=0)

    def ev_fn(g):
        return np.array([g.hit.astype(float).mean(), g.frac.mean(), g.bg.astype(float).mean()], float)

    def fa_fn(g):
        return np.array([g.onsets.sum() / g.hours.sum()], float)

    out = []
    for src, meth in METHODS:
        name = f"{src} {meth}"
        sub = R[(R.source == src) & (R.method == meth)]
        for kind, mag, _ in EVENTS:
            e = sub[(sub.kind == kind) & (sub.mag == mag)]
            groups = [g for g in (e[e.day == d] for d in days) if len(g)]
            pt, lo_, hi_ = boot(groups, ev_fn)
            out.append(dict(setting=name, kind=kind, mag_sd=mag, detect_rate=round(pt[0], 3),
                            alerted_frac=round(pt[1], 3), alerted_frac_ci_lo=round(lo_[1], 3),
                            alerted_frac_ci_hi=round(hi_[1], 3)))
        c = sub[sub.kind == "clean"]
        groups = [g for g in (c[c.day == d] for d in days) if len(g)]
        pt, lo_, hi_ = boot(groups, fa_fn)
        out.append(dict(setting=name, kind="clean", mag_sd=0, fa_per_h=round(pt[0], 3),
                        fa_ci_lo=round(lo_[0], 3), fa_ci_hi=round(hi_[0], 3)))
    summ = pd.DataFrame(out)
    summ.to_csv("out/env_summary.csv", index=False)
    pd.set_option("display.width", 220)
    print("\nLOO fits:"); print(pd.DataFrame(fits).to_string(index=False))
    print("\nSummary:"); print(summ.to_string(index=False))


if __name__ == "__main__":
    main()