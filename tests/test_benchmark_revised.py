import numpy as np
import pandas as pd
from analysis.benchmark_revised import fold_split,inject_elapsed,score_instance,session_labels

def make_session(seconds=4000):
    t=pd.date_range('2026-01-01',periods=seconds+1,freq='1s')
    x=2000+100*np.sin(np.arange(len(t))/7)
    return dict(key='s1',fold='source|2026-01-01',t=t,bio=x,lo=np.zeros(len(t),bool),n_sat=None)

def test_gaps_split_sessions_without_filling_missing_bins():
    t=pd.to_datetime(['2026-01-01 00:00:00','2026-01-01 00:00:01','2026-01-01 00:00:20','2026-01-01 00:00:21'])
    labels=session_labels(t,10)
    assert labels.tolist()==[0,0,1,1] and len(t)==4

def test_elapsed_event_injection_duration_and_seed_reproducibility():
    s=make_session(); y1,p1=inject_elapsed(s,10,'step',6,60,seed=13); y2,p2=inject_elapsed(s,10,'step',6,60,seed=13)
    assert np.array_equal(y1,y2) and p1==p2
    p=next(r for r in p1 if r['status']=='planned')
    assert p['requested_duration_s']==60 and p['actual_duration_s']==60 and p['observed_samples']==60
    assert (p['end_timestamp']-p['start_timestamp']).total_seconds()==60

def test_detection_latency_and_guard_only_are_distinct():
    t=pd.date_range('2026-01-01',periods=8,freq='1s'); start=t[2]; end=start+pd.Timedelta(seconds=2)
    in_event=score_instance(t,[0,0,0,1,0,0,0,0],start,end)
    assert in_event['detected_in_event'] and not in_event['post_only'] and in_event['detection_delay_s']==1
    post=score_instance(t,[0,0,0,0,0,1,0,0],start,end)
    assert not post['detected_in_event'] and post['detected_post_event'] and post['post_only'] and post['post_detection_delay_s']==1

def test_event_matching_marks_existing_alarm_episode():
    t=pd.date_range('2026-01-01',periods=8,freq='1s'); start=t[3]; end=t[5]
    r=score_instance(t,[0,1,1,1,1,0,0,0],start,end)
    assert r['alarm_preexisting'] and r['detected_in_event'] and r['matching_alarm_episode_count']==1

def test_fold_separation_keeps_all_same_day_sessions_held_together():
    folds=fold_split(['a|day1','a|day1','a|day2','b|day1'])
    held,train=folds[0]
    assert held=='a|day1' and 'a|day1' not in train and set(train)=={'a|day2','b|day1'}

def test_event_clipped_by_adc_rails_is_recorded_as_excluded():
    s=make_session(); s['bio']=s['bio'].copy(); s['bio'][2400:2460]=4088
    _,plans=inject_elapsed(s,10,'step',6,60)
    assert next(x for x in plans if x['status']!='excluded_insufficient_elapsed_coverage')['status']=='excluded_adc_limit'

def test_drift_injection_uses_elapsed_fraction():
    s=make_session(); y,plans=inject_elapsed(s,10,'drift',6,60)
    p=next(x for x in plans if x['status']=='planned'); i=int((p['start_timestamp']-s['t'][0]).total_seconds())
    assert y[i]==s['bio'][i] and y[i+59]>s['bio'][i+59]
