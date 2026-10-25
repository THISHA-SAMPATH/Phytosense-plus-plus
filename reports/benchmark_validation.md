# Revised benchmark validation

- Eligible sessions: 6; held-out folds: 5. Each fold key is source file plus session start date; sessions sharing a fold remain together. The selection CSV marks held-out data as unused for threshold selection.
- Event score rows: 15088; clean false-alarm rows: 138; event manifest rows: 685. Planned event rows: 656. Manifest status counts: `{'planned': 656, 'excluded_adc_limit': 24, 'excluded_insufficient_elapsed_coverage': 5}`. Exclusions are explicit (no scale, insufficient elapsed coverage, or ADC limit).
- Event outcome accounting: every scored row is exactly one of in-event detection, post-only detection, or missed event. Pre-existing alarm is an additional flag and can overlap in-event detection.
- Detection rates checked within [0,1]; event-free hours and episode counts checked nonnegative. Zero-hour false-alarm denominators remain NaN and are not presented as zero rates.
- Input gaps >10s split sessions; no bins were interpolated. All event windows and guards use timestamps. Window/persistence/reset counters retain legacy observation-count meanings and are recorded in `bench_config.json`.
- Detector settings remain from `analysis/benchmark.py`: 23 configurations across six methods. Python and ESP32-S3 execution timing are not measured.

Inspect `bench_event_manifest.csv` for every scheduled event, its requested and represented duration, affected observation span, amplitude, seed, and inclusion/exclusion reason. A missing event-kind row in the summary means no event survived the explicit eligibility/ADC rules; it must not be read as a zero detection rate.

## Run record

- Successful full-run command: `python analysis/benchmark_revised.py` (23 October 2026; approximately 5m42s wall time). The first full invocation completed detector replay but stopped during aggregation due to named-tuple dictionary indexing; the corrected invocation above completed all outputs.
- Profiling command: `python -c "import cProfile,pstats,numpy as np,pandas as pd; from analysis.benchmark_revised import score_instance; t=pd.date_range('2026-01-01',periods=20000,freq='1s'); a=np.zeros(len(t),bool); a[::37]=1; pr=cProfile.Profile(); pr.enable(); [score_instance(t,a,t[5000+i*20],t[5060+i*20]) for i in range(200)]; pr.disable(); pstats.Stats(pr).sort_stats('cumtime').print_stats(15)"`. Before the change, 200 scores took 17.128s; `alarm_episodes` consumed 16.341s, primarily pandas scalar `.iloc` calls. The same profile after the change took 0.976s (about 17.5× faster).
- Deterministic compatibility command compared the previous scoring logic with the optimized scorer on 80 seeded event cases; output: `80 deterministic cases: exact output match`.
- Tests: `python -m pytest tests/test_benchmark_revised.py tests/test_research_pipeline.py -q` and final `python -m pytest -q`; both final runs passed all 16 tests.
- Generated files are in `out/revised/`: `bench_events.csv` (4,319,322 bytes), `bench_event_manifest.csv` (169,023), `bench_fa.csv` (29,446), `bench_folds.csv` (4,177), `bench_summary.csv` (7,771), `bench_cost.csv` (4,649), `bench_config.json` (6,349), `bench_detection.png` (141,615), and `bench_tradeoff.png` (39,837). All are nonempty.

## Selected held-out results

Mean in-event detection rate is averaged across the selected event-kind/magnitude summary rows (clean rows excluded). Clean false alarms are episode counts per event-free monitoring hour.

| Method | Event scores | Mean detection rate | Clean FA episodes/hour |
|---|---:|---:|---:|
| baseline | 656 | 0.3263 | 0.0000 |
| freeze | 656 | 0.5035 | 6.0096 |
| winsor | 656 | 0.3359 | 0.0000 |
| CUSUM | 656 | 0.7240 | 4.0064 |
| Page-Hinkley | 656 | 0.7213 | 4.0064 |
| stable | 656 | 0.3657 | 0.0000 |

The generated config and manifest preserve the exact evaluation conditions, event exclusions, and detector settings. Runtime and cost CSV values do not claim embedded firmware timing; Python and ESP32-S3 execution timing remain unmeasured.
