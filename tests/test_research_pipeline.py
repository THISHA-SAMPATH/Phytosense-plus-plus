import numpy as np
import pandas as pd
from analysis.benchmark_time import coalesce_timestamps,event_mask,score_event,monitoring_hours,alarm_episodes
from analysis.real_fault_replay import episodes
from analysis.baseline_absorption import theory
from analysis.research_common import firmware_gate

def test_duplicate_timestamps_coalesced_deterministically():
    d=pd.DataFrame({'wall_clock_time':['2026-01-01T00:00:00','2026-01-01T00:00:00'],'bioelectric_raw':[1.,3.],'lo_plus':[0,1]})
    r=coalesce_timestamps(d); assert len(r)==1 and r.bioelectric_raw.iloc[0]==2 and r.lo_plus.iloc[0]==1

def test_event_duration_and_scoring_use_elapsed_time():
    t=pd.date_range('2026-01-01',periods=6,freq='2s'); m=event_mask(t,t[1],3); assert m.sum()==2
    r=score_event(t,[0,0,1,1,1,0],t[1],3,guard_s=3); assert r['detected_in_event'] and r['detection_delay_s']==2 and r['detected_post_event']

def test_gaps_reduce_valid_monitoring_hours():
    t=pd.to_datetime(['2026-01-01 00:00:00','2026-01-01 00:00:01','2026-01-01 00:01:00']); assert monitoring_hours(t,[1,1,1],10)==1/3600

def test_consecutive_alarms_merge_as_one_episode():
    t=pd.to_datetime(['2026-01-01 00:00:00','2026-01-01 00:00:01','2026-01-01 00:00:02','2026-01-01 00:00:03','2026-01-01 00:00:20']); assert len(alarm_episodes(t,[0,1,1,0,1]))==2

def test_known_rail_samples_group_with_timestamp_elapsed_duration():
    d=pd.DataFrame({'t':pd.to_datetime(['2026-01-01 00:00:00','2026-01-01 00:00:01','2026-01-01 00:00:30'])})
    e=episodes(d,np.array([1,1,1],bool),10); assert len(e)==2 and e.elapsed_s.tolist()==[1.,0.]

def test_moving_mean_threshold_theory_edge_cases():
    assert theory(100,6,1,3)==51 and theory(100,2,1,3)==0

def test_seeded_simulation_is_reproducible():
    from analysis.baseline_absorption import sim
    assert sim(50,6,1,3,5,'update',7)==sim(50,6,1,3,5,'update',7)

def test_gate_rail_flatline_jump_and_leads_off_conditions():
    d=pd.DataFrame({'bioelectric_raw':[4090.,50.,1000.,1000.,2301.], 'lo_plus':[0,0,0,0,0], 'lo_minus':[0,0,1,0,0]})
    # Separate contact/rail/jump checks from the 60-value flatline warm-up.
    assert firmware_gate(d)[:2].tolist()==['rail_hi','rail_lo']
    assert firmware_gate(d)[2]=='contact'
    flat=pd.DataFrame({'bioelectric_raw':[1000.]*60,'lo_plus':[0]*60,'lo_minus':[0]*60})
    assert firmware_gate(flat)[-1]=='flat'

def test_inadequate_data_yields_no_event_score_as_missed():
    t=pd.to_datetime(['2026-01-01 00:00:00']); r=score_event(t,[False],t[0],10,3)
    assert r['missed'] and not r['detected_in_event'] and np.isnan(r['detection_delay_s'])
