"""Moving-mean reference derivation and deterministic firmware-like step simulations."""
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from collections import deque
from pathlib import Path
try:
    from .research_common import ROOT, OUT, REPORTS, prepare_dirs
except ImportError:
    from research_common import ROOT, OUT, REPORTS, prepare_dirs

def theory(n, delta, sigma, z):
    # remaining signal-to-moving-mean residual after k shifted values enter full ring
    q=z*sigma/abs(delta)
    return 0 if q>1 else int(np.floor(n*(1-q))+1)

def sim(n,delta,sigma,z,persist,policy,seed=41):
    rng=np.random.default_rng(seed); base=deque(rng.normal(0,sigma,n).tolist(),maxlen=n); sm=sum(base); ss=sum(v*v for v in base); ref=sm/n; devrun=0; alarm=False; onset=None; cleared=None; trans=[]
    signal=np.r_[rng.normal(0,sigma,200),rng.normal(delta,sigma,5*n),rng.normal(0,sigma,3*n)]
    for i,v in enumerate(signal):
        m=sm/n; s=float(np.sqrt(max((ss-sm*sm/n)/(n-1),0))); score=(v-m)/(s+1e-6)
        devrun=devrun+1 if abs(score)>z else 0
        if devrun>=persist and onset is None: onset=i-persist+1; alarm=True
        if alarm and abs(score)<=z and cleared is None: cleared=i
        if policy=='freeze' and abs(score)>z: pass
        elif policy=='gatefreeze' and abs(score)>z: pass
        else:
            old=base[0]; base.append(float(v)); sm+=float(v)-old; ss+=float(v*v)-old*old
        trans.append(m-ref)
    # Detector clears at first below-threshold sample after alarm; this is different from mean absorption.
    return dict(window_n=n,delta=delta,noise_sigma=sigma,z=z,persistence=persist,policy=policy,seed=seed,onset_index=onset,alarm_clear_index=cleared,baseline_peak_abs=float(np.max(np.abs(trans))),baseline_final=float(trans[-1]),theory_samples=theory(n,delta,sigma,z),sim_absorb_samples=next((i for i,q in enumerate(trans) if i>200 and abs(delta-q)<=z*sigma),None),alarm_duration_samples=(cleared-onset+1 if cleared is not None and onset is not None else None),baseline='rolling arithmetic mean/sample SD, sample-count window')

def main():
    prepare_dirs(); ns=[300,600,900,1800]; deltas=[3,4,6]; sigmas=[1.0,2.0]; zs=[2.5,3.0]; persists=[5,10]; policies=['update','freeze','gatefreeze']
    rows=[]
    for n in ns:
      for delta in deltas:
       for sigma in sigmas:
        for z in zs:
         for p in persists:
          for policy in policies: rows.append(sim(n,delta,sigma,z,p,policy))
    d=pd.DataFrame(rows); d.to_csv(OUT/'window_sweep.csv',index=False)
    d['theory_seconds_at_1hz']=d.theory_samples
    d[['window_n','delta','noise_sigma','z','persistence','policy','seed','theory_samples','theory_seconds_at_1hz','sim_absorb_samples','alarm_clear_index','alarm_duration_samples','baseline_peak_abs','baseline_final']].to_csv(OUT/'absorption_theory_vs_simulation.csv',index=False)
    fig,ax=plt.subplots(2,2,figsize=(11,8)); sub=d[(d.noise_sigma==1)&(d.z==3)&(d.persistence==10)]
    q=sub.groupby(['window_n','delta']).sim_absorb_samples.median().unstack(); q.plot(ax=ax[0,0]); ax[0,0].set(title='Simulated absorption',xlabel='Window (samples)',ylabel='Samples after shift')
    for delta in deltas:
      s=sub[sub.delta==delta].groupby('window_n').sim_absorb_samples.median(); ax[0,1].plot(s.index,s.values,'o-',label=f'delta={delta} sigma'); ax[0,1].plot(s.index,[theory(n,delta,1,3) for n in s.index],'--')
    ax[0,1].set(title='Window-size sweep (solid simulation, dashed theory)',xlabel='Window (samples)',ylabel='Samples'); ax[0,1].legend()
    for delta in deltas:
      s=sub[sub.delta==delta].groupby('noise_sigma').sim_absorb_samples.median(); ax[1,0].plot(s.index,s.values,'o-',label=f'delta={delta}')
    ax[1,0].set(title='Noise-scale sweep',xlabel='Noise sigma',ylabel='Samples'); ax[1,0].legend()
    s=d[(d.window_n==900)&(d.delta==6)&(d.noise_sigma==1)&(d.z==3)].groupby('policy').alarm_duration_samples.median(); s.plot.bar(ax=ax[1,1]); ax[1,1].set(title='Alarm duration by update policy',xlabel='Policy',ylabel='Samples')
    fig.tight_layout(); fig.savefig(OUT/'absorption_plots.png',dpi=140); plt.close(fig)
    (REPORTS/'baseline_absorption.md').write_text('''# Baseline absorption: derivation and simulation\n\nFor a full rolling arithmetic-mean buffer of N old observations at level μ, after k persistent step observations at μ+δ replace old values, the mean is μ_k=μ+(k/N)δ for 0≤k≤N. The remaining signal-to-mean difference is |δ|−(k/N)|δ|=|δ|(1−k/N). For a fixed threshold zσ, absorption at or below threshold occurs when |δ|(1−k/N)≤zσ, hence k≥N(1−zσ/|δ|); the first integer is ceil(max(0,N(1−zσ/|δ|))). For strict-below, the first integer is floor(max(0,N(1−zσ/|δ|)))+1. The detector uses strict `>` so equality is not alarm.\n\nThe repository firmware baseline is an arithmetic rolling mean and sample SD over 1800 values, but its scale is adaptive, scores before pushing, uses gating, and persistence=10. The equation describes mean displacement only under fixed σ and uninterrupted valid samples. It does not predict alarm clearing when sample variance changes. It also does not apply to robust median/MAD models; this implementation is not median/MAD.\n\n`window_sweep.csv` is a deterministic software simulation over sample-count windows (300, 600, 900, 1800), shifts (3/4/6 σ), fixed noise (σ=1/2), thresholds (2.5/3), persistence (5/10), and update/freeze policies. No irregular timestamps or firmware gates are simulated here; sample counts equal seconds only under the explicit 1 Hz synthetic assumption. Synthetic results are methodological illustrations, not plant-stress evidence. The code currently measures mean displacement and threshold clearing separately; fixed-scale theory and adaptive-SD simulation need not match.\n''',encoding='utf-8')
if __name__=='__main__':main()
