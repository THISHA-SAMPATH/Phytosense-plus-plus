import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
import sys
OUT = sys.argv[1]; DST = sys.argv[2]
ev = pd.read_csv(f"{OUT}/bench_events.csv")
fa = pd.read_csv(f"{OUT}/bench_fa.csv")
folds = pd.read_csv(f"{OUT}/bench_folds.csv")
pass
pass
days = sorted(set(ev.key))

# ---- 1. trade-off curve: every setting, all days pooled ----
rows = []
for s, g in fa.groupby("setting"):
    f = g.onsets.sum() / g.hours.sum()
    e = ev[(ev.setting == s) & (ev.kind == "sustained") & (ev.mag == 6)]
    lat = e.latency.dropna()
    rows.append(dict(setting=s, family=g.family.iloc[0], fa_per_h=f,
                     sustained6_alerted_frac=e.frac.mean(),
                     sustained6_median_latency_s=lat.median() if len(lat) else np.nan))
tr = pd.DataFrame(rows).sort_values(["family", "fa_per_h"])
tr.to_csv(f"{DST}/bench_tradeoff.csv", index=False)

fig, ax = plt.subplots(1, 2, figsize=(10, 4.2))
style = {"baseline": ("k", "o"), "freeze": ("tab:red", "s"), "winsor": ("tab:orange", "^"),
         "cusum": ("tab:blue", "D"), "ph": ("tab:green", "v")}
for fam, g in tr.groupby("family"):
    c, m = style[fam]
    if fam in ("baseline", "freeze", "winsor"):
        ax[0].scatter(g.fa_per_h, g.sustained6_alerted_frac, c=c, marker=m, s=60, label=fam, zorder=3)
        ax[1].scatter(g.fa_per_h, g.sustained6_median_latency_s, c=c, marker=m, s=60, label=fam, zorder=3)
    else:
        ax[0].plot(g.fa_per_h, g.sustained6_alerted_frac, c=c, marker=m, label=fam)
        ax[1].plot(g.fa_per_h, g.sustained6_median_latency_s, c=c, marker=m, label=fam)
        for _, r in g.iterrows():
            ax[1].annotate(r.setting.split("(")[1].rstrip(")"), (r.fa_per_h, r.sustained6_median_latency_s),
                           fontsize=6, xytext=(3, 3), textcoords="offset points")
for a in ax:
    a.set_xscale("symlog", linthresh=0.5); a.set_xlabel("clean false alarms per hour (all days, log scale)")
    a.axvline(1.0, ls=":", c="grey"); a.grid(alpha=0.3)
ax[0].set_ylabel("share of +6 SD sustained shift alerted")
ax[1].set_ylabel("median time to first alert (s), +6 SD sustained")
ax[1].set_yscale("symlog", linthresh=10)
ax[0].legend(fontsize=8); ax[1].legend(fontsize=8)
fig.suptitle("Synthetic +6 SD sustained shifts, 10 min. Dotted line = 1 FA/h budget. Synthetic events only.", fontsize=9)
plt.tight_layout(); plt.savefig(f"{DST}/fig_tradeoff.png", dpi=150)

# ---- 2. drop-one-day sensitivity (uses the leave-one-day-out choices) ----
def pooled(exclude):
    use = [d for d in days if d != exclude]
    sel_ev, sel_fa = [], []
    for held in use:
        for _, r in folds[folds.held_out == held].iterrows():
            sel_ev.append(ev[(ev.setting == r.chosen) & (ev.key == held)])
        for st in ["baseline", "freeze", "winsor"]:
            sel_ev.append(ev[(ev.setting == st) & (ev.key == held)])
        for fam, g in folds[folds.held_out == held].groupby("family"):
            pass
        sel_fa += [fa[(fa.setting == st) & (fa.key == held)] for st in ["baseline", "freeze", "winsor"]]
        sel_fa += [fa[(fa.setting == r.chosen) & (fa.key == held)] for _, r in folds[folds.held_out == held].iterrows()]
    E = pd.concat(sel_ev); F = pd.concat(sel_fa)
    out = {}
    for fam in ["baseline", "freeze", "winsor", "cusum", "ph"]:
        e = E[(E.family == fam) & (E.kind == "sustained") & (E.mag == 6)]
        f = F[F.family == fam]
        out[fam] = dict(sust6_alerted=e.frac.mean(), fa_per_h=f.onsets.sum() / f.hours.sum())
    return out

rows = []
full = pooled(None)
for fam, v in full.items():
    rows.append(dict(drop="none", family=fam, **v))
for d in days:
    for fam, v in pooled(d).items():
        rows.append(dict(drop=d, family=fam, **v))
sens = pd.DataFrame(rows)
sens.to_csv(f"{DST}/bench_drop_one_day.csv", index=False)
print(sens.round(3).to_string(index=False))
print("\nTradeoff table:")
print(tr.round(3).to_string(index=False))