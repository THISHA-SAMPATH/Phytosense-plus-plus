"""Timestamp-aware evaluation primitives used to audit the legacy benchmark."""
import numpy as np
import pandas as pd

def quality_gate(x,lo,n_sat=None):
    """Firmware gate reasons in priority order; n_sat is optional for older logs."""
    x=np.asarray(x,float); lo=np.asarray(lo,bool); sat=None if n_sat is None else np.asarray(n_sat,float)
    reasons=np.full(len(x),'none',object); history=[]; prev=None
    for i,v in enumerate(x):
        history.append(v)
        if len(history)>60: history.pop(0)
        if not np.isfinite(v): r='invalid'
        elif lo[i]: r='contact'
        elif v>=4090 or (sat is not None and sat[i]>=5): r='rail_hi'
        elif v<=50: r='rail_lo'
        elif len(history)==60 and np.std(history,ddof=1)<2: r='flat'
        elif prev is not None and abs(v-prev)>1200: r='jump'
        else: r='none'
        reasons[i]=r; prev=v
    return reasons=='none'

def coalesce_timestamps(frame, timestamp='wall_clock_time'):
    d=frame.copy(); d['_t']=pd.to_datetime(d[timestamp],format='mixed',errors='coerce'); d=d.dropna(subset=['_t']).sort_values('_t',kind='stable')
    agg={c:'median' for c in d.select_dtypes(include='number').columns}
    for c in ('lo_plus','lo_minus','n_sat'):
        if c in d: agg[c]='max'
    for c in d.select_dtypes(include='object').columns:
        if c!=timestamp: agg[c]='first'
    return d.groupby('_t',as_index=False,sort=True).agg(agg).rename(columns={'_t':'timestamp'})

def event_mask(times, start, duration_s):
    t=pd.to_datetime(times); start=pd.Timestamp(start); end=start+pd.Timedelta(seconds=float(duration_s))
    return (t>=start)&(t<end)

def score_event(times, alarm, start, duration_s, guard_s=120):
    t=pd.to_datetime(times); a=np.asarray(alarm,bool); start=pd.Timestamp(start); end=start+pd.Timedelta(seconds=float(duration_s)); guard=end+pd.Timedelta(seconds=float(guard_s))
    inside=np.flatnonzero((t>=start)&(t<end)&a); after=np.flatnonzero((t>=end)&(t<guard)&a)
    prior=bool(np.any(a[t<start])); hit=inside[0] if len(inside) else None; post=after[0] if len(after) else None
    return dict(detected_in_event=hit is not None,detected_post_event=post is not None,missed=hit is None and post is None,alarm_preexisting=prior,detection_delay_s=((t.iloc[hit] if hasattr(t,'iloc') else t[hit])-start).total_seconds() if hit is not None else np.nan,post_detection_delay_s=((t.iloc[post] if hasattr(t,'iloc') else t[post])-end).total_seconds() if post is not None else np.nan)

def monitoring_hours(times, valid, max_gap_s=10):
    t=pd.Series(pd.to_datetime(times)); v=np.asarray(valid,bool); dt=t.diff().dt.total_seconds().fillna(0).to_numpy(); prev=np.r_[False,v[:-1]]; eligible=(dt>0)&(dt<=max_gap_s)&v&prev
    return float(dt[eligible].sum()/3600)

def alarm_episodes(times, alarm, max_clear_gap_s=10):
    t=pd.Series(pd.to_datetime(times)); a=np.asarray(alarm,bool); ix=np.flatnonzero(a)
    if not len(ix): return []
    groups=[]; cur=[ix[0]]
    for i in ix[1:]:
        if (t.iloc[i]-t.iloc[cur[-1]]).total_seconds()<=max_clear_gap_s:cur.append(i)
        else:groups.append(cur);cur=[i]
    groups.append(cur)
    return [(t.iloc[g[0]],t.iloc[g[-1]]) for g in groups]

def elapsed_window_mask(times,start,duration_s): return event_mask(times,start,duration_s)
