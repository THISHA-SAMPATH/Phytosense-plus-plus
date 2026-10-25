import numpy as np
import pandas as pd
import pytest

from analysis import benchmark as legacy
from analysis.benchmark_revised import (
    clean_exposure_mask,
    false_alarm_rate,
    monitoring_hours,
    select_adaptive_settings,
    unweighted_stratum_detection_mean,
)


def test_excluded_injection_does_not_censor_clean_samples_near_interval():
    t = pd.date_range('2026-01-01', periods=8, freq='1s')
    good = np.ones(len(t), dtype=bool)
    excluded_plan = {
        'status': 'excluded_adc_limit',
        'start_timestamp': t[2],
        'end_timestamp': t[5],
    }
    # Clean exposure is deliberately defined without an injection manifest.
    mask = clean_exposure_mask(t, good, warmup_s=0)
    assert mask.tolist() == [True] * len(t)
    assert excluded_plan['status'].startswith('excluded_')


def test_clean_exposure_hours_use_only_adjacent_valid_intervals():
    t = pd.to_datetime([
        '2026-01-01 00:00:00',
        '2026-01-01 00:00:01',
        '2026-01-01 00:00:20',
        '2026-01-01 00:00:21',
    ])
    mask = clean_exposure_mask(t, [True] * 4, warmup_s=0)
    assert monitoring_hours(t, mask, max_gap_s=10) == pytest.approx(2 / 3600)


def test_zero_clean_exposure_has_undefined_rate_not_zero():
    assert np.isnan(false_alarm_rate(0, 0))
    assert false_alarm_rate(0, 0.5) == 0
    assert false_alarm_rate(2, 0.5) == 4


def test_adaptive_selection_uses_training_folds_and_rejects_heldout_membership():
    cfgs = [
        {'family': family, 'setting': f'{family}-{setting}'}
        for family in legacy.ADAPTIVE
        for setting in ('a', 'b')
    ]
    fa_rows = []
    event_rows = []
    for family in legacy.ADAPTIVE:
        for setting in ('a', 'b'):
            fa_rows.append(dict(fold='train', family=family, setting=f'{family}-{setting}',
                                alarm_episodes=0, eligible_clean_hours=1.0))
            event_rows.append(dict(fold='train', family=family, setting=f'{family}-{setting}',
                                   kind='step', excess_in_event=0.8 if setting == 'a' else 0.2))
            # Held-out scores favor b strongly; they must not change train choice.
            fa_rows.append(dict(fold='held', family=family, setting=f'{family}-{setting}',
                                alarm_episodes=0, eligible_clean_hours=1.0))
            event_rows.append(dict(fold='held', family=family, setting=f'{family}-{setting}',
                                   kind='step', excess_in_event=0.0 if setting == 'a' else 1.0))
    choices, diagnostics = select_adaptive_settings(
        pd.DataFrame(fa_rows), pd.DataFrame(event_rows), ['train'], 'held', cfgs, 1.0
    )
    assert choices == {family: f'{family}-a' for family in legacy.ADAPTIVE}
    assert all(row['heldout_data_used_for_selection'] is False for row in diagnostics)
    with pytest.raises(ValueError, match='Held-out fold'):
        select_adaptive_settings(pd.DataFrame(fa_rows), pd.DataFrame(event_rows),
                                 ['train', 'held'], 'held', cfgs, 1.0)


def test_detection_mean_weights_event_strata_not_repeated_event_rows():
    summary = pd.DataFrame([
        {'family': 'x', 'kind': 'few', 'detect_rate': 1.0},
        {'family': 'x', 'kind': 'many', 'detect_rate': 0.0},
        {'family': 'x', 'kind': 'clean', 'detect_rate': np.nan},
    ])
    assert unweighted_stratum_detection_mean(summary) == {'x': 0.5}
