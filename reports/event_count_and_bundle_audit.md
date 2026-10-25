# Event-count and corrected-bundle audit

## Verified event counts

Counts were recomputed from `out/corrected/` using pandas and normalized parsed datetimes for event start/end (raw CSV timestamp strings have mixed fractional-second formatting).

- The held-out manifest has **685 distinct scheduled plan IDs**: **656 planned** and **29 excluded** (24 `excluded_adc_limit`, 5 `excluded_insufficient_elapsed_coverage`). The 29 excluded plan IDs are separate from the 656 planned IDs.
- The 656 planned IDs are the **total unique held-out synthetic instances across all five folds**, not 656 per fold or per configuration. Fold counts are 84 (2026-09-12), 357 (2026-09-13), 32 (2026-10-12), 161 (2026-10-18), and 22 (preflight 2026-10-17). They sum to 656.
- The held-out event table has **15,088 rows**. One row is one unique planned event instance, evaluated by one method setting in its held-out fold. Each of the **23 configurations** has 656 rows and covers the same 656 normalized event IDs. The 23 settings comprise six method families: baseline (1), freeze (1), winsor (1), CUSUM (7), Page-Hinkley (7), and stable (6). The event rows are repeated evaluations, not independent events.
- The held-out table contains **5 outer folds**, **6 method families**, **23 method configurations**, and **8 event strata** (`kind` plus magnitude): drift/6, permanent/6, rail/0, spike/10, step/6, and sustained/3, /4, /6.
- All 15,088 held-out rows have `event_status=planned`. The 29 exclusions are not scored and do not reduce the 656 evaluated-instance denominator. Each method has 656 instances total across its eight strata; the stratum denominators are 87, 5, 97, 96, 94, 93, 92, and 92 (656 total).

The held-out manifest's 24 and 5 exclusion counts describe the final held-out injection plans. The 59,984 rows in `bench_selection_events.csv` are training-fold event/configuration evaluations across outer folds; they include only planned injections, as the runner filters plans by `status == 'planned'`. There is no separate persisted training-plan manifest, so the held-out manifest's exclusion totals should not be read as aggregate counts of every training-fold injection attempt. This does not change the held-out denominator.

## Reproduction checks

The selected held-out rows (`selected_for_heldout_fold=True`) were grouped by method, event kind, and magnitude. For all **48** method/stratum cells (6 × 8), recomputed `n_events`, detected count, and `detected_in_event.mean()` match `bench_summary.csv`; there are zero denominator mismatches and the largest floating-point rate difference is `9.1e-17`. The method-level headlines reproduce as unweighted means of the eight stratum rates:

| Method | Recomputed mean detection |
|---|---:|
| baseline | 0.326318 |
| freeze | 0.503522 |
| winsor | 0.335892 |
| CUSUM | 0.620061 |
| Page-Hinkley | 0.507731 |
| stable | 0.398875 |

Clean alarm burden was independently reconstructed by applying each held-out fold's selected setting to the matching session rows in `bench_fa.csv` (fixed methods use their fixed setting). For every method the selected rows total **64.4254497222 eligible clean hours**, rounded in reports to **64.42545**. Recomputed episodes and rates exactly reproduce `bench_summary.csv` within floating-point precision:

| Method | Episodes | Eligible clean hours | Recomputed episodes/hour |
|---|---:|---:|---:|
| baseline | 5 | 64.4254497222 | 0.077609 |
| freeze | 136 | 64.4254497222 | 2.110967 |
| winsor | 9 | 64.4254497222 | 0.139696 |
| CUSUM | 67 | 64.4254497222 | 1.039962 |
| Page-Hinkley | 76 | 64.4254497222 | 1.179658 |
| stable | 6 | 64.4254497222 | 0.093131 |

## Selection integrity

The configured fold list in `bench_config.json` has five canonical source/date keys. For each row in `bench_folds.csv`, I formed the training set as all configured folds except that row's held-out fold, then checked `bench_selection_events.csv`: it contains all four permitted training folds and no held-out fold. Recomputed each adaptive selection from training-only `bench_fa.csv` rates and training-only `bench_selection_events.csv` mean excess scores, applying the recorded 1/hour budget and lowest-rate fallback. All **15** selections (three adaptive families × five folds) reproduce the selected setting in `bench_folds.csv`. The held-out event rows use the fold's recorded training-only pooled scale. No held-out leakage was found.

One metadata-format caveat remains: `training_folds` joins fold IDs with `|`, while each fold ID itself contains `|` between source and date. Splitting that field on `|` is ambiguous. The results remain reproducible from the canonical fold list in `bench_config.json`, the held-out fold, and the training score rows; a future manifest could store `training_folds` as a JSON array. This is a metadata ergonomics issue, not a selection or metric defect.

## Verdict and paper wording

No result-count or metric discrepancy was found. The bundle is internally consistent, and a benchmark rerun is **not necessary**. No files other than this new report were changed; no detector, raw data, output, or prior audit report was modified.

Suggested methods wording:

> “We generated elapsed-time synthetic events in six eligible recording sessions grouped into five source/date held-out folds. The held-out manifest contained 656 planned event instances and 29 explicitly excluded plans (24 ADC-limit and 5 insufficient-coverage exclusions). Each planned instance was evaluated under 23 configurations, yielding 15,088 held-out event/configuration scores across eight event-type/magnitude strata. These score rows are repeated evaluations of the same synthetic instances, not independent events. Adaptive settings were selected using training-fold data only, with the training-only pooled scale used for both training and held-out injections.”

Suggested results wording:

> “Mean in-event detection was calculated as the unweighted mean of the eight stratum-specific detection rates. The resulting values were 0.3263 (baseline), 0.5035 (freeze), 0.3359 (winsor), 0.6201 (CUSUM), 0.5077 (Page-Hinkley), and 0.3989 (stable). Clean false-alarm rates were calculated from 5, 136, 9, 67, 76, and 6 alarm episodes, respectively, over 64.42545 eligible clean monitoring hours per method. These are synthetic replay results on recorded signal streams and do not establish plant-stress detection.”

Interpret these estimates as clustered session/fold-level software replay results; do not treat the 15,088 score rows as independent observations or infer population-level plant performance.

## Files and commands

Inspected `out/corrected/bench_event_manifest.csv`, `bench_events.csv`, `bench_selection_events.csv`, `bench_folds.csv`, `bench_summary.csv`, `bench_fa.csv`, `bench_config.json`; `analysis/benchmark_revised.py`, `analysis/validate_corrected_benchmark.py`, `tests/test_benchmark_corrected.py`; `reports/benchmark_correction_report.md`; and `reports/final_scientific_audit_corrected.md`.

The read-only count/reproduction query was run from PowerShell as a here-string piped to Python (`@' ... '@ | python -`); it parsed event timestamps with `pd.to_datetime(..., format='mixed')`, grouped normalized IDs, recomputed all 48 event-stratum cells, reconstructed six clean totals from fold-selected `bench_fa.csv` rows, and recalculated all 15 adaptive selections from training-only rows. The existing bundle validator also passed:

```text
python analysis/validate_corrected_benchmark.py
git diff --check
```

The validator reported 15,088 held-out scores, 59,984 selection scores, 138 clean FA rows, 685 manifest rows, 11 nonempty artifacts, six methods, and five outer folds. No code changes were needed, so the test suite was not rerun for this read-only audit.
