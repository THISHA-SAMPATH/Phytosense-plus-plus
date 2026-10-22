"""Audit known rail samples and replay firmware-like baseline admission on real logs."""
import json, platform, subprocess
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
try:
    from .research_common import FILES, OUT, REPORTS, ROOT, load, prepare_dirs, firmware_gate, MeanRing
except ImportError:
    from research_common import FILES, OUT, REPORTS, ROOT, load, prepare_dirs, firmware_gate, MeanRing

N, MIN_N, Z, PERSIST, RESET_BAD = 1800, 200, 3.0, 10, 600

def episodes(d, rail, merge_seconds=10):
    idx=np.flatnonzero(rail)
    if not len(idx): return pd.DataFrame(columns=["start","end","samples","elapsed_s"])
    t=d.t.to_numpy(); groups=[]; current=[idx[0]]; prev=idx[0]
    for i in idx[1:]:
        if (t[i]-t[prev]).astype('timedelta64[ms]').astype(int)/1000 > merge_seconds:
            groups.append(current); current=[i]
        else: current.append(i)
        prev=i
    groups.append(current)
    return pd.DataFrame([dict(start=t[g[0]],end=t[g[-1]],samples=len(g),elapsed_s=(t[g[-1]]-t[g[0]]).astype('timedelta64[ms]').astype(int)/1000) for g in groups])

def replay(d, gated, reasons):
    x=d.bioelectric_raw.to_numpy(float); times=d.t.to_numpy(dtype='datetime64[ms]'); ring=MeanRing(N); run=bad=0; prevt=None; rows=[]
    for i,v in enumerate(x):
        dt=1.0 if prevt is None else max(float((times[i]-prevt).astype('timedelta64[ms]').astype(int))/1000,0)
        prevt=times[i]
        good=(reasons[i]=="none") if gated else True
        bad=0 if good else bad+1
        if gated and bad==RESET_BAD: ring=MeanRing(N); run=0
        if len(ring.q)>=MIN_N:
            m,s=ring.stats(); z=(v-m)/(s+1e-6) if good or not gated else np.nan
            run=(run+1 if abs(z)>Z else 0) if good or not gated else 0
            alert=run>=PERSIST if good or not gated else False
        else: m,s,z,alert=np.nan,np.nan,np.nan,False
        admitted=bool(good)
        if admitted: ring.push(v)
        m2,s2=ring.stats() if ring.q else (np.nan,np.nan)
        rows.append((m2,s2,admitted,alert,run,len(ring.q),reasons[i]))
    return pd.DataFrame(rows,columns=["baseline_center","baseline_sd","admitted","alert","deviation_run","baseline_count","gate_reason"])

def main():
    prepare_dirs(); source=ROOT/"data"/"phytosense_trial_log.csv"; raw=pd.read_csv(source,low_memory=False); d=load(source)
    x=d.bioelectric_raw.to_numpy(float); rail=(x>=4090)|(x<=50); reason=firmware_gate(d)
    ep=episodes(d,rail,10); ep.to_csv(OUT/"real_fault_episodes.csv",index=False)
    a=replay(d,False,reason); b=replay(d,True,reason)
    ts=pd.concat([d[["t","bioelectric_raw"]].rename(columns={"bioelectric_raw":"raw_adc"}),a.add_prefix("ungated_"),b.add_prefix("gated_")],axis=1)
    ts["known_rail"]=rail; ts.to_csv(OUT/"real_fault_replay_timeseries.csv",index=False)
    clean=d.loc[~rail & (reason=="none"),"bioelectric_raw"]
    ref=float(clean.iloc[:min(3600,len(clean))].median()) if len(clean) else np.nan
    scale=float(1.4826*np.median(np.abs(clean.iloc[:min(3600,len(clean))]-ref))) if len(clean) else np.nan
    metrics=[]
    for name,r in (("gate_disabled",a),("gate_enabled",b)):
        disp=r.baseline_center-ref
        metrics.append(dict(mode=name,known_rail_samples=int(rail.sum()),rail_admitted=int((rail&r.admitted.to_numpy()).sum()),rail_admission_fraction=float((rail&r.admitted.to_numpy()).sum()/max(rail.sum(),1)),reference_adc=ref,reference_mad_scale=scale,peak_abs_displacement_adc=float(disp.abs().max()),peak_abs_displacement_mad=float(disp.abs().max()/scale) if scale else np.nan,material_displacement_s_at_3mad=float(d.loc[disp.abs()>3*scale,"t"].diff().dt.total_seconds().clip(0,10).sum()) if scale else np.nan,valid_samples_rejected=int((~rail & ~r.admitted.to_numpy()).sum()) if name=="gate_enabled" else 0))
    pd.DataFrame(metrics).to_csv(OUT/"real_fault_metrics.csv",index=False)
    pd.DataFrame({"t":d.t,"reason":reason,"known_rail":rail,"accepted":b.admitted}).groupby(["reason","known_rail","accepted"]).size().rename("samples").reset_index().to_csv(OUT/"real_fault_reasons.csv",index=False)
    fig,ax=plt.subplots(3,1,figsize=(14,9),sharex=True)
    ax[0].plot(d.t,x,lw=.35); ax[0].axhline(4090,color='r',ls='--',label='rail threshold 4090 ADC'); ax[0].set_ylabel('Raw ADC (counts)'); ax[0].legend()
    ax[1].plot(d.t,a.baseline_center,label='gate disabled',lw=.6); ax[1].plot(d.t,b.baseline_center,label='gate enabled',lw=.6); ax[1].set_ylabel('Baseline centre (ADC)'); ax[1].legend()
    ax[2].plot(d.t,(a.baseline_center-ref)/scale,label='ungated'); ax[2].plot(d.t,(b.baseline_center-ref)/scale,label='gated'); ax[2].axhline(3,color='k',ls=':'); ax[2].axhline(-3,color='k',ls=':'); ax[2].set_ylabel('Displacement (MAD)'); ax[2].set_xlabel('Timestamp (naive wall-clock; timezone not encoded)'); ax[2].legend()
    fig.tight_layout(); fig.savefig(OUT/"real_fault_replay.png",dpi=140); plt.close(fig)
    rawx=raw.bioelectric_raw.to_numpy(float); rawrail=int(((rawx>=4090)|(rawx<=50)).sum())
    report=f'''# Real fault replay\n\nSource: `data/phytosense_trial_log.csv` ({len(raw):,} source rows; {len(d):,} unique timestamps after deterministic duplicate coalescing). The wall clock is naive and has no timezone marker. Firmware logs an average of 20 ADC samples per cycle; for this file per-cycle min/max/n_sat are absent, so high-rail detection is approximated by logged average >=4090.\n\nKnown rail-valued source rows (>=4090 or <=50): **{rawrail:,}** (high={(rawx>=4090).sum():,}, low={(rawx<=50).sum():,}); {rail.sum():,} unique rail timestamps remain after coalescing. Grouping rail rows separated by at most 10 seconds produces {len(ep)} episodes; this is an operational grouping, with actual timestamps and elapsed durations in `out/revised/real_fault_episodes.csv`. These rows are spread across the recording, including early isolated samples, so the aggregate must not be described as one continuous 93,154-second episode.\n\nFirmware uses 20-read average, digital leads-off, average/sample saturation rails, rolling 60-sample standard deviation <2, and absolute one-step jump >1200. Priority is contact, high rail, low rail, flat, jump. A good sample is scored against the current baseline and then pushed; baseline is a 1800-value rolling **mean/sample SD**, begins alerting after 200 values, threshold |z|>3, persistence 10. On 600 consecutive rejected cycles it clears the ring; this retains no baseline state. Flat ring, previous-sample state, and deviation run are not cleared by that reset. The replay mirrors sample-count behavior; missing elapsed time does not consume state. This cannot reconstruct the original early firmware processing or hidden ADC sample saturation.\n\nThe replay starts with an empty baseline at the beginning of this CSV, which is primarily a faulty early stream; it is not a shared known-clean initialized state. Its ungated arm admits all rail-valued samples; gated arm excludes reasons derived from available fields. This shows algorithmic admission, not a calibrated causal estimate of a deployed firmware run. Results and time series are in the CSV outputs. The reference uses the first up to 3600 nonrail, gate-accepted samples in chronological order; this period is not guaranteed biologically stable.\n\nNo claim of real biological recovery is made: the log has extensive gaps and separated recording sessions; a transition from fault to later clean data cannot be treated as continuous recovery. See benchmark timestamp handling and the source data audit for gap limits.\n'''
    (REPORTS/"real_fault_analysis.md").write_text(report,encoding='utf-8')
    print(f"rail samples={rail.sum()} episodes={len(ep)}; wrote replay artifacts")

if __name__=='__main__': main()
