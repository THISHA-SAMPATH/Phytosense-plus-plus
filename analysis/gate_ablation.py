"""Ablate the five firmware gate checks on the main historical CSV."""
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
try:
    from .research_common import ROOT, OUT, REPORTS, load, prepare_dirs
    from .real_fault_replay import replay
except ImportError:
    from research_common import ROOT, OUT, REPORTS, load, prepare_dirs
    from real_fault_replay import replay

CHECKS=["contact","rail_hi","rail_lo","flat","jump"]
def flags(d):
    x=d.bioelectric_raw.to_numpy(float); lo=(d.lo_plus.fillna(0).to_numpy(float)!=0)|(d.lo_minus.fillna(0).to_numpy(float)!=0)
    f={k:np.zeros(len(d),bool) for k in CHECKS}; hist=[]; prev=None
    for i,v in enumerate(x):
        hist.append(v); hist=hist[-60:]
        f['contact'][i]=lo[i]
        f['rail_hi'][i]=v>=4090 or ('n_sat' in d and d.n_sat.iloc[i]>=5)
        f['rail_lo'][i]=v<=50
        f['flat'][i]=len(hist)==60 and np.std(hist,ddof=1)<2
        f['jump'][i]=prev is not None and abs(v-prev)>1200
        prev=v
    return f
def main():
    prepare_dirs(); d=load(ROOT/'data'/'phytosense_trial_log.csv'); f=flags(d)
    x=d.bioelectric_raw.to_numpy(float); known=(x>=4090)|(x<=50); proxy=~known
    base_good=~np.logical_or.reduce([f[k] for k in CHECKS]); ref_values=x[base_good & ~known][:3600]
    reference=float(np.median(ref_values)); ref_scale=float(1.4826*np.median(np.abs(ref_values-reference)))
    names={"full":CHECKS,**{k:[k] for k in CHECKS},**{f"leave_out_{k}":[q for q in CHECKS if q!=k] for k in CHECKS}}
    rows=[]
    for name,checks in names.items():
        rej=np.logical_or.reduce([f[k] for k in checks]) if checks else np.zeros(len(d),bool)
        good=~rej; metrics=replay(d,True,np.where(good,'none','rejected'))
        disp=(metrics.baseline_center-reference).abs(); dt=d.t.diff().dt.total_seconds().clip(0,10)
        rows.append(dict(configuration=name,checks='|'.join(checks),samples=len(d),rejected=int(rej.sum()),known_rail=int(known.sum()),known_rail_rejected=int((rej&known).sum()),known_rail_rejection_rate=float((rej&known).sum()/max(known.sum(),1)),nonrail_proxy=int(proxy.sum()),nonrail_proxy_rejected=int((rej&proxy).sum()),nonrail_proxy_rejection_rate=float((rej&proxy).sum()/max(proxy.sum(),1)),valid_monitoring_s=float(dt.where(good,0).sum()),rail_admitted=int((known&good).sum()),baseline_reference_adc=reference,baseline_reference_mad=ref_scale,baseline_peak_abs_displacement_adc=float(disp.max()),material_displacement_over_3mad_s=float(dt.where(disp>3*ref_scale,0).sum()) if ref_scale else np.nan))
    out=pd.DataFrame(rows); out.to_csv(OUT/'gate_ablation_combinations.csv',index=False)
    single=out[out.configuration.isin(CHECKS+['full'])].copy(); single['proxy_label_note']='non-rail, non-rejected samples are presumed-good proxy only; no complete independent labels'
    single.to_csv(OUT/'gate_ablation.csv',index=False)
    fig,ax=plt.subplots(1,2,figsize=(12,4)); plot=single.set_index('configuration').reindex(CHECKS+['full']);
    plot.known_rail_rejection_rate.mul(100).plot.bar(ax=ax[0],color='tab:red'); ax[0].set_ylabel('Known rail rejected (%)');
    plot.nonrail_proxy_rejection_rate.mul(100).plot.bar(ax=ax[1],color='tab:blue'); ax[1].set_ylabel('Non-rail proxy rejected (%)');
    for a in ax:a.set_xlabel('Firmware check / full gate')
    fig.tight_layout(); fig.savefig(OUT/'gate_ablation.png',dpi=140); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,5));
    ax.scatter(out.valid_monitoring_s/3600,out.known_rail_rejected,label='Known rail samples rejected',s=45)
    for _,r in out.iterrows(): ax.annotate(r.configuration,(r.valid_monitoring_s/3600,r.known_rail_rejected),fontsize=7,xytext=(3,3),textcoords='offset points')
    ax.set_xlabel('Valid monitoring time retained (hours; elapsed timestamps, gaps >10 s excluded)'); ax.set_ylabel('Known rail-valued samples rejected (count)'); ax.set_title('Gate trade-off on available labels'); ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(OUT/'gate_tradeoff.png',dpi=140); plt.close(fig)
    (REPORTS/'gate_ablation.md').write_text(f'''# Quality-gate ablation\n\nThe gate has exactly five checks: {', '.join(CHECKS)}. They are defined in `firmware/src/main.cpp`: contact = either leads-off pin, high rail = average >=4090 or >=5 of 20 raw ADC samples at >=4090, low rail = average <=50, flat = sample SD of last 60 logged averages <2, jump = absolute change >1200 from previous cycle. Historical main CSV contains leads-off and average only, with no n_sat/min/max, so high-rail evaluation uses average >=4090 and may miss mixed saturated cycles.\n\n`gate_ablation.csv` reports each check alone and full gate; `gate_ablation_combinations.csv` also reports leave-one-out. Rail-valued rows are the only directly known fault label. All other rows are called non-rail proxy and must not be interpreted as complete good labels; they may include undetected corruption. Overlap is preserved through OR composition. The baseline replay uses the available logged values and firmware-like ring, but does not prove deployed fault causality.\n\nNo check should be removed based on this single dataset. Check redundancy is dataset-specific: identical rejection masks are observable overlap, not evidence of functional equivalence on unrecorded failure modes.\n''',encoding='utf-8')
    print(out[['configuration','known_rail_rejected','nonrail_proxy_rejected']].to_string(index=False))
if __name__=='__main__':main()
