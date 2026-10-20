import sys
import os
from collections import deque

import numpy as np
import pandas as pd


# ============================================================
# DETECTION THRESHOLDS
# ============================================================

RAIL_HI = 4090.0
RAIL_LO = 50.0
FLAT_WIN = 60
FLAT_STD = 2.0
JUMP = 1200.0


# ============================================================
# BASELINE SETTINGS
# ============================================================

BASELINE_SECONDS = 1800.0
MIN_N = 200
Z = 3.0

# Center the signal to reduce numerical cancellation when
# calculating rolling variance.
SIGNAL_CENTER = 2048.0


# ============================================================
# TIMING SETTINGS
# ============================================================

LONG_GAP_SECONDS = 10.0
MAX_SCORE_INTERVAL_SECONDS = 1.5
FIRST_WINDOW_HOURS = 2.0


# ============================================================
# RECORDING WINDOWS
# ============================================================

FAULT_START = "2026-10-12 22:03"
FAULT_END = "2026-10-14 17:52"
CLEAN_START = "2026-10-18 07:30"


# ============================================================
# TIMESTAMP-BASED ROLLING BASELINE
# ============================================================

class TimeWindow:
    """Maintain a rolling baseline using actual timestamps."""

    def __init__(self):
        self.q = deque()
        self.s = 0.0
        self.ss = 0.0

    def expire(self, current_time):
        cutoff = current_time - pd.Timedelta(
            seconds=BASELINE_SECONDS
        )

        while self.q and self.q[0][0] <= cutoff:
            _, old_centered = self.q.popleft()
            self.s -= old_centered
            self.ss -= old_centered * old_centered

    def push(self, timestamp, value):
        centered = float(value) - SIGNAL_CENTER

        self.q.append((timestamp, centered))
        self.s += centered
        self.ss += centered * centered

    def z(self, value):
        n = len(self.q)

        if n < 2:
            return 0.0

        mean = self.s / n

        variance = (
            self.ss - n * mean * mean
        ) / (n - 1)

        variance = max(variance, 0.0)

        centered_value = float(value) - SIGNAL_CENTER
        standard_deviation = variance ** 0.5

        return (
            (centered_value - mean)
            / (standard_deviation + 1e-6)
        )

    def reset(self):
        self.q.clear()
        self.s = 0.0
        self.ss = 0.0

    def __len__(self):
        return len(self.q)


# ============================================================
# SENSOR QUALITY GATE
# ============================================================

def gate(value, previous_good, flat_queue):
    """
    Check for rail values, flat signals and large jumps.

    Rejected rail and jump readings are not added to the
    flat-signal history. Flat readings are also excluded.
    previous_good contains the last accepted reading.
    """

    # 1. Reject readings outside the permitted signal range.
    if value >= RAIL_HI:
        return "rail_hi"

    if value <= RAIL_LO:
        return "rail_lo"

    # 2. Reject sudden jumps compared with the last accepted reading.
    if (
        previous_good is not None
        and abs(value - previous_good) > JUMP
    ):
        return "jump"

    # 3. Test the candidate against the recent accepted readings.
    # Do not permanently retain it if it is classified as flat.
    candidate_values = list(flat_queue)
    candidate_values.append(value)

    if len(candidate_values) > FLAT_WIN:
        candidate_values = candidate_values[-FLAT_WIN:]

    if (
        len(candidate_values) == FLAT_WIN
        and np.std(candidate_values, ddof=1) < FLAT_STD
    ):
        return "flat"

    # 4. Only accepted readings enter the flat-signal history.
    flat_queue.append(value)

    if len(flat_queue) > FLAT_WIN:
        flat_queue.popleft()

    return "none"
# ============================================================
# PREPARE A RECORDING SEGMENT
# ============================================================

def prepare_segment(frame):
    """
    Sort observations and combine duplicate timestamps by mean.
    """

    frame = frame[
        ["t", "bioelectric_raw"]
    ].copy()

    frame["bioelectric_raw"] = pd.to_numeric(
        frame["bioelectric_raw"],
        errors="coerce"
    )

    frame = frame.dropna(
        subset=["t", "bioelectric_raw"]
    )

    frame = frame.sort_values("t")

    duplicate_rows = int(
        frame.duplicated("t").sum()
    )

    frame = (
        frame.groupby(
            "t",
            as_index=False
        )["bioelectric_raw"]
        .mean()
        .sort_values("t")
        .reset_index(drop=True)
    )

    return frame, duplicate_rows


# ============================================================
# RUN THE DETECTOR ON ONE RECORDING
# ============================================================

def run_segment(frame):
    """
    Evaluate one recording without joining separate periods.

    Gated baseline:
        Uses only readings accepted by the quality gate.

    Ungated baseline:
        Uses every valid signal observation.

    Scored interval:
        Positive interval no longer than 1.5 seconds.
    """

    frame = frame.reset_index(drop=True)

    values = frame[
        "bioelectric_raw"
    ].to_numpy(dtype=float)

    times = frame["t"]

    if len(values) == 0:
        return {
            "reasons": np.array([], dtype=str),
            "gated": np.array([], dtype=bool),
            "ungated": np.array([], dtype=bool),
            "score_seconds": np.array([], dtype=float),
            "rows": 0,
            "start": None,
            "end": None,
        }

    gated_baseline = TimeWindow()
    ungated_baseline = TimeWindow()

    flat_queue = deque()

    previous_good = None

    reasons = []
    gated_deviation = []
    ungated_deviation = []
    score_seconds = []

    for i, value in enumerate(values):
        timestamp = times.iloc[i]

        interval = (
            0.0
            if i == 0
            else (
                timestamp - times.iloc[i - 1]
            ).total_seconds()
        )

        # Reset the baseline after a sufficiently long gap.
        if interval > LONG_GAP_SECONDS:
            gated_baseline.reset()
            ungated_baseline.reset()
            flat_queue.clear()
            previous_good = None

        gated_baseline.expire(timestamp)
        ungated_baseline.expire(timestamp)

        reason = gate(
            value,
            previous_good,
            flat_queue
        )

        good = reason == "none"

        reasons.append(reason)

        scored = (
            i > 0
            and interval > 0
            and interval <= MAX_SCORE_INTERVAL_SECONDS
        )

        score_seconds.append(
            interval if scored else 0.0
        )

        # Gated deviation detection uses past accepted samples.
        gated_alarm = False

        if good and len(gated_baseline) >= MIN_N:
            gated_alarm = (
                abs(gated_baseline.z(value)) > Z
            )

        gated_deviation.append(gated_alarm)

        # Only accepted readings become the jump reference
        # and enter the gated baseline.
        if good:
            previous_good = value

            gated_baseline.push(
                timestamp,
                value
            )

        # Ungated detector uses all valid observations.
        ungated_alarm = False

        if len(ungated_baseline) >= MIN_N:
            ungated_alarm = (
                abs(ungated_baseline.z(value)) > Z
            )

        ungated_deviation.append(ungated_alarm)

        ungated_baseline.push(
            timestamp,
            value
        )

    return {
        "reasons": np.array(reasons),
        "gated": np.array(
            gated_deviation,
            dtype=bool
        ),
        "ungated": np.array(
            ungated_deviation,
            dtype=bool
        ),
        "score_seconds": np.array(
            score_seconds,
            dtype=float
        ),
        "rows": len(values),
        "start": times.iloc[0],
        "end": times.iloc[-1],
    }


# ============================================================
# METRIC HELPERS
# ============================================================

def eligible_mask(result):
    """Return the mask of samples eligible for scoring."""

    return result["score_seconds"] > 0


def alarm_sample_count(deviations, score_seconds):
    """Count detected samples whose intervals are eligible."""

    eligible = score_seconds > 0

    return int(
        np.sum(deviations & eligible)
    )


def count_events(
    deviations,
    score_seconds,
    minimum_length=10
):
    """
    Count runs of at least minimum_length consecutive
    detected, eligible samples.
    """

    count = 0
    run_length = 0

    for detected, seconds in zip(
        deviations,
        score_seconds
    ):
        if seconds > 0 and detected:
            run_length += 1

            if run_length == minimum_length:
                count += 1
        else:
            run_length = 0

    return count


def alarm_rate_per_hour(
    deviations,
    score_seconds
):
    """
    Calculate alarm samples per eligible recording hour.

    This is NOT the number of distinct alarm events per hour.
    """

    eligible_seconds = float(
        score_seconds.sum()
    )

    if eligible_seconds <= 0:
        return float("nan")

    alarms = alarm_sample_count(
        deviations,
        score_seconds
    )

    return alarms / (eligible_seconds / 3600.0)


def percentage(numerator, denominator):
    if denominator <= 0:
        return float("nan")

    return 100.0 * numerator / denominator


def format_percentage(value):
    if np.isnan(value):
        return "N/A"

    return f"{value:.2f}%"


def format_rate(value):
    if np.isnan(value):
        return "N/A"

    return f"{value:.2f}"


def rejection_counts(reasons):
    rejected = reasons[reasons != "none"]

    if len(rejected) == 0:
        return {}

    counts = pd.Series(
        rejected
    ).value_counts()

    return {
        str(key): int(value)
        for key, value in counts.items()
    }


# ============================================================
# REPORT ONE RECORDING SEGMENT
# ============================================================

def summarize_segment(name, frame, lines):
    result = run_segment(frame)

    rows = result["rows"]

    lines.append(f"[{name}]")

    if rows == 0:
        lines.append(
            " No valid observations in this recording window."
        )
        return result

    reasons = result["reasons"]
    rejected = reasons != "none"

    score_seconds = result["score_seconds"]
    eligible = eligible_mask(result)

    duration = (
        result["end"] - result["start"]
    ).total_seconds()

    eligible_seconds = float(
        score_seconds.sum()
    )

    eligible_hours = eligible_seconds / 3600.0

    gated_count = alarm_sample_count(
        result["gated"],
        score_seconds
    )

    ungated_count = alarm_sample_count(
        result["ungated"],
        score_seconds
    )

    gated_events = count_events(
        result["gated"],
        score_seconds
    )

    ungated_events = count_events(
        result["ungated"],
        score_seconds
    )

    lines.append(
        f" rows={rows} unique timestamps; "
        f"start={result['start']}; "
        f"end={result['end']}"
    )

    lines.append(
        f" elapsed span={duration / 3600.0:.3f} h; "
        f"eligible scored time={eligible_hours:.3f} h"
    )

    lines.append(
        f" eligible intervals={int(eligible.sum())}; "
        f"rejected={format_percentage(percentage(int(rejected.sum()), rows))}"
    )

    lines.append(
        f" rejection reasons={rejection_counts(reasons)}"
    )

    lines.append(
        " Deviation samples across all rows: "
        f"gated={format_percentage(percentage(int(result['gated'].sum()), rows))}; "
        f"ungated={format_percentage(percentage(int(result['ungated'].sum()), rows))}"
    )

    lines.append(
        " Eligible alarm samples: "
        f"gated={gated_count}; ungated={ungated_count}"
    )

    lines.append(
        " Distinct alarm events "
        "(10 consecutive eligible samples): "
        f"gated={gated_events}; ungated={ungated_events}"
    )

    lines.append(
        " Alarm samples per eligible hour: "
        f"gated={format_rate(alarm_rate_per_hour(result['gated'], score_seconds))}; "
        f"ungated={format_rate(alarm_rate_per_hour(result['ungated'], score_seconds))}"
    )

    return result


# ============================================================
# ISOLATED SYNTHETIC FAULT TESTS
# ============================================================

def build_fault_case(clean, fault_type):
    """
    Build one synthetic test at a time.

    Each test begins with the original clean recording.
    Fault types are never mixed with one another in the
    same isolated test.
    """

    synthetic = clean.copy().reset_index(drop=True)

    values = synthetic[
        "bioelectric_raw"
    ].to_numpy(dtype=float).copy()

    labels = np.zeros(
        len(values),
        dtype=bool
    )

    if len(values) < 5000:
        return None, None

    # Keep injection locations away from the beginning
    # and end of the recording.
    low = 4000
    high = len(values) - 2500

    if high <= low:
        return None, None

    available = high - low

    if fault_type == "rail":
        # Six separate rail episodes.
        slot = available // 6

        if slot < 1200:
            return None, None

        for i in range(6):
            slot_start = low + i * slot
            max_duration = min(
                1199,
                slot - 1
            )

            duration = min(
                300 + (i * 137) % 900,
                max_duration
            )

            start = slot_start + max(
                0,
                (slot - duration) // 2
            )

            end = start + duration

            values[start:end] = 4095.0
            labels[start:end] = True

    elif fault_type == "spike":
        # Twelve isolated spikes at separated positions.
        for i in range(12):
            start = low + (
                (i + 1) * available
            ) // 13

            direction = (
                1.0 if i % 2 == 0 else -1.0
            )

            values[start] += direction * 1800.0
            labels[start] = True

    elif fault_type == "offset":
        # Four separate 600-sample offset steps.
        slot = available // 4

        if slot < 600:
            return None, None

        for i in range(4):
            start = low + i * slot + (
                slot - 600
            ) // 2

            end = start + 600

            values[start:end] += 400.0
            labels[start:end] = True

    else:
        raise ValueError(
            f"Unknown fault type: {fault_type}"
        )

    synthetic["bioelectric_raw"] = values

    return synthetic, labels


def evaluate_fault_case(clean, fault_type):
    """
    Evaluate one isolated fault type.

    A labelled sample is counted as detected when it is
    rejected by the quality gate or flagged by the gated
    deviation detector, provided its interval is eligible.
    """

    synthetic, labels = build_fault_case(
        clean,
        fault_type
    )

    if synthetic is None:
        return None

    result = run_segment(synthetic)

    eligible = eligible_mask(result)

    rejected = result["reasons"] != "none"

    detected = rejected | result["gated"]

    eligible_fault = eligible & labels

    eligible_clean = eligible & ~labels

    fault_total = int(
        eligible_fault.sum()
    )

    fault_detected = int(
        (detected & eligible_fault).sum()
    )

    clean_total = int(
        eligible_clean.sum()
    )

    clean_false = int(
        (detected & eligible_clean).sum()
    )

    return {
        "fault_type": fault_type,
        "fault_total": fault_total,
        "fault_detected": fault_detected,
        "fault_percentage": percentage(
            fault_detected,
            fault_total
        ),
        "clean_total": clean_total,
        "clean_false": clean_false,
        "clean_false_percentage": percentage(
            clean_false,
            clean_total
        ),
        "eligible_seconds": float(
            result["score_seconds"].sum()
        ),
        "gate_rejected": int(
            np.sum(rejected & eligible)
        ),
        "gated_alarms": alarm_sample_count(
            result["gated"],
            result["score_seconds"]
        ),
        "ungated_alarms": alarm_sample_count(
            result["ungated"],
            result["score_seconds"]
        ),
    }


def run_injected_fault_test(clean):
    """
    Run separate rail, spike and offset experiments.

    These are controlled synthetic tests, not field
    validation.
    """

    if len(clean) < 5000:
        return [
            "[INJECTED FAULTS - SIMULATED]",
            " Not enough clean samples for fault injection."
        ]

    lines = [
        "[INJECTED FAULTS - SIMULATED]",
        " Each fault type is tested separately.",
        " Rail: six episodes of elevated readings.",
        " Spike: twelve isolated +/-1800 changes.",
        " Offset: four +400 steps lasting 600 rows.",
        " Detection means gate rejection OR gated deviation.",
        " Only eligible labelled samples count in sensitivity.",
        "",
    ]

    results = []

    for fault_type in (
        "rail",
        "spike",
        "offset"
    ):
        result = evaluate_fault_case(
            clean,
            fault_type
        )

        if result is None:
            lines.append(
                f" {fault_type}: unable to create this test."
            )
            continue

        results.append(result)

        lines.append(
            f" {fault_type.capitalize()} fault samples detected: "
            f"{result['fault_detected']} / "
            f"{result['fault_total']} "
            f"({format_percentage(result['fault_percentage'])})"
        )

        lines.append(
            f" Clean eligible samples wrongly rejected or alarmed: "
            f"{result['clean_false']} / "
            f"{result['clean_total']} "
            f"({format_percentage(result['clean_false_percentage'])})"
        )

        lines.append(
            f" Eligible gate rejections={result['gate_rejected']}; "
            f"gated alarm samples={result['gated_alarms']}; "
            f"ungated alarm samples={result['ungated_alarms']}"
        )

        lines.append("")

    lines.append(
        " Fault types were isolated to prevent cross-type overlap."
    )

    lines.append(
        " Results depend on the chosen synthetic fault magnitudes, "
        "durations and locations."
    )

    lines.append(
        " Synthetic results do not establish field or clinical performance."
    )

    return lines


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python analysis\\replay_eval_timestamped.py "
            "<csv_path> [output_directory]"
        )
        sys.exit(1)

    path = sys.argv[1]

    output_directory = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "."
    )

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Input CSV was not found: {path}"
        )

    df = pd.read_csv(
        path,
        low_memory=False
    )

    required = {
        "wall_clock_time",
        "bioelectric_raw"
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"CSV is missing required columns: "
            f"{sorted(missing)}"
        )

    df["t"] = pd.to_datetime(
        df["wall_clock_time"],
        format="mixed",
        errors="coerce"
    )

    invalid_timestamps = int(
        df["t"].isna().sum()
    )

    df = (
        df.dropna(subset=["t"])
        .sort_values("t")
    )

    fault_raw = df[
        (df["t"] >= FAULT_START)
        & (df["t"] <= FAULT_END)
    ]

    clean_raw = df[
        df["t"] >= CLEAN_START
    ]

    fault, fault_duplicates = prepare_segment(
        fault_raw
    )

    clean, clean_duplicates = prepare_segment(
        clean_raw
    )

    lines = [
        "TIMESTAMP-AWARE REPLAY EVALUATION",
        f"Input CSV: {path}",
        f"Invalid timestamps dropped: {invalid_timestamps}",
        (
            "Duplicate timestamp rows combined: "
            f"fault={fault_duplicates}, "
            f"clean={clean_duplicates}"
        ),
        f"Baseline window: previous {BASELINE_SECONDS:.0f} seconds",
        f"Minimum baseline samples: {MIN_N}",
        f"Long-gap reset threshold: > {LONG_GAP_SECONDS:.1f} seconds",
        (
            "Scored interval limit: "
            f"<= {MAX_SCORE_INTERVAL_SECONDS:.1f} seconds"
        ),
        "Rejected readings are excluded from the gated baseline.",
        "Only eligible intervals count toward alarm rates.",
        "",
    ]

    summarize_segment(
        "FAULT RECORDING",
        fault,
        lines
    )

    lines.append("")

    summarize_segment(
        "CLEAN RECORDING",
        clean,
        lines
    )

    lines.append("")

    lines.append(
        "[FIRST TWO HOURS OF CLEAN RECORDING]"
    )

    if len(clean) > 0:
        window_start = clean["t"].iloc[0]

        window_end = (
            window_start
            + pd.Timedelta(hours=FIRST_WINDOW_HOURS)
        )

        first_window = clean[
            clean["t"] < window_end
        ].copy()

        if len(first_window) == 0:
            lines.append(
                " No observations found in this window."
            )
        else:
            first_result = run_segment(
                first_window
            )

            lines.append(
                f" window={window_start} to {window_end}"
            )

            lines.append(
                f" rows={len(first_window)}; "
                f"eligible intervals="
                f"{int(eligible_mask(first_result).sum())}"
            )

            lines.append(
                " eligible alarm samples: "
                f"gated={alarm_sample_count(first_result['gated'], first_result['score_seconds'])}; "
                f"ungated={alarm_sample_count(first_result['ungated'], first_result['score_seconds'])}"
            )

            lines.append(
                " This is the first two hours of the clean recording, "
                "not the period immediately after the fault recording."
            )

    else:
        lines.append(
            " No clean recording rows were found."
        )

    lines.append("")

    lines.extend(
        run_injected_fault_test(clean)
    )

    lines.append("")

    lines.append(
        "[INTERPRETATION NOTES]"
    )

    lines.append(
        "Fault and clean recordings are evaluated independently."
    )

    lines.append(
        "The baseline uses a timestamp-based 1800-second window."
    )

    lines.append(
        "Baseline variance uses centered signal values for stability."
    )

    lines.append(
        "Long gaps reset the baselines and jump reference."
    )

    lines.append(
        "Only positive intervals up to 1.5 seconds count toward eligible time."
    )

    lines.append(
        "Alarm samples per hour and distinct alarm events are different metrics."
    )

    lines.append(
        "Deviation percentages across all rows include ineligible intervals."
    )

    lines.append(
        "Synthetic fault tests are isolated and do not establish field or clinical validation."
    )

    output = "\n".join(lines)

    print(output)

    os.makedirs(
        output_directory,
        exist_ok=True
    )

    output_path = os.path.join(
        output_directory,
        "replay_eval_timestamped_summary.txt"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(output + "\n")

    print(
        f"\nSummary saved to: {output_path}"
    )


if __name__ == "__main__":
    main()