# Final scientific audit of the revised benchmark

## Verdict

The generated benchmark is a completed software replay of **synthetic injected events on six eligible recorded sessions**. It is not evidence that the detectors identify plant stress. The score tables and configuration are traceable, and the held-out folds keep the same source/date group together. However, the headline clean false-alarm rates and the adaptive-method selection are **not submission-ready**: the clean exposure mask removes some windows whose injections were excluded, and the adaptive training scores use a different injection calibration from held-out scoring. These are evaluation defects, not detector implementation defects. No detector was rerun or changed for this audit.

## Trace of headline metrics

`bench_events.csv` contains 15,088 scored rows: 656 planned event instances evaluated at each of 23 detector configurations (3 fixed configurations, 7 CUSUM, 7 Page-Hinkley, and 6 stable). Thus 15,088 is **not** an independent-event sample size. The same synthetic event/time window is evaluated repeatedly under detector configurations. The 656 event instances are themselves clustered within only six sessions and five folds; repeated events within a session are not independent biological replicates.

Each method's selected held-out summary has eight event strata: step, three sustained magnitudes, drift, spike, rail, and permanent. Its reported mean detection rate is the **unweighted mean of those eight stratum-level rates**, where each stratum rate is `n_detected_in_event / n_events`. It is not the pooled fraction across all 656 events. The stratum event counts (87, 5, 97, 96, 94, 93, 92, 92) sum to 656. The exact means from `bench_summary.csv` are:

| Method | Equal-weight mean across 8 event strata | Clean episodes / hour in output | Verdict |
|---|---:|---:|---|
| baseline | 0.3263 | 0.0000 | Supported with limitations for synthetic in-event detection; clean rate requires corrected exposure accounting |
| freeze | 0.5035 | 6.0096 | Supported with limitations for synthetic in-event detection; clean rate requires corrected exposure accounting |
| winsor | 0.3359 | 0.0000 | Supported with limitations for synthetic in-event detection; clean rate requires corrected exposure accounting |
| CUSUM | 0.7240 | 4.0064 | Supported with limitations as selected synthetic replay output; adaptive selection and clean rate require correction |
| Page-Hinkley | 0.7213 | 4.0064 | Supported with limitations as selected synthetic replay output; adaptive selection and clean rate require correction |
| stable | 0.3657 | 0.0000 | Supported with limitations as selected synthetic replay output; adaptive selection and clean rate require correction |

The clean rate formula in the runner is `sum(alarm_episodes) / sum(valid_event_free_hours)` across the selected held-out session rows. In this output each method has 6 selected session rows, **0.998401 total hours**, and no zero-hour denominators. `bench_fa.csv` has 138 configuration/session rows; its per-session event-free hours range from 0.166384 to 0.166456 hours. The written zero-denominator behavior is correct (`NaN` when hours are zero), but it was not exercised by this dataset.

### Clean-exposure correctness defect

`analysis/benchmark_revised.py` builds `event_plans` including planned and excluded events, then passes all plans to `event_free_mask`. That function excludes each timestamp interval without checking `status`. Consequently, time windows with `excluded_adc_limit` events—where injection was reverted to the original signal—and some insufficient-coverage plans are removed from clean monitoring exposure and from alarm episode counts. Such samples are clean observations and should remain in the clean denominator. The resulting 0.998401-hour denominator and its paired episode counts therefore do not represent all eligible event-free clean monitoring. The direction and size of the rate change cannot be recovered from these summary CSVs because the clean alarm time series is not saved. This also contaminates false-alarm-budget calculations used to choose CUSUM and Page-Hinkley settings. **Verdict: unsupported as a valid clean false-alarm estimate until clean exposure and selection are recomputed.**

## Sessions, folds, and leakage

The runner sorts timestamps, coalesces duplicate timestamps, splits sessions at gaps greater than 10 seconds, applies the quality gate, and requires at least one elapsed valid monitoring hour after the 1,800-second warm-up. The six eligible sessions map to five fold keys: `phytosense_trial_log.csv|2026-09-12`, `...|2026-09-13`, `...|2026-10-12`, `...|2026-10-18`, and `preflight_90min.csv|2026-10-17`. The September 13 fold contains two sessions; all other folds contain one. The separate preflight source/date is one fold, not an independent plant-level cohort.

For each held-out fold, the other four folds are used for selection. `bench_folds.csv` records the training folds, chosen setting, calibration scale, and `heldout_data_used_for_selection=False`. Fold membership is by source filename plus session start date, so multiple sessions on the same source/date are held together. **No direct held-out-fold leakage was found in the selection grouping.** This supports the no-leakage claim with the limitation that five folds from these recordings are a small, correlated evaluation set.

There is a training/evaluation condition mismatch: adaptive settings are selected using exploratory event rows injected at each training session's own robust scale, while the final held-out events use a pooled robust scale computed only from training sessions. This is not held-out leakage, but it means tuning scores and test events are not generated under the same calibration rule. In addition, the false-alarm defect above affects the training budget and can change selected settings. **Adaptive ranking and selected-setting metrics should be treated as provisional until selection is rerun with a consistent training-only scale and correct clean exposure mask.** Fixed detector event rows are not selected by this tuning step.

The recorded selections mark the fallback path for CUSUM and Page-Hinkley in every held-out fold: no candidate met the 1 episode/hour training budget, so the lowest-rate candidate was chosen. Their reported held-out rates (4.0064/hour in the current summary) are above that budget. The stable family did have a qualifying candidate in the recorded selection, but its selection is still affected by the clean-exposure defect.

## Event dependence and uncertainty

The 15,088 rows are repeated configuration evaluations of 656 planned event instances, not 15,088 independent trials. Events reuse fixed elapsed-time offsets and magnitudes within a session; detector configurations see the same underlying source windows. Comparisons must therefore be paired by session and event identity. The current summary contains point estimates only; it does not provide confidence intervals. Event-level binomial intervals that treat all 656 events as independent would be anti-conservative.

For uncertainty supported by these data, report per-fold or per-session results and use a **paired cluster bootstrap over the five held-out fold keys**, resampling a fold as a unit and preserving all its sessions, event identities, and detector settings. For detector comparisons, bootstrap paired within-event differences in detection, excess detection, and alarm burden. With only five folds, intervals will be unstable; show fold-level values and characterize intervals as exploratory. A larger number of independent plants, runs, or acquisition days is needed for strong population-level inference. Avoid interpreting a confidence interval over repeated event/configuration rows as uncertainty over plants.

## Cost and plant-recording claims

`bench_cost.csv` contains logical memory estimates: a 1,800-element float32 buffer (7,200 bytes) plus manually assigned additional state (8, 12, 40, or 520 bytes). Those figures are estimates, not measured RAM or a complete firmware memory profile. Operation counts are explicitly “not measured”; Python runtime and firmware runtime are also marked “not measured.” The benchmark's detector code is Python, while the firmware baseline rescans its buffer and the alternative methods are not shown here as equivalent deployed firmware implementations. This is not a fair empirical compute-cost comparison. **Verdict: limited support for rough state-size estimates only; unsupported for relative execution cost, ESP32-S3 runtime, energy, or deployment performance.**

Synthetic injections test responses to programmed step, sustained, drift, spike, rail, and permanent signal changes. They do not constitute labeled real plant-stress events. The real recording/audit outputs describe logged rail-valued samples, gate replay, and operational episode grouping under incomplete historical fields; they do not validate biological stress detection or real-fault recovery. **Verdict for synthetic software behavior: supported with limitations. Verdict for plant-stress detection from these results: unsupported.**

## Claim-by-claim verdicts

| Result or claim | Verdict | Reason |
|---|---|---|
| Six sessions and five date/source folds met the stated eligibility rule | Supported | Session/fold keys and held-out rows are recorded; two September 13 sessions share one fold. |
| Held-out fold was excluded from its own setting selection | Supported with limitations | Fold grouping prevents direct leakage; only five correlated folds are available. |
| 15,088 event score rows | Supported | 656 planned event instances expanded over 23 settings; rows are repeated evaluations. |
| Per-method synthetic detection rates in `bench_summary.csv` | Supported with limitations | Correctly trace to selected held-out rows and eight-stratum equal-weight means; no uncertainty estimates and adaptive selection has calibration mismatch. |
| Clean false alarms/hour in `bench_summary.csv` | Unsupported as a valid event-free rate | Excluded injection intervals are also excluded from clean exposure and episode counts. |
| CUSUM/Page-Hinkley/stable selected-setting ranking | Supported with limitations, provisional | No direct leakage, but false-alarm exclusion bug affects budget selection and training injection scale differs from held-out scale. |
| Logical state-byte table | Supported with limitations | Transparent arithmetic estimate; not measured full-device memory. |
| Relative algorithm runtime/energy or ESP32-S3 performance | Unsupported | Neither firmware timing nor energy was measured; operation counts are not measured. |
| Real plant-stress detection or recovery | Unsupported | No labeled biological events or continuous ground-truth recovery intervals are available. |
| Gate/rail replay behavior on recorded values | Supported with limitations | Offline reconstruction uses available logged averages and fields; historical per-cycle saturation details are incomplete. |

## Paper changes recommended

No paper manuscript containing an abstract or contributions section was present in the examined `paper/` tree; it contains benchmark data tables and a figure. Apply these wording changes to the manuscript when it is available:

- **Abstract:** replace any claim of plant-stress detection or validated detector superiority with: “We evaluated six detector families in an offline replay using timestamp-aware synthetic signal injections across six eligible recording sessions grouped into five held-out source/date folds. These results characterize responses to the injected signal patterns and do not establish plant-stress detection.” Do not quote clean false-alarm rates until the clean-exposure defect and adaptive selection have been corrected.
- **Contributions:** describe contributions as (1) timestamp-aware replay and explicit gap/session handling, (2) grouped held-out evaluation of synthetic injection responses, and (3) a software audit of available recorded gate/rail behavior. Do not claim validated agronomic detection, deployable firmware equivalence, or measured resource efficiency.
- **Results:** report 656 planned event instances, 23 configurations per event (15,088 score rows), the eight-stratum equal-weight detection means, and five folds/six sessions. State that the event rows are repeated, clustered evaluations. Omit current clean false-alarm rates and adaptive-setting comparisons as final claims pending corrected exposure and selection calculations. Keep synthetic results separate from real-recording observations.
- **Limitations:** add the clean exposure-mask defect and required correction; training-versus-held-out injection-scale mismatch; five-fold/six-session dependence; no labeled plant-stress ground truth; incomplete historical ADC saturation fields; and no measured firmware runtime, energy, or complete memory footprint. State that confidence intervals and paired cluster comparisons are not currently reported.

The stale tables under `paper/data/bench_*.csv` are from the earlier benchmark schema and do not match the revised `out/revised/bench_*.csv` outputs. They must not be presented as results of this revised benchmark without an explicit provenance check and update. `reports/final_research_report.md` also predates this run: it says the revised benchmark has not been generated. That statement is now outdated, while its broader warning against using legacy tables remains relevant.

## Files examined

- Reports: `reports/benchmark_validation.md`, `reports/final_research_report.md`, `reports/claim_audit.md`, `reports/audit_report.md`, `reports/real_fault_analysis.md`, `reports/gate_ablation.md`, and `reports/baseline_absorption.md`.
- Revised benchmark outputs: every CSV in `out/revised/` (`absorption_theory_vs_simulation.csv`, `bench_cost.csv`, `bench_event_manifest.csv`, `bench_events.csv`, `bench_fa.csv`, `bench_folds.csv`, `bench_summary.csv`, `data_quality.csv`, `gate_ablation.csv`, `gate_ablation_combinations.csv`, `real_fault_episodes.csv`, `real_fault_metrics.csv`, `real_fault_reasons.csv`, `real_fault_replay_timeseries.csv`, and `window_sweep.csv`), plus `out/revised/bench_config.json` and the generated benchmark plots.
- Implementation/configuration: `analysis/benchmark_revised.py`, `analysis/benchmark.py`, `analysis/benchmark_time.py`, and `firmware/src/main.cpp`.
- Paper-side benchmark tables: `paper/data/bench_cost.csv`, `paper/data/bench_drop_one_day.csv`, `paper/data/bench_fa.csv`, `paper/data/bench_summary.csv`, and `paper/data/bench_tradeoff.csv`.

No raw inputs, benchmark outputs, or original audit reports were modified. The only file created by this audit is `reports/final_scientific_audit.md`.
