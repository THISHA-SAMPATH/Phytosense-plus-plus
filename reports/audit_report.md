# Repository and reproducibility audit

- Revision: `e2c19807cb82f00a39c3ecdc1873f699e46fa1e5`
- Python: `3.14.2`
- Dependencies: {'numpy': '2.4.6', 'pandas': '2.3.3', 'matplotlib': '3.10.8', 'pytest': '9.1.1'}
- Git status at audit start: branch `main`, one pre-existing modified file `analysis/reliability_report.py`; retained untouched.
- Original outputs in `out/`: `bench_summary.csv`, `bench_folds.csv`, `bench_cost.csv`, `bench_events.csv`, `bench_fa.csv`, `reliability_report.txt`; timestamps/provenance not embedded, so source/config revision for those generated files is unknown. Frozen paper outputs also exist under `paper/data/`.
- Benchmark original configuration: GAP_S=10, SKIP_S=1800 rows (despite `_S` naming), MIN_GOOD_H=1, BASE_N=1800 sample rows, MIN_N=200 sample rows, Z=3, persistence=10 good rows, reset=900 rows for most alternatives, guard=120 rows; events injected at row indices, not true elapsed time.
- Duplicate policy in revised work: sort chronologically, coalesce same timestamp using median numeric values and max leads-off/saturation counts. Gaps remain gaps; no interpolation.
- Full field-level quality summary is in `out/revised/data_quality.csv`.

## Input files

### `preflight_test.csv`

- Rows: 244; unique timestamps: 244; duplicate rows: 0.
- Timestamp range: 2026-10-17 12:19:48.999000 to 2026-10-17 12:23:52.994000 (timezone absent; interpreted as naive wall clock).
- Gaps >10 s: 0; maximum gap: 2.014 s.
- Rail-valued average readings: high=0, low=0; invalid bioelectric values=0.
- Columns: `wall_clock_time, uptime_ms, bioelectric_raw, lo_plus, lo_minus, soil_raw, temp_c, humidity_pct, pressure_hpa, reading_status, bio_min, bio_max, n_sat, z_score, gate_reason, event`.

### `preflight_90min.csv`

- Rows: 9,243; unique timestamps: 9,243; duplicate rows: 0.
- Timestamp range: 2026-10-17 13:06:36.465000 to 2026-10-17 15:41:11.245000 (timezone absent; interpreted as naive wall clock).
- Gaps >10 s: 0; maximum gap: 2.995 s.
- Rail-valued average readings: high=0, low=0; invalid bioelectric values=0.
- Columns: `wall_clock_time, uptime_ms, bioelectric_raw, lo_plus, lo_minus, soil_raw, temp_c, humidity_pct, pressure_hpa, reading_status, bio_min, bio_max, n_sat, z_score, gate_reason, event`.

### `trial_v7.csv`

- Rows: 6,364; unique timestamps: 6,364; duplicate rows: 0.
- Timestamp range: 2026-10-17 22:21:16.588000 to 2026-10-18 01:01:40.343000 (timezone absent; interpreted as naive wall clock).
- Gaps >10 s: 4; maximum gap: 1,739.076 s.
- Rail-valued average readings: high=0, low=0; invalid bioelectric values=0.
- Columns: `wall_clock_time, uptime_ms, bioelectric_raw, lo_plus, lo_minus, soil_raw, temp_c, humidity_pct, pressure_hpa, reading_status, bio_min, bio_max, n_sat, z_score, gate_reason, event`.

### `phytosense_trial_log.csv`

- Rows: 329,271; unique timestamps: 315,899; duplicate rows: 13,372.
- Timestamp range: 2026-09-12 16:19:34 to 2026-10-19 00:14:30.946000 (timezone absent; interpreted as naive wall clock).
- Gaps >10 s: 17; maximum gap: 2,455,669.577 s.
- Rail-valued average readings: high=93,049, low=0; invalid bioelectric values=0.
- Columns: `wall_clock_time, uptime_ms, bioelectric_raw, lo_plus, lo_minus, soil_raw, temp_c, humidity_pct, pressure_hpa, reading_status`.

## Firmware and evidence limits

`firmware/src/main.cpp` reads each cycle as 20 ADC samples, stores their average, tracks min/max/count at saturation, then applies five gate checks: leads-off/contact, high rail, low rail, 60-second flatline SD, and one-sample jump. Gate priority is contact > high rail > low rail > flat > jump. The ring baseline stores 1800 good values, computes arithmetic mean and sample SD by rescanning, becomes scoreable after 200 values, scores before update, and emits deviation after 10 consecutive |z|>3 good cycles. 600 consecutive bad cycles clear only baseline count/head.

The main historical CSV does not have `bio_min`, `bio_max`, or `n_sat`; only later log schemas do. Consequently exact high-rail detection and reconstruction of raw oversampling are not available for the full rail log. Timestamp strings have no timezone suffix; UTC/local cannot be inferred. Nominal interval is approximately 1 second in some sessions, but the overall data contain duplicates, irregular intervals, and multi-day gaps. Existing benchmark treats `SKIP_S`, `BASE_N`, and events as rows despite names/comments implying seconds. Its event score includes the guard as a hit and reports index latency; this requires repair before paper claims rely on it.
