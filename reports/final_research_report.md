# PhytoSense++ research benchmark: corrected results and interpretation

## Scope and contribution

This study evaluates quality-aware baseline management for resource-constrained plant bioelectric monitoring. It compares a fixed rolling baseline, freeze and winsorized update rules, CUSUM, Page-Hinkley, and a stable-band rule in timestamp-aware software replay. The contribution is an evaluation of baseline management and data-quality handling under synthetic perturbations; it is not a novel-detector claim.

The repository contains analysis and reports, corrected benchmark data and plots, and legacy exploratory audits. The `paper/` directory contains benchmark CSVs and a plot, but no manuscript source (`.tex`, `.docx`, `.qmd`, or equivalent) was present. Paper prose should be transferred into the manuscript by its maintainer using the wording and verified values here; no manuscript file was guessed or created.

### Abstract-ready wording

> We evaluated quality-aware baseline management for resource-constrained plant bioelectric monitoring using timestamp-aware software replay on six recorded sessions grouped into five held-out folds. Across 656 planned synthetic event instances and eight event-type/magnitude strata, the unweighted mean stratum detection rates ranged from 0.3263 for the fixed baseline to 0.6201 for CUSUM. The same replay streams provided 64.42545 eligible clean monitoring hours per method, with 0.0776 to 2.1110 alarm episodes per hour. Event scores are repeated evaluations of synthetic injections, not independent biological events. These results characterize software replay on the available recordings; they do not establish plant-stress detection or deployed-device runtime or energy performance.

### Contribution wording

Describe the contributions as: (1) a timestamp- and quality-aware replay evaluation protocol with explicit clean exposure and outer-fold selection; (2) a comparison of six baseline-management method families under synthetic signal perturbations; and (3) an audit of the limits of the available recordings and the implementation-based cost estimates. Do not claim a novel detector, validated plant-stress classifier, or embedded performance result.

## Data context and protocol

The source log has 329,271 rows, including 13,372 duplicate timestamps. Deterministic duplicate coalescing yields 93,049 unique rail timestamps from 93,154 raw rail-valued rows. A 10-second grouping yields 109 operational episodes; the longest spans 72,857.424 elapsed seconds. Large timestamp gaps mean this grouping does not establish continuous acquisition. Times have no timezone marker.

The corrected benchmark uses six eligible sessions grouped into five source/date outer folds. Events are elapsed-time synthetic injections into recorded signal streams. The held-out manifest contains 656 planned synthetic event instances and 29 separate excluded plans: 24 ADC-limit exclusions and five insufficient-coverage exclusions. The excluded plans are not scored and do not reduce the 656 planned-instance denominator. The event table has 15,088 rows because the same 656 instances were evaluated repeatedly across 23 configurations. Those rows are repeated configuration evaluations, not independent events.

Detection is computed within each of eight event-type/magnitude strata as detections divided by planned events in that stratum. Each headline is the unweighted mean of the eight stratum rates. Clean exposure includes eligible quality-gate-good observations after the 1,800-second elapsed warm-up. Exposure counts only adjacent eligible observations with `0 < gap <= 10` seconds. Synthetic plan windows do not censor otherwise eligible observations in the unmodified clean stream. Clean false-alarm burden is merged alarm episodes divided by actual eligible clean hours; a zero-hour denominator is undefined (`NaN`), not a zero rate.

Adaptive settings are selected separately for each outer fold using its other four configured folds only. Training-fold data determine the pooled scale and the setting; that training-only pooled scale is used for training and held-out event injections. Independent bundle checks found no held-out selection leakage. The `training_folds` text field uses a delimiter also present inside fold IDs, so fold membership should be described from the canonical configuration and score rows, not parsed from that field alone.

## Corrected synthetic replay results

| Method | Mean detection across 8 synthetic strata | Clean alarm episodes | Eligible clean hours | Episodes/hour |
|---|---:|---:|---:|---:|
| Baseline | 0.326318 | 5 | 64.42545 | 0.077609 |
| Freeze | 0.503522 | 136 | 64.42545 | 2.110967 |
| Winsor | 0.335892 | 9 | 64.42545 | 0.139696 |
| CUSUM | 0.620061 | 67 | 64.42545 | 1.039962 |
| Page-Hinkley | 0.507731 | 76 | 64.42545 | 1.179658 |
| Stable | 0.398875 | 6 | 64.42545 | 0.093131 |

These are software replay outcomes for synthetic events on recorded signal streams. They do not demonstrate detection of biological plant stress. Results are clustered within only six sessions/five folds; no confidence intervals are reported. The 15,088 score rows and 656 event instances are not independent biological replicates. Paired fold-cluster resampling could provide exploratory uncertainty, but five clusters would yield unstable intervals; additional independent days, runs, plants, and labeled outcomes are needed for stronger inference.

## Cost and device claims

`paper/data/bench_cost.csv` contains logical state-size estimates derived from implementation assumptions. These are estimates, not measured device memory. Operation counts, Python runtime, firmware-equivalent runtime, ESP32-S3 runtime, energy consumption, and complete deployed memory were not measured. Do not claim firmware equivalence, ESP32-S3 speed, or energy efficiency.

## Other evidence and limitations

The available-field firmware-like gate replay admitted all 93,049 unique rail timestamps ungated and none gated; it rejected 36 nonrail values. It starts with an empty ring and reconstructs gates from incomplete historical fields, so it is not an exact recreation of historical firmware state. The high-rail check rejects all labeled rail points in these logs; contact, low-rail, and jump reject none, while flatness also rejects many rail points. Nonrail rejection rates are proxy-only because complete independent good/fault labels and historical per-cycle ADC min/max/saturation fields are unavailable.

The logged stream has large gaps and unknown reset/reboot history. The corrected synthetic replay does not establish real fault recovery or plant-stress detection. Available recordings have no labeled plant-stress episodes, and real-plant validation is limited to observational signal and gate audits. Population-level claims, validated agronomic interpretation, and post-fault recovery claims remain unsupported.

## Reproducibility and artifacts

Corrected benchmark source artifacts and provenance are under `out/corrected/`; paper-side benchmark assets are under `paper/data/`. The corrected bundle records protocol version `corrected_clean_exposure_pooled_scale_v1`, commit `313de1fe25bcfa85907e0c533428f6f6847884cc`, and runner SHA-256 `0a3c85631b9c704b8e6910bc25ac8e379ceedb365fb489df54d6e916505c4b39`. The benchmark completed in about 9 minutes 19 seconds. Its validator and test outcomes are documented in `reports/benchmark_correction_report.md`; independent counts and aggregation checks are in `reports/event_count_and_bundle_audit.md` and `reports/final_scientific_audit_corrected.md`.

Paper-side CSVs and `fig_tradeoff.png` were regenerated from corrected outputs. `bench_drop_one_day.csv` now records actual held-out-fold method results; it is not the former leave-one-day analysis. `bench_tradeoff.csv` reports descriptive fixed-configuration replay across all five held-out folds and is not an independent post-selection comparison. Cost entries remain explicitly labeled logical estimates or not measured.
