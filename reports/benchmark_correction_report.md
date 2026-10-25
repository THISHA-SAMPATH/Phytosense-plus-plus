# Corrected benchmark run and validation

## What changed

The prior runner passed every scheduled event plan into `event_free_mask`, regardless of status. This censored clean observations for ADC-limited and insufficient-coverage events even though excluded injections were not applied. It also selected adaptive settings from event rows injected at each training session's own robust scale, while held-out events used a pooled training-fold scale.

The corrected run writes to `out/corrected/` and leaves `out/revised/`, `out/`, paper tables, source data, and prior audit reports unchanged.

- Clean exposure is now all quality-gate-good observed samples at or after 1,800 elapsed seconds from each session start. The denominator sums elapsed intervals only between adjacent eligible observations with `0 < delta_t <= 10s`. Neither planned nor excluded synthetic event windows censor clean-stream exposure, since the clean stream has no synthetic injection.
- The false-alarm rate is total merged alarm episodes divided by eligible clean hours. If exposure is zero, the rate is `NaN`; the implementation and tests prevent zero episodes over zero hours from being represented as zero false alarms/hour.
- For every outer held-out fold, a pooled scale is calculated as the median of positive finite per-session robust scales from training-fold warm-up observations only. That same scale is used for training event injections that drive selection and the held-out event injections. The selector receives only training-fold clean FA rows and event scores. The fold CSV records its training folds, selected configuration, training exposure, calibration scale, and `heldout_data_used_for_selection=False`.
- Added `bench_selection_events.csv` so the fold-specific training objective is auditable. `bench_events.csv` remains the all-configuration held-out evaluation table. The score rows are repeated evaluations of synthetic instances across configurations, not independent event samples.

Detector algorithms and hyperparameter grids were not changed. The gate, session split, elapsed event placement, exclusions, event score categories, and selection objective (FA budget, then mean excess in-event detection excluding rail/permanent events; lowest-FA fallback) remain as documented. The revised scale protocol makes training and test injection calibration consistent.

## Corrected results

There are 6 eligible sessions grouped into 5 held-out source/date folds. The 685-row held-out manifest contains 656 planned events, 24 ADC-limit exclusions, and 5 insufficient-coverage exclusions. Each method has 656 held-out event instances; all 23 configurations evaluated per event yield 15,088 event-score rows. Training objective rows are separately recorded (59,984, repeated across outer-fold training runs).

Detection rate is computed per event-type/magnitude stratum as `n_detected_in_event / n_events`; the headline mean is an unweighted average across eight event strata. It is not a pooled independent-trial rate.

| Method | Mean detection across 8 synthetic strata | Clean alarm episodes | Eligible clean hours | Episodes/hour |
|---|---:|---:|---:|---:|
| baseline | 0.326318 | 5 | 64.42545 | 0.077609 |
| freeze | 0.503522 | 136 | 64.42545 | 2.110967 |
| winsor | 0.335892 | 9 | 64.42545 | 0.139696 |
| CUSUM | 0.620061 | 67 | 64.42545 | 1.039962 |
| Page-Hinkley | 0.507731 | 76 | 64.42545 | 1.179658 |
| stable | 0.398875 | 6 | 64.42545 | 0.093131 |

`bench_folds.csv` records the chosen settings. CUSUM used the no-setting-meets-budget fallback in one fold; the selected held-out summaries do not imply a guarantee that the 1/hour training budget is met on held-out data. Event scores and clean alarm burden are synthetic replay measurements on recorded signal streams, not biological event measurements.

## Generated outputs

All outputs are under `out/corrected/`:

- `bench_events.csv`, `bench_selection_events.csv`, `bench_event_manifest.csv`
- `bench_fa.csv`, `bench_folds.csv`, `bench_summary.csv`, `bench_cost.csv`
- `bench_config.json`, `bench_validation.md`
- `bench_detection.png`, `bench_tradeoff.png`

The manifest records protocol version `corrected_clean_exposure_pooled_scale_v1`, repository commit `313de1fe25bcfa85907e0c533428f6f6847884cc`, and runner SHA-256 `0a3c85631b9c704b8e6910bc25ac8e379ceedb365fb489df54d6e916505c4b39`. The configuration explicitly records the clean exposure rule, zero-hour behavior, fold grouping, calibration, event scoring, and repeated-score interpretation. Cost rows remain logical memory estimates; operation count, Python timing, ESP32-S3 runtime, and energy are not measured. The corrected benchmark invocation ran from 17:49:16 to final artifact write at 17:58:35 local time (about 9m19s).

## Verification

Commands run from the repository root:

```text
python -m py_compile analysis/benchmark_revised.py
python -m pytest tests/test_benchmark_corrected.py tests/test_benchmark_revised.py tests/test_research_pipeline.py -q
python analysis/benchmark_revised.py
python analysis/validate_corrected_benchmark.py
python -m py_compile analysis/validate_corrected_benchmark.py
python -m pytest -q
git diff --check
```

Results: focused tests **21 passed**; full suite **21 passed**; `python analysis/validate_corrected_benchmark.py` passed; `git diff --check` passed. Post-run assertions verified 6 sessions/5 folds, 15,088 held-out score rows, 59,984 training score rows, 138 per-session/configuration FA rows, the expected planned/excluded manifest counts, all six methods, unique event/configuration score keys, partitioned event outcomes, no training rows from their outer held-out fold, exact FA/hour arithmetic, correct zero-exposure handling, and a matching runner hash in the config. Every generated output file is nonempty. This dataset had no zero-hour sessions; the zero-hour behavior is covered by the regression test.

## Remaining limits

The five outer folds and six sessions are a small, correlated dataset; events within a session are not independent biological replicates. The rates have no confidence intervals. Report fold-level results and use paired fold-cluster resampling for exploratory uncertainty; stronger population inference requires more independent recording days/runs/plants. The data have no labeled plant-stress episodes, so synthetic injection performance cannot validate plant-stress detection. Historical ADC fields are incomplete. The cost file does not establish deployed firmware equivalence, runtime, energy, or complete memory use. No paper tables or manuscript text were edited.
