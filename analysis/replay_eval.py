"""
PhytoSense++ - Software-only replay evaluation (no new hardware needed)
-----------------------------------------------------------------------
Usage: python replay_eval.py <log.csv> [out_dir] [clean_after_date]
  e.g.  python replay_eval.py data/full_log.csv out 2026-10-17
  clean_after_date (optional) = ignore everything before it when picking the clean
  stretch (use it to skip the old Sept data).

Replays the firmware's gate + bounded-memory baseline in Python over EXISTING logs and
compares GATED vs UNGATED learning. Three experiments:

 A. Real fault replay : Oct 12-14 log (genuinely railed front end) spliced in front of
                        the clean stretch. Skipped automatically if the file has no
                        Oct 12-14 rows.
 B. Clean baseline    : deviation rate on the longest clean, non-railed stretch.
 C. Injected faults   : synthetic contact faults (rail episodes, spikes, offset steps)
                        added to the clean data; measures gate catch rate and the
                        alarms each baseline raises afterwards. SIMULATED - say so.
                        Skipped if the clean stretch is shorter than about 1.4 h.

Limits to state in the paper: unless your log contains stimulus events, nothing here
shows stress-detection lead time. This evaluates the GATING mechanism only.
Splicing (A) and injection (C) are semi-synthetic.
"""
import sys, os
from collections import deque
import numpy as np
import pandas as pd

# firmware constants (main.cpp v7)
RAIL_HI, RAIL_LO, FLAT_WIN, FLAT_STD, JUMP = 4090.0, 50.0, 60, 2.0, 1200.0
N, MIN_N, Z, RESET_BAD = 1800, 200, 3.0, 600


class Ring:
    def __init__(self):
        self.q = deque(); self.s = 0.0; self.ss = 0.0
    def push(self, v):
        self.q.append(v); self.s += v; self.ss += v * v
        if len(self.q) > N:
            o = self.q.popleft(); self.s -= o; self.ss -= o * o
    def z(self, v):
        n = len(self.q)
        m = self.s / n
        var = max((self.ss - n * m * m) / (n - 1), 0.0)
        return (v - m) / (var ** 0.5 + 1e-6)
    def reset(self):
        self.q.clear(); self.s = 0.0; self.ss = 0.0


def gate(x, prev, flat_q):
    flat_q.append(x)
    if len(flat_q) > FLAT_WIN: flat_q.popleft()
    if x >= RAIL_HI: return "rail_hi"
    if x <= RAIL_LO: return "rail_lo"
    if len(flat_q) == FLAT_WIN and np.std(flat_q, ddof=1) < FLAT_STD: return "flat"
    if prev is not None and abs(x - prev) > JUMP: return "jump"
    return "none"


def run(sig):
    """returns per-sample arrays for gated and ungated baselines"""
    g, u = Ring(), Ring()
    fq = deque(); prev = None; bad = 0
    reasons, dev_g, dev_u, scored_g, scored_u = [], [], [], [], []
    for x in sig:
        r = gate(x, prev, fq); prev = x
        good = r == "none"
        reasons.append(r)
        # gated
        if good: bad = 0
        else: bad += 1
        if bad == RESET_BAD: g.reset()
        if good:
            if len(g.q) >= MIN_N:
                dev_g.append(abs(g.z(x)) > Z); scored_g.append(True)
            else:
                dev_g.append(False); scored_g.append(False)
            g.push(x)
        else:
            dev_g.append(False); scored_g.append(False)
        # ungated: learns and scores everything
        if len(u.q) >= MIN_N:
            dev_u.append(abs(u.z(x)) > Z); scored_u.append(True)
        else:
            dev_u.append(False); scored_u.append(False)
        u.push(x)
    return (np.array(reasons), np.array(dev_g), np.array(dev_u),
            np.array(scored_g), np.array(scored_u))


def events(dev, min_len=10):
    """count alarm EVENTS: runs of >= min_len consecutive deviation samples"""
    n = run_len = 0
    for d in dev:
        run_len = run_len + 1 if d else 0
        if run_len == min_len: n += 1
    return n


def rate(dev, scored):
    h = scored.sum() / 3600
    return (dev[scored].sum() / h) if h > 0 else float("nan")


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    after = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(out, exist_ok=True)
    df = pd.read_csv(path, low_memory=False)
    df["t"] = pd.to_datetime(df["wall_clock_time"], format="mixed")
    df = df.sort_values("t").reset_index(drop=True)
    b = df["bioelectric_raw"].to_numpy(float)

    # CLEAN stretch = longest continuous run of non-railed rows (no gap > 2 min)
    ok = (b < RAIL_HI) & (b > RAIL_LO)
    if after is not None:
        ok = ok & (df["t"] >= after).to_numpy()
    gap = df["t"].diff().dt.total_seconds().fillna(0).to_numpy() > 120
    seg = np.cumsum(gap | (ok != np.roll(ok, 1)))
    best = (0, None)
    for sid in np.unique(seg[ok]):
        n = int((seg == sid).sum())
        if n > best[0]: best = (n, sid)
    if best[0] < 3600:
        print("No clean stretch of >= 1 h found in this file. Send a longer, non-railed recording.")
        sys.exit(2)
    clean = b[seg == best[1]]
    t_clean = df["t"][seg == best[1]]

    # FAULT episode (optional) = rows in the Oct 12-14 railed log, if this file has them
    fmask = (df.t >= "2026-10-12 22:03") & (df.t <= "2026-10-14 17:52")
    fault = b[fmask.to_numpy()]

    L = []
    L.append(f"clean stretch: {len(clean)} rows ({len(clean)/3600:.1f} h)  {t_clean.min()} -> {t_clean.max()}")
    L.append(f"fault-episode rows in file: {len(fault)} ({len(fault)/3600:.1f} h)" + ("" if len(fault) >= 3600 else "  -> experiment A skipped"))

    # B. clean only
    r, dg, du, sg, su = run(clean)
    L.append("\n[B] CLEAN BASELINE (no fault; no stress unless your log has stimulus events)")
    L.append(f"  gate rejected: {(r!='none').mean()*100:.2f}%  reasons={ {k:int(v) for k,v in pd.Series(r[r!='none']).value_counts().items()} }")
    L.append(f"  deviation samples: {dg.mean()*100:.2f}% of rows ({rate(dg,sg):.1f}/h sample-level)")
    L.append(f"  alarm EVENTS (>=10 consecutive deviation samples): gated={events(dg)}  ungated={events(du)}")

    # A. real fault spliced before clean
    if len(fault) >= 3600:
        seq = np.concatenate([fault, clean]); k = len(fault)
        r, dg, du, sg, su = run(seq)
        L.append("\n[A] REAL FAULT EPISODE then clean data (spliced)")
        fr = r[:k]
        bad = fr != "none"
        L.append(f"  during fault: gate rejected {bad.mean()*100:.1f}% of rows  reasons={ {kk:int(v) for kk,v in pd.Series(fr[bad]).value_counts().items()} }")
        L.append(f"  of those invalid rows: GATED labelled them low_confidence (no alert, no learning) = {int(bad.sum())}")
        nd = ~du[:k][bad]
        L.append(f"                         UNGATED labelled {int(nd.sum())} of them as normal and kept learning from them ({nd.mean()*100:.1f}%)")
        first = slice(k, k + 3600 * 2)     # first 2 h after faults end
        L.append(f"  first 2 h after fault ends: deviation samples  gated={int(dg[first].sum())}  ungated={int(du[first].sum())}")
        L.append(f"  alarm EVENTS in clean part: gated={events(dg[k:])}  ungated={events(du[k:])}")

    # C. injected faults (needs enough clean data to place episodes after cold start)
    LOW, NEED = 1000, 5000
    if len(clean) < NEED:
        L.append(f"\n[C] INJECTED FAULTS skipped: clean stretch has {len(clean)} rows, need >= {NEED} (about {NEED/3600:.1f} h).")
    else:
        rng = np.random.default_rng(7)
        x = clean.copy(); lab = np.zeros(len(x), bool)
        hi = len(x) - 1300                              # leave room for the longest episode
        for _ in range(6):                              # rail episodes 5-20 min
            a = rng.integers(LOW, hi); d = int(rng.integers(300, 1200)); x[a:a+d] = 4095; lab[a:a+d] = True
        for _ in range(12):                             # single-sample spikes
            a = rng.integers(LOW, len(x) - 10); x[a] = x[a] + rng.choice([-1, 1]) * 1800; lab[a] = True
        for _ in range(4):                              # offset steps (contact shift) 10 min
            a = rng.integers(LOW, len(x) - 700); x[a:a+600] += 400; lab[a:a+600] = True
        r, dg, du, sg, su = run(x)
        L.append("\n[C] INJECTED FAULTS on clean data (SIMULATED: 6 rail episodes, 12 spikes, 4 offset steps)")
        caught = (r != "none")
        L.append(f"  injected-fault rows caught by gate: {caught[lab].mean()*100:.1f}%  (note: offset steps within normal range are not gate-detectable)")
        L.append(f"  clean rows wrongly rejected: {caught[~lab].mean()*100:.2f}%")
        L.append(f"  deviation alarms on whole run  gated={dg.sum()}  ungated={du.sum()}")
    L.append("\n  memory: ring = %d floats (%.1f KB), constant regardless of run length" % (N, N*4/1024))
    txt = "\n".join(L); print(txt)
    with open(os.path.join(out, "replay_eval_summary.txt"), "w") as f:
        f.write(txt + "\n")

if __name__ == "__main__":
    main()