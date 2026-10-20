
import sys
import os
from collections import deque

import numpy as np
import pandas as pd

# Detection thresholds
RAIL_HI = 4090.0
RAIL_LO = 50.0
FLAT_WIN = 60
FLAT_STD = 2.0
JUMP = 1200.0

# Baseline settings
BASELINE_SECONDS = 1800.0
MIN_N = 200
Z = 3.0

# Timing settings
LONG_GAP_SECONDS = 10.0
MAX_SCORE_INTERVAL_SECONDS = 1.5
FIRST_WINDOW_HOURS = 2.0

FAULT_START = "2026-10-12 22:03"
FAULT_END = "2026-10-14 17:52"
CLEAN_START = "2026-10-18 07:30"


class TimeWindow:
    """Maintain a timestamp-based rolling baseline."""

    def __init__(self):
        self.q = deque()
        self.s = 0.0
        self.ss = 0.0

    def expire(self, current_time):
        cutoff = current_time - pd.Timedelta(
            seconds=BASELINE_SECONDS
        )

        while self.q and self.q[0][0] <= cutoff:
            _, old_value = self.q.popleft()
            self.s -= old_value
            self.ss -= old_value * old_value

    def push(self, timestamp, value):
        self.q.append((timestamp, value))
        self.s += value
        self.ss += value * value

    def z(self, value):
        n = len(self.q)

        if n < 2:
            return 0.0

        mean = self.s / n
        variance = max(
            (self.ss - n * mean * mean) / (n - 1),
            0.0
        )

        return (value - mean) / (variance ** 0.5 + 1e-6)

    def reset(self):
        self.q.clear()
        self.s = 0.0
        self.ss = 0.0

    def __len__(self):
        return len(self.q)


def gate(value, previous, flat_queue):
    flat_queue.append(value)

    if len(flat_queue) > FLAT_WIN:
        flat_queue.popleft()

    if value >= RAIL_HI:
        return "rail_hi"

    if value <= RAIL_LO:
        return "rail_lo"

    if (
        len(flat_queue) == FLAT_WIN
        and np.std(flat_queue, ddof=1) < FLAT_STD
    ):
        return "flat"

    if previous is not None and abs(value - previous) > JUMP:
        return "jump"

    return "none"


def prepare_segment(frame):
    """Sort observations and combine duplicate timestamps by mean."""
    frame = frame[["t", "bioelectric_raw"]].copy()

    frame["bioelectric_raw"] = pd.to_numeric(
        frame["bioelectric_raw"],
        errors="coerce"
    )

    frame = frame.dropna(subset=["t", "bioelectric_raw"])
    frame = frame.sort_values("t")

    duplicate_rows = int(frame.duplicated("t").sum())

    frame = (
        frame.groupby("t", as_index=False)["bioelectric_raw"]
        .mean()
        .sort_values("t")
        .reset_index(drop=True)
    )

    return frame, duplicate_rows


def run_segment(frame):
    """Evaluate one recording without joining separate recording periods."""
    values = frame["bioelectric_raw"].to_numpy(dtype=float)
    times = frame["t"].reset_index(drop=True)

    gated_baseline = TimeWindow()
    ungated_baseline = TimeWindow()
    flat_queue = deque()

    previous = None

    reasons = []
    gated_deviation = []
    ungated_deviation = []
    score_seconds = []

    for i, value in enumerate(values):
        timestamp = times.iloc[i]

        interval = (
            0.0 if i == 0
            else (timestamp - times.iloc[i - 1]).total_seconds()
        )

        if interval > LONG_GAP_SECONDS:
            gated_baseline.reset()
            ungated_baseline.reset()
            flat_queue.clear()
            previous = None

        gated_baseline.expire(timestamp)
        ungated_baseline.expire(timestamp)

        reason = gate(value, previous, flat_queue)
        previous = value
        good = reason == "none"

        reasons.append(reason)

        scored = (
            i > 0
            and interval > 0
            and interval <= MAX_SCORE_INTERVAL_SECONDS
        )

        score_seconds.append(interval if scored else 0.0)

        # Gated baseline uses only samples accepted by the quality gate.
        if good and len(gated_baseline) >= MIN_N:
            gated_deviation.append(
                abs(gated_baseline.z(value)) > Z
            )
        else:
            gated_deviation.append(False)

        if good:
            gated_baseline.push(timestamp, value)

        # Ungated baseline uses every valid signal observation.
        if len(ungated_baseline) >= MIN_N:
            ungated_deviation.append(
                abs(ungated_baseline.z(value)) > Z
            )
        else:
            ungated_deviation.append(False)

        ungated_baseline.push(timestamp, value)

    return {
        "reasons": np.array(reasons),
        "gated": np.array(gated_deviation, dtype=bool),
        "ungated": np.array(ungated_deviation, dtype=bool),
        "score_seconds": np.array(score_seconds, dtype=float),
        "rows": len(values),
        "start": times.iloc[0] if len(times) else None,
        "end": times.iloc[-1] if len(times) else None,
    }


def count_events(deviations, score_seconds, minimum_length=10):
    """Count runs of at least 10 detected, eligible samples."""
    count = 0
    run_length = 0

    for detected, seconds in zip(deviations, score_seconds):
        if seconds > 0 and detected:
            run_length += 1

            if run_length == minimum_length:
                count += 1
        else:
            run_length = 0

    return count


def alarm_rate_per_hour(deviations, score_seconds):
    """Calculate alarm samples per hour of eligible recording time."""
    eligible_seconds = score_seconds.sum()

    if eligible_seconds <= 0:
        return float("nan")

    eligible = score_seconds > 0
    alarm_samples = deviations[eligible].sum()

    return alarm_samples / (eligible_seconds / 3600.0)


def summarize_segment(name, frame, lines):
    result = run_segment(frame)
    reasons = result["reasons"]
    rejected = reasons != "none"

    duration = (
        (result["end"] - result["start"]).total_seconds()
        if result["rows"] > 1 else 0.0
    )

    scored_hours = result["score_seconds"].sum() / 3600.0

    lines.append(f"[{name}]")
    lines.append(
        f" rows={result['rows']} unique timestamps; "
        f"start={result['start']}; end={result['end']}"
    )
    lines.append(
        f" elapsed span={duration / 3600.0:.3f} h; "
        f"eligible scored time={scored_hours:.3f} h"
    )
    lines.append(
        f" rejected={rejected.mean() * 100:.2f}% "
        f"reasons={dict(pd.Series(reasons[rejected]).value_counts())}"
    )
    lines.append(
        f" deviation samples: "
        f"gated={result['gated'].mean() * 100:.2f}%; "
        f"ungated={result['ungated'].mean() * 100:.2f}%"
    )
    lines.append(
        " events (10 consecutive eligible samples): "
        f"gated={count_events(result['gated'], result['score_seconds'])}; "
        f"ungated={count_events(result['ungated'], result['score_seconds'])}"
    )
    lines.append(
        " alarm samples per eligible hour: "
        f"gated={alarm_rate_per_hour(result['gated'], result['score_seconds']):.2f}; "
        f"ungated={alarm_rate_per_hour(result['ungated'], result['score_seconds']):.2f}"
    )

    return result


def run_injected_fault_test(clean):
    """Test reproducible synthetic rail, spike, and offset faults."""
    if len(clean) < 5000:
        return ["Not enough clean samples for the injected-fault test."]

    rng = np.random.default_rng(7)
    values = clean["bioelectric_raw"].to_numpy(dtype=float).copy()

    labels = np.zeros(len(values), dtype=bool)
    rail_labels = np.zeros(len(values), dtype=bool)
    spike_labels = np.zeros(len(values), dtype=bool)
    offset_labels = np.zeros(len(values), dtype=bool)

    low = 4000
    high = len(values) - 2500

    if high <= low:
        return ["Not enough clean samples for safe fault injection."]

    # Inject six rail episodes.
    for _ in range(6):
        start = int(rng.integers(low, high))
        duration = int(rng.integers(300, 1200))
        end = min(start + duration, len(values))

        values[start:end] = 4095.0
        labels[start:end] = True
        rail_labels[start:end] = True

    # Inject twelve isolated spikes.
    for _ in range(12):
        start = int(rng.integers(low, len(values) - 10))

        values[start] += rng.choice([-1.0, 1.0]) * 1800.0
        labels[start] = True
        spike_labels[start] = True

    # Inject four offset steps.
    for _ in range(4):
        start = int(rng.integers(low, high))
        end = min(start + 600, len(values))

        values[start:end] += 400.0
        labels[start:end] = True
        offset_labels[start:end] = True

    synthetic = clean.copy().reset_index(drop=True)
    synthetic["bioelectric_raw"] = values

    result = run_segment(synthetic)
    rejected = result["reasons"] != "none"
    eligible = result["score_seconds"] > 0

    # Combined detection: either quality-gate rejection or gated alarm.
    detected = (rejected | result["gated"]) & eligible

    def detection_line(name, mask):
        eligible_fault = eligible & mask
        total = int(eligible_fault.sum())
        caught = int((detected & eligible_fault).sum())
        percentage = 100.0 * caught / total if total else 0.0

        return (
            f" {name}: detected {caught} / {total} "
            f"eligible labelled samples ({percentage:.2f}%)"
        )

    clean_eligible = eligible & ~labels
    clean_total = int(clean_eligible.sum())
    clean_false = int((detected & clean_eligible).sum())
    clean_rate = (
        100.0 * clean_false / clean_total if clean_total else 0.0
    )

    return [
        "[INJECTED FAULTS - SIMULATED]",
        " Injection types: 6 rail episodes, 12 spikes, 4 offset steps",
        detection_line("Rail-labelled samples", rail_labels),
        detection_line("Spike-labelled samples", spike_labels),
        detection_line("Offset-labelled samples", offset_labels),
        detection_line("All injected samples", labels),
        (
            f" Clean eligible samples wrongly rejected or alarmed: "
            f"{clean_false} / {clean_total} ({clean_rate:.2f}%)"
        ),
        f" Gate-rejected samples: {int(rejected.sum())}",
        (
            f" Deviation samples: gated={int(result['gated'].sum())}; "
            f"ungated={int(result['ungated'].sum())}"
        ),
        (
            " Synthetic results are controlled test outputs, "
            "not evidence of field or clinical performance."
        ),
    ]


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python analysis\\replay_eval_timestamped.py "
            "<csv_path> [output_directory]"
        )
        sys.exit(1)

    path = sys.argv[1]
    output_directory = sys.argv[2] if len(sys.argv) > 2 else "."

    df = pd.read_csv(path, low_memory=False)

    required = {"wall_clock_time", "bioelectric_raw"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"CSV is missing required columns: {sorted(missing)}"
        )

    df["t"] = pd.to_datetime(
        df["wall_clock_time"],
        format="mixed",
        errors="coerce"
    )

    invalid_timestamps = int(df["t"].isna().sum())
    df = df.dropna(subset=["t"]).sort_values("t")

    fault_raw = df[
        (df["t"] >= FAULT_START)
        & (df["t"] <= FAULT_END)
    ]
    clean_raw = df[df["t"] >= CLEAN_START]

    fault, fault_duplicates = prepare_segment(fault_raw)
    clean, clean_duplicates = prepare_segment(clean_raw)

    lines = [
        "TIMESTAMP-AWARE REPLAY EVALUATION",
        f"Input CSV: {path}",
        f"Invalid timestamps dropped: {invalid_timestamps}",
        f"Duplicate timestamp rows combined: "
        f"fault={fault_duplicates}, clean={clean_duplicates}",
        f"Baseline window: previous {BASELINE_SECONDS:.0f} seconds",
        f"Minimum baseline samples: {MIN_N}",
        f"Long-gap reset threshold: > {LONG_GAP_SECONDS:.1f} seconds",
        f"Scored interval limit: <= {MAX_SCORE_INTERVAL_SECONDS:.1f} seconds",
        "",
    ]

    summarize_segment("FAULT RECORDING", fault, lines)
    lines.append("")
    summarize_segment("CLEAN RECORDING", clean, lines)

    lines.append("")
    lines.append("[FIRST TWO HOURS OF CLEAN RECORDING]")

    if len(clean):
        window_end = clean["t"].iloc[0] + pd.Timedelta(
            hours=FIRST_WINDOW_HOURS
        )
        first_window = clean[clean["t"] < window_end]
        first_result = run_segment(first_window)

        lines.append(
            f" window={clean['t'].iloc[0]} to {window_end}"
        )
        lines.append(
            f" rows={len(first_window)}; "
            f"gated alarms={first_result['gated'].sum()}; "
            f"ungated alarms={first_result['ungated'].sum()}"
        )
        lines.append(
            " This window is not immediately after the fault recording; "
            "the recordings are separated by a long unobserved gap."
        )
    else:
        lines.append("No clean recording rows were found.")

    lines.append("")
    lines.extend(run_injected_fault_test(clean))

    lines.append("")
    lines.append("[INTERPRETATION NOTES]")
    lines.append("Fault and clean recordings are evaluated independently.")
    lines.append("The baseline uses a timestamp-based 1800-second window.")
    lines.append("Only positive intervals up to 1.5 seconds count toward eligible time.")
    lines.append("Gated and ungated alarm rates share the same eligible-time denominator.")
    lines.append("Event counts require 10 consecutive detected samples with eligible intervals.")
    lines.append("Synthetic injected-fault results do not establish clinical or field validation.")

    output = "\n".join(lines)
    print(output)

    os.makedirs(output_directory, exist_ok=True)
    output_path = os.path.join(
        output_directory,
        "replay_eval_timestamped_summary.txt"
    )

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(output + "\n")

    print(f"\nSummary saved to: {output_path}")


if __name__ == "__main__":
    main()
