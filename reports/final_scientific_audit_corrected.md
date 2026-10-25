# Updated scientific audit: corrected revised benchmark

This audit supersedes the benchmark-specific conclusions in `reports/final_scientific_audit.md` for the newly generated bundle under `out/corrected/`. The earlier audit remains preserved. The correction report is `reports/benchmark_correction_report.md`.

## Corrected metrics and denominators

There are six eligible sessions grouped into five source/date folds. Each method's clean result pools selected held-out session rows over the same **64.42545 eligible clean monitoring hours**. Clean exposure means good, observed samples after the 1,800-second elapsed warm-up, with elapsed exposure counted only across adjacent eligible observations separated by more than zero and no more than ten seconds. No synthetic event-plan interval censors the unmodified clean stream. Rates are alarm episodes divided by those actual eligible hours; a zero-hour denominator is `NaN`. No zero-hour session occurred in this data set.

The event summary includes 656 planned held-out synthetic instances per method across eight event-type/magnitude strata. The mean detection headline is the unweighted mean of the eight stratum rates, `n_detected_in_event / n_events`; it is not a pooled event-level rate. The 15,088 score rows are 656 instances evaluated across 23 configurations, not 15,088 independent events. `bench_selection_events.csv` separately records 59,984 training-objective score rows repeated across outer folds.

| Method | Mean in-event detection, 8-stratum equal weight | Clean alarm episodes | Eligible clean hours | Clean episodes/hour |
|---|---:|---:|---:|---:|
| baseline | 0.326318 | 5 | 64.42545 | 0.077609 |
| freeze | 0.503522 | 136 | 64.42545 | 2.110967 |
| winsor | 0.335892 | 9 | 64.42545 | 0.139696 |
| CUSUM | 0.620061 | 67 | 64.42545 | 1.039962 |
| Page-Hinkley | 0.507731 | 76 | 64.42545 | 1.179658 |
| stable | 0.398875 | 6 | 64.42545 | 0.093131 |

The manifest has 685 rows: 656 planned, 24 ADC-limit exclusions, and 5 insufficient-coverage exclusions. Only planned injections are scored. The separate training event scores and fold metadata establish that the held-out fold is excluded from its training objective and calibration scale.

## Fold selection

For each held-out fold, the median of positive finite per-session robust scales from training-fold warm-up observations is used for both training event injections and that fold's held-out injections. Adaptive selection uses training-fold clean FA episodes/hour, then mean excess in-event detection for non-rail and non-permanent synthetic events. If no candidate meets the 1/hour budget, the lowest training FA setting is selected. Fixed methods remain fixed.

| Held-out fold | CUSUM | Page-Hinkley | Stable |
|---|---|---|---|
| `phytosense_trial_log.csv|2026-09-12` | `cusum(h=256)` | `ph(lam=320)` | `stable(band=1.0,T=1800)` |
| `phytosense_trial_log.csv|2026-09-13` | `cusum(h=256)` | `ph(lam=640)` | `stable(band=1.0,T=600)` |
| `phytosense_trial_log.csv|2026-10-12` | `cusum(h=128)` | `ph(lam=80)` | `stable(band=1.0,T=1800)` |
| `phytosense_trial_log.csv|2026-10-18` | `cusum(h=64)` | `ph(lam=40)` | `stable(band=1.0,T=600)` |
| `preflight_90min.csv|2026-10-17` | `cusum(h=128)` | `ph(lam=320)` | `stable(band=1.0,T=1800)` |

The outer-fold isolation checks pass. CUSUM fell back to its lowest training false-alarm rate in one fold because no candidate met the training budget. Held-out rates can exceed the selection budget; the budget is a training selection constraint, not a held-out guarantee.

## Verdicts

| Major result or claim | Verdict | Audit basis |
|---|---|---|
| Clean exposure and false alarms/hour | **Supported with limitations** | Uses the entire eligible clean signal and explicit gap-aware denominator; verified as episodes divided by hours. No zero-hour session occurred, though tests verify that case returns undefined. Rates describe only these sessions. |
| Held-out separation and adaptive selection | **Supported with limitations** | Training event scores, scales, and folds are recorded and checked for outer-fold isolation. Only five correlated folds are available. |
| Synthetic in-event detection results | **Supported with limitations** | Scores are generated from programmed signal changes on recorded streams, with explicit event strata. They do not measure biological stress response; no confidence intervals are reported. |
| Event count and independence | **Supported** | 15,088 rows repeat evaluations of 656 planned instances across 23 configurations. Events remain clustered by six sessions/five folds and are not independent biological replicates. |
| Clean false-alarm budget on held-out folds | **Supported with limitations** | Budget applies during training selection only. The chosen held-out detector can exceed 1 episode/hour. |
| Real plant-stress detection | **Unsupported** | No labeled plant-stress events are present. Synthetic injections cannot establish agronomic validity. |
| Real fault recovery from recordings | **Unsupported** | Existing logs have major gaps, unknown state across sessions, and incomplete historical ADC oversampling fields. The corrected benchmark does not change that evidence. |
| Gate behavior on available historical values | **Supported with limitations** | Offline reconstruction and rail groupings use logged fields; missing historical saturation/min/max fields prevent full firmware replay. |
| Relative cost, ESP32-S3 runtime, or energy | **Unsupported as measured performance** | `bench_cost.csv` has logical state estimates only. Operations, device runtime, energy, and full firmware memory were not measured. |

## Statistical and scientific limits

The 656 event instances are repeated, fixed-offset synthetic events nested in six sessions and five folds. The 23 settings evaluate the same underlying event windows; neither 15,088 score rows nor 656 event injections should be treated as independent plant replicates. No confidence intervals or paired tests are in the current summary. Report fold/session-level metrics and, if intervals are added, use a paired cluster bootstrap over the five source/date folds, preserving all sessions and event instances in each sampled fold. With five clusters, intervals are exploratory and unstable. A broader claim needs more independent acquisition days/runs/plants and labeled outcomes.

Keep synthetic replay findings separate from observed recording audits. Do not claim plant-stress detection, real fault recovery, firmware equivalence, ESP32-S3 speed, or energy efficiency. The state-byte table is an estimate, not a hardware measurement. Paper tables and `final_research_report.md` were not edited in this pass.

## Verification and files

Verification commands and outcomes are recorded in `reports/benchmark_correction_report.md`. The full test suite passed **21 tests**, the artifact validator passed, and `git diff --check` passed. The bundle in `out/corrected/` includes the event scores, separate training event scores, clean FA rows, folds, summary, manifest, cost estimates, configuration/provenance, validation report, and plots. `bench_config.json` includes protocol version, commit, runner SHA-256, scale-selection procedure, clean exposure rule, and repeated-event interpretation.
