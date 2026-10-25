"""Timestamp-aware, separate-output rerun of the existing six-detector benchmark.

The detector algorithms and hyperparameter grids are imported unchanged from
analysis/benchmark.py. Detector windows, persistence, and reset counters remain
observation counts; event windows, warm-up, scoring, monitoring denominators,
and episode timestamps use elapsed wall-clock time.
"""
from __future__ import annotations
import hashlib, json, math, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    from . import benchmark as legacy
    from .benchmark_time import coalesce_timestamps, event_mask, monitoring_hours, alarm_episodes, quality_gate
except ImportError:
    import benchmark as legacy
    from benchmark_time import coalesce_timestamps, event_mask, monitoring_hours, alarm_episodes, quality_gate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out'/'corrected'
FILES=[ROOT/p for p in legacy.FILES]
MAX_GAP_S=legacy.GAP_S
WARMUP_S=legacy.SKIP_S
MIN_GOOD_H=legacy.MIN_GOOD_H
EVENT_LEAD_S=legacy.EVENT_LEAD_S
EVENT_SPACING_S=legacy.EVENT_SPACING_S
GUARD_S=legacy.GUARD_S
FA_BUDGET=legacy.FA_BUDGET
SEED=0

def load_sessions(path):
    raw=pd.read_csv(path,low_memory=False)
    d=coalesce_timestamps(raw)
    labels=session_labels(d.timestamp)
    sessions=[]
    for sid in np.unique(labels):
        s=d.iloc[np.flatnonzero(labels==sid)].reset_index(drop=True)
        if not len(s): continue
        t=pd.DatetimeIndex(s.timestamp)
        bio=s.bioelectric_raw.to_numpy(float)
        lo=((s.lo_plus.fillna(0).to_numpy(float)!=0)|(s.lo_minus.fillna(0).to_numpy(float)!=0))
        sat=s.n_sat.to_numpy(float) if 'n_sat' in s else None
        good=quality_gate(bio,lo,sat)
        after=t>=t[0]+pd.Timedelta(seconds=WARMUP_S)
        valid_h=monitoring_hours(t,good&after,MAX_GAP_S)
        if valid_h<MIN_GOOD_H: continue
        source=path.name; fold=f'{source}|{t[0].date().isoformat()}'
        sessions.append(dict(key=f'{fold}|session{int(sid)}',fold=fold,source=source,day=t[0].date().isoformat(),t=t,bio=bio,lo=lo,n_sat=sat,good=good,valid_hours=valid_h,duplicate_rows=len(raw)-len(d)))
    return sessions

def fold_split(keys):
    keys=sorted(set(keys))
    return [(held,[k for k in keys if k!=held]) for held in keys]

def session_labels(times,max_gap_s=MAX_GAP_S):
    dt=pd.Series(pd.to_datetime(times)).diff().dt.total_seconds().fillna(0).to_numpy()
    return np.cumsum(dt>max_gap_s)

def robust_scale(x,good,times):
    warm=(pd.DatetimeIndex(times)<times[0]+pd.Timedelta(seconds=WARMUP_S))&good&np.isfinite(x)
    v=np.asarray(x)[warm]
    if len(v)<legacy.MIN_N: return np.nan
    med=np.median(v); return float(1.4826*np.median(np.abs(v-med)))

def pooled_training_scale(sessions):
    scales=[robust_scale(s['bio'],s['good'],s['t']) for s in sessions]
    scales=[v for v in scales if np.isfinite(v) and v>0]
    return float(np.median(scales)) if scales else np.nan

def inject_elapsed(session,scale,kind,mag,duration_s,seed=SEED):
    """Inject fixed, elapsed-time events; return changed stream and full manifest.

    Seed is included in provenance. Placements are deterministic fixed offsets,
    so no held-out data are consulted to select event positions.
    """
    x=session['bio']; times=session['t']; y=x.copy(); manifests=[]
    if not np.isfinite(scale) or scale<=0:
        return y,[dict(kind=kind,mag_sd=mag,requested_duration_s=duration_s,seed=seed,status='excluded_no_training_scale')]
    onset0=times[0]+pd.Timedelta(seconds=WARMUP_S+EVENT_LEAD_S)
    spacing=pd.Timedelta(seconds=EVENT_SPACING_S)
    ordinal=0; start=onset0
    while start<times[-1]:
        if kind=='permanent': end=times[-1]+pd.Timedelta(seconds=1)
        else: end=start+pd.Timedelta(seconds=float(duration_s))
        observed=event_mask(times,start,(end-start).total_seconds())
        idx=np.flatnonzero(observed)
        # A full transient and post-event guard must be represented. Permanent
        # events are scored through the recording end and have no post guard.
        enough=(len(idx)>0 and (kind=='permanent' or end+pd.Timedelta(seconds=GUARD_S)<=times[-1]))
        row=dict(session=session['key'],fold=session['fold'],kind=kind,mag_sd=mag,start_timestamp=start,end_timestamp=end,
                 requested_duration_s=(end-start).total_seconds(),actual_duration_s=(end-start).total_seconds(),
                 observed_samples=len(idx),seed=seed,status='planned',amplitude_adc=float(mag*scale),units='ADC counts')
        row['first_affected_sample']=times[idx[0]] if len(idx) else pd.NaT
        row['last_affected_sample']=times[idx[-1]] if len(idx) else pd.NaT
        row['observed_span_s']=(times[idx[-1]]-times[idx[0]]).total_seconds() if len(idx)>1 else 0.0
        if not enough:
            row['status']='excluded_insufficient_elapsed_coverage'; manifests.append(row); break
        if kind=='rail': y[idx]=4095.0
        elif kind=='drift':
            frac=np.clip((times[idx]-start).total_seconds()/max((end-start).total_seconds(),1e-12),0,1)
            y[idx]=y[idx]+mag*scale*frac
        else: y[idx]=y[idx]+mag*scale
        if kind!='rail' and ((y[idx]>=4090)|(y[idx]<=50)).any():
            y[idx]=x[idx]; row['status']='excluded_adc_limit'
        manifests.append(row)
        if kind=='permanent': break
        ordinal+=1; start=onset0+ordinal*spacing
    return y,manifests

def score_instance(times,alarm,start,end,clean_alarm=None,guard_s=GUARD_S):
    t=pd.DatetimeIndex(times); a=np.asarray(alarm,bool)
    # Timestamp indices let each score touch only its event and guard window.
    # Build alarm episodes with NumPy once per call; avoid pandas scalar boxing.
    tn=t.asi8; start_ns=pd.Timestamp(start).value; end_ns=pd.Timestamp(end).value
    guard_ns=end_ns+int(pd.Timedelta(seconds=guard_s).value)
    gap_ns=int(pd.Timedelta(seconds=MAX_GAP_S).value)
    lo=int(np.searchsorted(tn,start_ns,'left')); hi=int(np.searchsorted(tn,end_ns,'left'))
    ghi=int(np.searchsorted(tn,guard_ns,'left'))
    event_alarm=np.flatnonzero(a[lo:hi]); post_alarm=np.flatnonzero(a[hi:ghi])
    hit=lo+int(event_alarm[0]) if len(event_alarm) else None
    post_hit=hi+int(post_alarm[0]) if len(post_alarm) else None
    alarm_ix=np.flatnonzero(a)
    if len(alarm_ix):
        breaks=np.flatnonzero(np.diff(tn[alarm_ix])>gap_ns)+1
        groups=np.split(alarm_ix,breaks)
        ep_start=np.fromiter((tn[g[0]] for g in groups),dtype=np.int64)
        ep_end=np.fromiter((tn[g[-1]] for g in groups),dtype=np.int64)
        matching=int(np.sum((ep_end>=start_ns)&(ep_start<guard_ns)))
        preexisting=bool(np.any((ep_start<start_ns)&(ep_end>=start_ns-gap_ns)))
    else:
        matching=0; preexisting=False
    clean_a=np.zeros(len(t),bool) if clean_alarm is None else np.asarray(clean_alarm,bool)
    bg_in=bool(np.any(clean_a[lo:hi]))
    bg_post=bool(np.any(clean_a[hi:ghi]))
    delay=(t[hit]-start).total_seconds() if hit is not None else np.nan
    post_delay=(t[post_hit]-end).total_seconds() if post_hit is not None else np.nan
    clear=np.nan
    if hit is not None or post_hit is not None or preexisting:
        clear_ix=np.flatnonzero(~a[hi:])
        if len(clear_ix): clear=(t[hi+int(clear_ix[0])]-pd.Timestamp(end)).total_seconds()
    n_event_samples=hi-lo
    event_fraction=float(np.sum(a[lo:hi])/n_event_samples) if n_event_samples else np.nan
    return dict(detected_in_event=hit is not None,detected_post_event=post_hit is not None,
                post_only=hit is None and post_hit is not None,missed=hit is None and post_hit is None,
                alarm_preexisting=preexisting,background_detected_in_event=bg_in,background_detected_post_event=bg_post,
                matching_alarm_episode_count=matching,event_alarm_fraction=event_fraction,
                excess_in_event=(float(hit is not None)-float(bg_in)),detection_delay_s=delay,post_detection_delay_s=post_delay,
                alarm_clear_delay_s=clear)

def event_free_mask(times,manifests):
    keep=np.ones(len(times),bool); t=pd.DatetimeIndex(times)
    for e in manifests:
        if pd.isna(e.get('start_timestamp',pd.NaT)) or pd.isna(e.get('end_timestamp',pd.NaT)): continue
        end=pd.Timestamp(e['end_timestamp'])+pd.Timedelta(seconds=GUARD_S)
        keep &= ~((t>=pd.Timestamp(e['start_timestamp']))&(t<end))
    return keep

def clean_exposure_mask(times,good,warmup_s=WARMUP_S):
    """Good observed clean samples after elapsed warm-up; no injection plans censor clean data."""
    t=pd.DatetimeIndex(times)
    return np.asarray(good,bool)&(t>=t[0]+pd.Timedelta(seconds=warmup_s))

def false_alarm_rate(episode_count,eligible_hours):
    """Return NaN for no eligible exposure; never encode an undefined rate as zero."""
    if eligible_hours<0 or episode_count<0: raise ValueError('Exposure and episode counts must be nonnegative.')
    return float(episode_count/eligible_hours) if eligible_hours>0 else np.nan

def unweighted_stratum_detection_mean(summary):
    event_rows=summary[summary.kind!='clean']
    means=event_rows.groupby('family').detect_rate.mean()
    return means.to_dict()

def select_adaptive_settings(fa,training_events,training_folds,held_out_fold,cfgs,fa_budget=FA_BUDGET):
    """Select only from explicit training folds; reject accidental held-out overlap."""
    training_folds=set(training_folds)
    if held_out_fold in training_folds: raise ValueError('Held-out fold appears in training folds.')
    tf=fa[fa.fold.isin(training_folds)]
    te=training_events[training_events.fold.isin(training_folds)]
    if len(tf) and not set(tf.fold).issubset(training_folds): raise AssertionError('False-alarm training leakage.')
    if len(te) and not set(te.fold).issubset(training_folds): raise AssertionError('Event-score training leakage.')
    choices={}
    diagnostics=[]
    for fam in legacy.ADAPTIVE:
        candidates=[c['setting'] for c in cfgs if c['family']==fam]
        f=tf[tf.family==fam]
        rate=(f.groupby('setting').alarm_episodes.sum()/f.groupby('setting').eligible_clean_hours.sum()).reindex(candidates)
        e=te[(te.family==fam)&~te.kind.isin(['rail','permanent'])]
        score=e.groupby('setting').excess_in_event.mean().reindex(candidates)
        acceptable=[n for n in candidates if pd.notna(rate[n]) and np.isfinite(rate[n]) and rate[n]<=fa_budget]
        fallback=not bool(acceptable)
        chosen=max(acceptable,key=lambda n:(score[n] if pd.notna(score[n]) else -1,-rate[n])) if acceptable else min(candidates,key=lambda n:(rate[n] if pd.notna(rate[n]) else np.inf,n))
        choices[fam]=chosen
        diagnostics.append(dict(held_out_fold=held_out_fold,training_folds='|'.join(sorted(training_folds)),family=fam,chosen=chosen,
            training_fa_per_h=rate[chosen],training_excess_in_event_rate=score[chosen],fallback_no_setting_meets_budget=fallback,
            training_eligible_clean_hours=float(f[ f.setting==chosen ].eligible_clean_hours.sum()),training_alarm_episodes=int(f[f.setting==chosen].alarm_episodes.sum()),
            heldout_data_used_for_selection=False))
    return choices,diagnostics

def evaluate():
    OUT.mkdir(parents=True,exist_ok=True)
    sessions=[]
    for f in FILES:
        if not f.exists(): raise FileNotFoundError(f'Benchmark input missing: {f}')
        sessions.extend(load_sessions(f))
    if not sessions: raise RuntimeError('No sessions meet the elapsed-time and valid-monitoring eligibility rules.')
    folds=fold_split([s['fold'] for s in sessions])
    if len(folds)<2: raise RuntimeError('Leave-one-fold-out selection requires at least two eligible recording-day folds.')
    cfgs=legacy.CONFIGS; specs=legacy.EVENTS
    clean_run={}; fa_rows=[]; cache={}; selection_rows=[]; selection_event_rows=[]
    event_rows=[]; manifest_rows=[]; selected=[]
    # Clean exposure is the full valid post-warm-up clean stream. Event plans
    # never censor the unmodified clean stream, including excluded plans.
    for s in sessions:
        exposure=clean_exposure_mask(s['t'],s['good'])
        clean_run[s['key']]={}
        hours=monitoring_hours(s['t'],exposure,MAX_GAP_S)
        for cfg in cfgs:
            alarms=legacy.detect(s['bio'],s['good'],cfg['method'],cfg['params'])&exposure
            clean_run[s['key']][cfg['setting']]=alarms
            eps=alarm_episodes(s['t'],alarms,MAX_GAP_S)
            alarm_hours=monitoring_hours(s['t'],alarms,MAX_GAP_S)
            fa_rows.append(dict(session=s['key'],fold=s['fold'],source=s['source'],day=s['day'],family=cfg['family'],setting=cfg['setting'],
                alarm_episodes=len(eps),eligible_clean_hours=hours,valid_monitoring_hours=hours,valid_event_free_hours=hours,
                fa_per_h=false_alarm_rate(len(eps),hours),alarm_time_fraction=(alarm_hours/hours if hours>0 else np.nan),
                usable_hours_before_event_exclusion=s['valid_hours'],clean_exposure_rule='good samples at/after 1800s; valid adjacent intervals <=10s; no synthetic-plan censoring'))

    def event_scores_for_session(s,scale,outer_held_fold):
        cache_key=(s['key'],float(scale) if np.isfinite(scale) else None)
        if cache_key in cache:
            cached_rows,cached_plans=cache[cache_key]
            return [dict(r,outer_held_out_fold=outer_held_fold) for r in cached_rows],cached_plans
        after=s['t']>=s['t'][0]+pd.Timedelta(seconds=WARMUP_S)
        rows=[]; plans_for_manifest=[]
        for kind,mag,dur in specs:
            y,plans=inject_elapsed(s,scale,kind,mag,dur)
            plans_for_manifest.extend(plans)
            valid_plans=[p for p in plans if p.get('status')=='planned']
            if not valid_plans: continue
            inj_good=quality_gate(y,s['lo'],s['n_sat'])
            for cfg in cfgs:
                alarms=legacy.detect(y,inj_good,cfg['method'],cfg['params'])&after
                for p in valid_plans:
                    score=score_instance(s['t'],alarms,p['start_timestamp'],p['end_timestamp'],clean_run[s['key']][cfg['setting']])
                    rows.append(dict(outer_held_out_fold=outer_held_fold,session=s['key'],fold=s['fold'],source=s['source'],day=s['day'],family=cfg['family'],setting=cfg['setting'],kind=kind,mag_sd=mag,requested_duration_s=p['requested_duration_s'],actual_duration_s=p['actual_duration_s'],event_start=p['start_timestamp'],event_end=p['end_timestamp'],event_samples=p['observed_samples'],event_status=p['status'],injection_scale_adc=scale,**score))
        cache[cache_key]=(rows,plans_for_manifest)
        return [dict(r,outer_held_out_fold=outer_held_fold) for r in rows],plans_for_manifest

    # For each outer fold, training and held-out injections use the identical
    # training-only pooled calibration rule.
    for held,train in folds:
        train_sessions=[s for s in sessions if s['fold'] in train]
        heldout_sessions=[s for s in sessions if s['fold']==held]
        training_scale=pooled_training_scale(train_sessions)
        calibration_observations=sum(int(np.sum(s['good']&(s['t']<s['t'][0]+pd.Timedelta(seconds=WARMUP_S)))) for s in train_sessions)
        fold_training_rows=[]
        for s in train_sessions:
            rows,_=event_scores_for_session(s,training_scale,held)
            fold_training_rows.extend(rows)
        selection_event_rows.extend(fold_training_rows)
        choices,diagnostics=select_adaptive_settings(pd.DataFrame(fa_rows),pd.DataFrame(fold_training_rows),train,held,cfgs,FA_BUDGET)
        for r in diagnostics:
            r['training_scale_adc']=training_scale
            r['training_calibration_observations']=calibration_observations
            selection_rows.append(r)
        choices.update({m:m for m in legacy.FIXED})
        for family,setting in choices.items():
            for s in heldout_sessions: selected.append((held,family,setting,s['key']))
        for s in heldout_sessions:
            rows,plans=event_scores_for_session(s,training_scale,held)
            event_rows.extend(rows)
            manifest_rows.extend([dict(outer_held_out_fold=held,training_scale_adc=training_scale,**p) for p in plans])
    ev=pd.DataFrame(event_rows); fa=pd.DataFrame(fa_rows); manifest=pd.DataFrame(manifest_rows)
    selection_ev=pd.DataFrame(selection_event_rows)
    folds_df=pd.DataFrame(selection_rows)
    # Output all raw event scores; selected held-out estimates are marked and
    # summarized separately so adaptive settings do not leak held-out data.
    chosen_map={(r['held_out_fold'],r['family']):r['chosen'] for r in selection_rows}
    ev['selected_for_heldout_fold']=[r.setting==chosen_map.get((r.fold,r.family),r.family) for r in ev.itertuples()]
    ev.to_csv(OUT/'bench_events.csv',index=False); fa.to_csv(OUT/'bench_fa.csv',index=False)
    selection_ev.to_csv(OUT/'bench_selection_events.csv',index=False)
    manifest.to_csv(OUT/'bench_event_manifest.csv',index=False)
    folds_df=pd.DataFrame(selection_rows); folds_df.to_csv(OUT/'bench_folds.csv',index=False)
    # Summary uses selected held-out configuration for adaptive families; fixed
    # detectors use their unchanged configuration.
    selected_ev=ev[ev.selected_for_heldout_fold].copy()
    selected_fa=[]
    for row in selected:
        held,fam,setting,key=row
        z=fa[(fa.session==key)&(fa.setting==setting)]
        if not z.empty: selected_fa.append(z)
    selected_fa=pd.concat(selected_fa,ignore_index=True) if selected_fa else fa.iloc[:0]
    summary=[]
    for fam in legacy.FIXED+legacy.ADAPTIVE:
        sub=selected_ev[selected_ev.family==fam]
        fg=selected_fa[selected_fa.family==fam]
        hours=float(fg.valid_event_free_hours.sum()) if len(fg) else 0
        episodes=int(fg.alarm_episodes.sum()) if len(fg) else 0
        fa_rate=episodes/hours if hours>0 else np.nan
        for (kind,mag),g in sub.groupby(['kind','mag_sd']):
            delays=g.loc[g.detected_in_event,'detection_delay_s'].dropna()
            summary.append(dict(family=fam,kind=kind,mag_sd=mag,n_events=len(g),n_detected_in_event=int(g.detected_in_event.sum()),n_post_only=int(g.post_only.sum()),n_missed=int(g.missed.sum()),n_alarm_preexisting=int(g.alarm_preexisting.sum()),detect_rate=float(g.detected_in_event.mean()),background_in_event_rate=float(g.background_detected_in_event.mean()),excess_in_event=float(g.excess_in_event.mean()),post_only_rate=float(g.post_only.mean()),median_detection_delay_s=float(delays.median()) if len(delays) else np.nan,p90_detection_delay_s=float(delays.quantile(.9)) if len(delays) else np.nan,median_alarm_clear_delay_s=float(g.alarm_clear_delay_s.dropna().median()) if g.alarm_clear_delay_s.notna().any() else np.nan,mean_alerted_fraction=float(g.event_alarm_fraction.mean()),alarm_episodes=episodes,valid_monitoring_hours=hours,fa_per_h=fa_rate))
        summary.append(dict(family=fam,kind='clean',mag_sd=0,n_events=0,n_detected_in_event=0,n_post_only=0,n_missed=0,n_alarm_preexisting=0,detect_rate=np.nan,post_only_rate=np.nan,median_detection_delay_s=np.nan,p90_detection_delay_s=np.nan,median_alarm_clear_delay_s=np.nan,mean_alerted_fraction=np.nan,alarm_episodes=episodes,valid_monitoring_hours=hours,fa_per_h=fa_rate))
    summ=pd.DataFrame(summary); summ.to_csv(OUT/'bench_summary.csv',index=False)
    # Memory remains algorithmic estimate; no execution timing is claimed.
    cost=[]
    state_extra={'baseline':8,'freeze':12,'winsor':8,'cusum':40,'ph':40,'stable':520}
    for cfg in cfgs:
        cost.append(dict(family=cfg['family'],setting=cfg['setting'],baseline_buffer_bytes=legacy.BASE_N*4,additional_state_bytes=state_extra[cfg['method']],logical_state_bytes=legacy.BASE_N*4+state_extra[cfg['method']],theoretical_ops_per_sample='not measured; inherited detector implementation',python_runtime='not measured',firmware_runtime='not measured',cost_basis='logical estimate only; includes 64-bit recent window for stable; no ESP32 timing claim'))
    pd.DataFrame(cost).to_csv(OUT/'bench_cost.csv',index=False)
    # Figures: detection rate by event and FA rate vs event rate.
    det=summ[summ.kind!='clean']; fig,ax=plt.subplots(figsize=(12,5))
    for fam,g in det.groupby('family'):
        ax.plot(g.kind+' '+g.mag_sd.astype(str),g.detect_rate,marker='o',label=fam)
    ax.set_ylabel('In-event detection rate'); ax.set_xlabel('Synthetic event type and magnitude (SD)'); ax.tick_params(axis='x',rotation=65); ax.legend(ncol=3); fig.tight_layout(); fig.savefig(OUT/'bench_detection.png',dpi=140); plt.close(fig)
    clean=summ[summ.kind=='clean']; avg=unweighted_stratum_detection_mean(summ); fig,ax=plt.subplots(figsize=(7,5))
    for r in clean.itertuples(): ax.scatter(r.fa_per_h,avg.get(r.family,np.nan),label=r.family); ax.annotate(r.family,(r.fa_per_h,avg.get(r.family,np.nan)),fontsize=7)
    ax.axvline(FA_BUDGET,color='k',ls=':'); ax.set_xlabel('False-alarm episodes per valid event-free hour'); ax.set_ylabel('Mean in-event detection rate'); ax.set_title('Synthetic benchmark trade-off'); fig.tight_layout(); fig.savefig(OUT/'bench_tradeoff.png',dpi=140); plt.close(fig)
    try: commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    except Exception: commit='unavailable'
    meta=dict(protocol_version='corrected_clean_exposure_pooled_scale_v1',output_directory=str(OUT.relative_to(ROOT)),code_commit=commit,
        benchmark_runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_files=[str(p.relative_to(ROOT)) for p in FILES],duplicate_rule='timestamp sorted; numeric median; leads-off and n_sat maximum; categorical first',
        max_gap_s=MAX_GAP_S,large_gaps='split sessions when inter-row gap >10s; no interpolation',timestamp='naive wall-clock; no timezone inferred',
        clean_exposure_rule='All quality-gate-good observed samples at or after 1800 elapsed seconds from session start. Count elapsed exposure only across adjacent eligible samples when 0 < gap <= 10 seconds. Synthetic event plans do not censor the unmodified clean stream.',
        zero_exposure_rule='False-alarm episodes per hour is NaN when eligible_clean_hours is zero; zero episodes with zero exposure is not reported as zero rate.',
        duration_units=dict(SKIP_S='1800 elapsed seconds',MIN_GOOD_H='elapsed valid hours',BASE_N='1800 accepted observations',MIN_N='200 accepted observations',PERSIST='10 consecutive accepted observations',RESET_S='900 deviation observations in legacy code',stable_T='600/900/1800 observations',stable_W='60 observations',EVENT_LEAD_S='elapsed seconds',EVENT_SPACING_S='elapsed seconds',GUARD_S='elapsed seconds',EVENTS='elapsed seconds; permanent through final observed sample'),
        warmup='1800 elapsed seconds from session start; detections excluded before this instant',baseline_window='1800 accepted observations',min_baseline='200 accepted observations',persistence='10 consecutive accepted observations',reset='legacy counter >900 observations while detector deviation state persists',stable_W='60 observations',stable_T='600/900/1800 observations',
        gate=dict(contact='lo_plus OR lo_minus',rail_hi='average >=4090 OR n_sat >=5 where logged',rail_lo='average <=50',flat='sample SD of last 60 observed values <2',jump='absolute previous observed step >1200'),
        event_lead_s=EVENT_LEAD_S,event_spacing_s=EVENT_SPACING_S,guard_s=GUARD_S,min_good_h=MIN_GOOD_H,fa_budget_per_h=FA_BUDGET,seed=SEED,
        fold='source file + session start date; all sessions on same source/date held together',
        adaptive_selection_protocol='For each held-out fold, compute the median of positive finite within-session robust warm-up scales from training folds only. Use that same pooled scale for all training-fold event injections and held-out injections. Select settings on training-fold clean FA episodes/hour, then mean excess in-event detection for non-rail, non-permanent synthetic events; if none meet the FA budget, select the lowest-rate setting. Fixed methods retain their settings.',
        detector_configs=cfgs,detector_input='observed samples only; no missing bins synthesized; gaps >10 seconds split sessions; within-session windows count observations',
        alarm_episode='alarm samples no more than 10 timestamp seconds apart are merged',injection='elapsed intervals, transient end exclusive; non-rail events reaching ADC limits are excluded and listed in manifest',
        score_independence='Event score rows are repeated evaluations of synthetic event instances across configurations; they are not independent events.',
        eligible_sessions=len(sessions),folds=sorted({s['fold'] for s in sessions}),session_count=len(sessions),event_rows=len(ev),selection_event_rows=len(selection_ev),fa_rows=len(fa))
    (OUT/'bench_config.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    if not len(folds_df) or folds_df.held_out_fold.nunique()!=len(folds): raise AssertionError('Empty or missing held-out fold results.')
    if len(ev) and not ev.detected_in_event.isin([True,False]).all(): raise AssertionError('Invalid event detection labels.')
    if len(ev) and not (ev.detected_in_event.astype(int)+ev.post_only.astype(int)+ev.missed.astype(int)==1).all(): raise AssertionError('Event outcome categories do not partition event instances.')
    if len(fa) and ((fa.eligible_clean_hours<0).any() or (fa.alarm_episodes<0).any()): raise AssertionError('Negative clean monitoring exposure or alarm count.')
    if len(fa) and ((fa.eligible_clean_hours==0)&fa.fa_per_h.notna()).any(): raise AssertionError('Zero-hour false-alarm rate must remain undefined.')
    if len(fa) and ((fa.eligible_clean_hours>0)&fa.fa_per_h.isna()).any(): raise AssertionError('Positive exposure must have a defined false-alarm rate.')
    if len(summ) and ((summ.detect_rate.dropna()<0).any() or (summ.detect_rate.dropna()>1).any()): raise AssertionError('Detection rate outside [0,1].')
    planned=int((manifest.status=='planned').sum()) if len(manifest) else 0
    losses=manifest.status.value_counts().to_dict() if len(manifest) else {}
    qa=f'''# Corrected benchmark validation\n\n- Eligible sessions: {len(sessions)}; held-out folds: {len(folds)}. Fold keys group all sessions by source file and start date.\n- Event scores: {len(ev)} across 23 configurations; these are repeated evaluations of synthetic instances, not independent events. Planned held-out event-manifest rows: {planned}; status counts: `{losses}`.\n- Clean exposure is every quality-gate-good observed sample at/after the 1800s warm-up; elapsed exposure sums adjacent eligible intervals only for 0 < gap <= {MAX_GAP_S}s. Synthetic plans, including excluded plans, do not censor clean data.\n- Training and held-out event injections use the same pooled training-only scale within each outer fold. Selection event scores are saved in `bench_selection_events.csv`; selected held-out scores are in `bench_events.csv`.\n- Zero-hour FA rates are NaN; nonzero-hour rates equal alarm episodes divided by eligible clean monitoring hours.\n- Event outcomes partition into in-event, post-only, or missed. Detection rates are within [0,1]. No test-set data are used in fold selection.\n- Detector windows/counters retain observation-count units; timestamp event windows, warm-up and exposure calculations retain elapsed-time units. No ESP32-S3 runtime or energy is measured.\n'''
    (OUT/'bench_validation.md').write_text(qa,encoding='utf-8')
    print(f"sessions={len(sessions)} folds={len(folds)} event_rows={len(ev)} fa_rows={len(fa)}")
    print(summ.to_string(index=False))
    return summ,ev,fa,folds_df

def main(): evaluate()
if __name__=='__main__': main()
