"""PhytoSense++ reliability report from the logged CSVs.
Run from repo root:  python analysis/reliability_report.py
Writes out/reliability_report.txt and prints it."""
import os, sys
import numpy as np, pandas as pd

FILES = ["data/phytosense_trial_log.csv", "data/trial_v7.csv", "data/preflight_90min.csv"]
GAP_S = 5          # a gap bigger than this between rows = missed samples
RAIL = 4090

def report(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["wall_clock_time"], format="mixed")
    d = d.sort_values("t").reset_index(drop=True)
    dt = d["t"].diff().dt.total_seconds().dropna()
    span_h = (d["t"].iloc[-1] - d["t"].iloc[0]).total_seconds() / 3600
    gaps = dt[dt > GAP_S]
    expected = span_h * 3600
    out = [f"== {path} ==",
           f"rows={len(d)}  span={span_h:.1f} h  ({d['t'].iloc[0]} -> {d['t'].iloc[-1]})",
           f"sample interval: median={dt.median():.2f}s  p99={dt.quantile(.99):.2f}s  max={dt.max():.0f}s",
           f"gaps > {GAP_S}s: {len(gaps)}  total missing={gaps.sum()/3600:.2f} h  "
           f"longest={gaps.max()/3600 if len(gaps) else 0:.2f} h",
           f"logging availability: {100*(1-gaps.sum()/expected):.2f}%"]
    # restarts: uptime_ms going backwards
    if "uptime_ms" in d:
        rb = (d["uptime_ms"].diff() < 0).sum()
        out.append(f"reboots (uptime reset): {rb}")
    b = d["bioelectric_raw"]
    out.append(f"bio railed (>= {RAIL}): {100*(b>=RAIL).mean():.1f}%   bio <=50: {100*(b<=50).mean():.1f}%")
    contact = ((d["lo_plus"] == 1) | (d["lo_minus"] == 1)).mean()
    out.append(f"leads-off (contact bad): {100*contact:.2f}%")
    t = d["temp_c"]; h = d["humidity_pct"]; p = d["pressure_hpa"]
    out.append(f"implausible env rows: temp={((t<-10)|(t>60)).sum()}  hum={((h<0)|(h>100)).sum()}  "
               f"pres={((p<850)|(p>1100)).sum()}  NaN temp={t.isna().sum()}")
    out.append("status: " + str(d["reading_status"].value_counts().to_dict()))
    # per-day usable-signal table
    d["day"] = d["t"].dt.date
    d["good"] = (b < RAIL) & (b > 50)
    day = d.groupby("day").agg(rows=("good", "size"), good_pct=("good", lambda x: 100*x.mean()))
    out.append("per-day (rows, % non-railed):")
    out.append(day.round(1).to_string())
    return "\n".join(out)

if __name__ == "__main__":
    txt = "\n\n".join(report(f) for f in FILES if os.path.exists(f))
    os.makedirs("out", exist_ok=True)
    open("out/reliability_report.txt", "w").write(txt)
    print(txt)