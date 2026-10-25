"""Read-only integrity checks for the corrected benchmark artifact bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "corrected"
REQUIRED = (
    "bench_events.csv", "bench_selection_events.csv", "bench_event_manifest.csv",
    "bench_fa.csv", "bench_folds.csv", "bench_summary.csv", "bench_cost.csv",
    "bench_config.json", "bench_validation.md", "bench_detection.png", "bench_tradeoff.png",
)


def validate() -> None:
    missing = [name for name in REQUIRED if not (OUT / name).is_file() or (OUT / name).stat().st_size == 0]
    if missing:
        raise AssertionError(f"Missing or empty benchmark artifacts: {missing}")
    events = pd.read_csv(OUT / "bench_events.csv")
    selection = pd.read_csv(OUT / "bench_selection_events.csv")
    manifest = pd.read_csv(OUT / "bench_event_manifest.csv")
    fa = pd.read_csv(OUT / "bench_fa.csv")
    folds = pd.read_csv(OUT / "bench_folds.csv")
    summary = pd.read_csv(OUT / "bench_summary.csv")
    config = json.loads((OUT / "bench_config.json").read_text(encoding="utf-8"))

    expected_methods = {"baseline", "freeze", "winsor", "cusum", "ph", "stable"}
    if set(events.family.unique()) != expected_methods or set(summary.family.unique()) != expected_methods:
        raise AssertionError("The corrected event and summary outputs must contain all six methods.")
    if len(events) != config["event_rows"] or len(events) != 15088:
        raise AssertionError("Held-out score row count does not match the recorded configuration.")
    # Six sessions form five source/date folds; there are three adaptive rows per fold.
    if len(folds) != 15 or folds.held_out_fold.nunique() != 5:
        raise AssertionError("Fold result count is inconsistent with grouped outer validation.")
    if not events.event_status.eq("planned").all():
        raise AssertionError("Excluded injections must not appear as scored event rows.")
    outcomes = events.detected_in_event.astype(int) + events.post_only.astype(int) + events.missed.astype(int)
    if not outcomes.eq(1).all():
        raise AssertionError("Event outcome categories do not partition the score rows.")
    score_key = ["outer_held_out_fold", "session", "family", "setting", "kind", "mag_sd", "event_start"]
    if events.duplicated(score_key).any():
        raise AssertionError("Duplicate event/configuration score keys found.")

    scales = folds.drop_duplicates("held_out_fold").set_index("held_out_fold").training_scale_adc
    for outer, rows in selection.groupby("outer_held_out_fold"):
        if (rows.fold == outer).any():
            raise AssertionError(f"Held-out fold {outer} appears in its training event scores.")
        if not np.allclose(rows.injection_scale_adc, scales.loc[outer], equal_nan=True):
            raise AssertionError(f"Training injections do not use the recorded fold scale for {outer}.")
    for outer, rows in events.groupby("outer_held_out_fold"):
        if (rows.fold != outer).any():
            raise AssertionError(f"Held-out score rows contain another fold under {outer}.")
        if not np.allclose(rows.injection_scale_adc, scales.loc[outer], equal_nan=True):
            raise AssertionError(f"Held-out injections do not use the training-only scale for {outer}.")
    if not folds.heldout_data_used_for_selection.eq(False).all():
        raise AssertionError("Fold metadata indicates held-out data were used for selection.")

    if (fa.eligible_clean_hours < 0).any() or (fa.alarm_episodes < 0).any():
        raise AssertionError("Negative clean exposure or alarm episode count.")
    zero = fa.eligible_clean_hours.eq(0)
    if fa.loc[zero, "fa_per_h"].notna().any():
        raise AssertionError("A zero-hour false-alarm rate must be undefined.")
    positive = ~zero
    if not np.allclose(fa.loc[positive, "fa_per_h"],
                       fa.loc[positive, "alarm_episodes"] / fa.loc[positive, "eligible_clean_hours"]):
        raise AssertionError("False-alarm rates do not equal episodes divided by eligible clean hours.")

    for family, g in summary[summary.kind != "clean"].groupby("family"):
        if int(g.n_events.sum()) != 656:
            raise AssertionError(f"{family}: expected 656 held-out synthetic event instances across strata.")
        mean = float(g.detect_rate.mean())
        if not np.isfinite(mean) or not 0 <= mean <= 1:
            raise AssertionError(f"{family}: invalid equal-stratum mean detection rate.")
    status_counts = manifest.status.value_counts().to_dict()
    if status_counts != {"planned": 656, "excluded_adc_limit": 24, "excluded_insufficient_elapsed_coverage": 5}:
        raise AssertionError(f"Unexpected manifest statuses: {status_counts}")
    runner_hash = hashlib.sha256((ROOT / "analysis" / "benchmark_revised.py").read_bytes()).hexdigest()
    if config["benchmark_runner_sha256"] != runner_hash:
        raise AssertionError("Recorded runner SHA-256 does not match the current runner.")
    if config.get("protocol_version") != "corrected_clean_exposure_pooled_scale_v1":
        raise AssertionError("Unexpected corrected benchmark protocol version.")
    print(f"PASS: {len(events)} held-out scores; {len(selection)} training scores; {len(fa)} clean FA rows; "
          f"{len(manifest)} manifest rows; {len(REQUIRED)} nonempty artifacts; six methods; 5 outer folds.")


if __name__ == "__main__":
    validate()
