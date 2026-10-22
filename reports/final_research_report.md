# PhytoSense++ software-only research audit

## Completed

The repository audit, source data quality report, real rail episode extraction, firmware-like gate-on/off baseline replay, available-field gate ablation, moving-mean derivation and synthetic simulation sweep, timestamp-aware scoring primitives, focused automated tests, and paper claim audit are present in `reports/` and `out/revised/`.

The source log has 329,271 rows, including 13,372 duplicate timestamps. The raw rail-valued row count is 93,154; after deterministic duplicate coalescing there are 93,049 unique rail timestamps. A 10-second grouping creates 109 episodes, with the longest spanning 72,857.424 elapsed seconds. This is an operational grouping and the overall timestamp stream contains large gaps, so it is not proof of one continuous acquisition. Times have no timezone marker.

For available fields, the firmware-like replay admitted all 93,049 rail timestamps when ungated and none when gated. It rejected 36 nonrail values. Replay starts with an empty ring and uses reconstructed gates; it is not an exact recreation of historical firmware state. Its baseline centers have large deviations in both modes, and the output should not be used to claim successful recovery: reset/reboot state over long gaps is unknown and a continuous post-fault observation interval is not established.

The ablation confirms the expected direct rail behavior for logged averages: the high-rail check rejects all rail points; contact, low-rail, and jump reject none of those rail labels in this source. The flatness check also rejects many rail points because their values are flat. The nonrail rejection percentages are proxy-only; there are no complete independent good/fault labels. Full combination outputs preserve overlap. This does not justify removing checks.

The repository baseline is a rolling arithmetic mean and sample standard deviation, not median/MAD. Under a fixed full N-value buffer, fixed scale σ, and persistent shift δ, after k shifted values replace old values, the baseline is μ+kδ/N and residual is |δ|(1−k/N). Alarm threshold crossing at or below zσ is at the first integer k≥N(1−zσ/|δ|); strict below uses floor(N(1−zσ/|δ|))+1. Adaptive SD, persistence, gates, and resets change actual alarm behavior. Simulations are software illustrations only.

## Incomplete and blocked deliverables

The legacy detector benchmark was not regenerated. Its implementation treats skip, baseline, event duration, and guard values as row counts; it drops gaps before replay; it scores guard-only detections as hits; and it reports index latency. A corrected benchmark must use missing-bin-aware state handling across all six methods, preserve day/session grouping, reselect adaptive thresholds without held-out leakage, and rerun expensive event simulations. Revised timestamp-aware primitive functions and unit tests exist, but this is not a substitute for the benchmark. Therefore no revised `bench_summary.csv`, `bench_events.csv`, `bench_folds.csv`, `bench_fa.csv`, or `bench_cost.csv` is claimed complete. Existing `out/` and paper outputs remain unchanged.

The real-fault replay does not yet implement predeclared baseline-only and detector-state recovery criteria with tolerance sensitivity. Post-fault recovery claims remain unsupported. Gate ablation is limited by the absence of per-cycle ADC min/max/saturation counts in the principal fault CSV. The complete firmware equivalence, integration tests, configuration snapshot beside every result, comprehensive figures, and paper quantitative table update are also incomplete.

## Reproducibility

Run the implemented suite from repository root with:

```powershell
python analysis/run_revised_audit.py
```

Focused test command: `python -m pytest tests/test_research_pipeline.py -q` (latest result: 9 passed). See `audit_report.md`, `real_fault_analysis.md`, `gate_ablation.md`, `baseline_absorption.md`, and `claim_audit.md` for assumptions and claim-level limits.
