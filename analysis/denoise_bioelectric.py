"""
PhytoSense++ - Stage 3: Denoising pipeline for bioelectric_raw
----------------------------------------------------------------
Input : phytosense_trial_log.csv  (columns: wall_clock_time, uptime_ms,
        bioelectric_raw, lo_plus, lo_minus, soil_raw, temp_c,
        humidity_pct, pressure_hpa, reading_status)
Output: bioelectric_denoised.csv  (adds 'bioelectric_denoised' column)
        two PNG plots (full trial, and zoomed on the 21:30 leaf-damage event)

IMPORTANT DATA-REALITY NOTE (read before running):
    The logger writes ~1 sample/second (median dt = 1000 ms, confirmed by
    inspecting uptime_ms). That means Nyquist frequency = 0.5 Hz.
    A 50/60 Hz mains notch filter is *meaningless* on this file -- 50/60 Hz
    can't even be represented in a 1 Hz-sampled signal, and there's nothing
    for a notch at that frequency to remove. If you build one anyway it will
    do literally nothing (silently), which is worse than leaving it out.
    Real "oversampling" (sample the ADC fast on the ESP32, average N raw
    samples, log 1 value) also has to happen ON THE FIRMWARE, not after the
    fact on an already-decimated CSV -- you can't manufacture samples that
    were never taken.

    What this script does instead, matched to what's actually in the CSV:
      1. Drop the pre-trial saturation stretch (bioelectric_raw pinned at
         4095), per Master Reference Section 8: official trial start is
         2026-09-12 16:33 (electrode reattachment).
      2. Despike: rolling median filter to kill the ADC/contact glitch
         spikes (short, isolated jumps to/near 4095).
      3. Band-limit: Butterworth low-pass (removes ADC-noise energy above
         the frequency range that plant bioelectric events occupy) +a
         gentle high-pass (removes slow DC baseline drift) = effectively a
         bandpass, implemented as two explicit filters so you can tune each
         independently.
      4. "Oversampling" proxy: rolling-mean smoothing (boxcar), labeled
         honestly as a smoothing/SNR step, not true oversampling.
      5. 50/60 Hz notch: included but SKIPPED with a clear printed reason
         (function is there, ready to use once firmware logs at >=200 Hz).
"""

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, medfilt, iirnotch
import matplotlib.pyplot as plt

# ---------------------------------------------------------------- settings
CSV_PATH = "phytosense_trial_log.csv"
TRIAL_START = "2026-09-12 16:33:00"     # per Master Reference Sec 8 (reattachment)
LEAF_DAMAGE_TS = "2026-09-12 21:30:00"  # per Master Reference Sec 8
DESPIKE_WINDOW = 5          # samples (odd number), median filter
LOWPASS_CUTOFF_HZ = 0.20    # smooths ADC-level noise, keeps 1-30s transients
HIGHPASS_CUTOFF_HZ = 0.0005 # removes slow baseline drift only (~33 min period)
OVERSAMPLE_WINDOW = 5       # rolling-mean "software oversampling" window

# ------------------------------------------------------------ 1. load data
df = pd.read_csv(CSV_PATH)
df["wall_clock_time"] = pd.to_datetime(df["wall_clock_time"])
df = df.sort_values("wall_clock_time").reset_index(drop=True)

before_rows = len(df)
df = df[df["wall_clock_time"] >= TRIAL_START].reset_index(drop=True)
print(f"Dropped {before_rows - len(df)} rows before official trial start ({TRIAL_START})")

# confirm actual sample rate from the data itself, don't assume
dt_ms = df["wall_clock_time"].diff().dt.total_seconds().mul(1000).dropna()
fs = 1000.0 / dt_ms.median()
print(f"Detected sample rate: {fs:.3f} Hz (median dt = {dt_ms.median():.0f} ms) -> Nyquist = {fs/2:.3f} Hz")

raw = df["bioelectric_raw"].to_numpy(dtype=float)

# ------------------------------------------------------------ 2. despike
despiked = medfilt(raw, kernel_size=DESPIKE_WINDOW)

# ------------------------------------------------------------ 3. bandpass
nyq = fs / 2.0


def butter_filter(x, cutoff_hz, fs, order, btype):
    cutoff_hz = min(cutoff_hz, fs / 2 * 0.99)  # stay below Nyquist
    b, a = butter(order, cutoff_hz / (fs / 2), btype=btype)
    return filtfilt(b, a, x)


lowpassed = butter_filter(despiked, LOWPASS_CUTOFF_HZ, fs, order=4, btype="low")
bandpassed = butter_filter(lowpassed, HIGHPASS_CUTOFF_HZ, fs, order=2, btype="high")
# re-add the mean removed by the high-pass so the signal stays in raw ADC units
bandpassed = bandpassed - bandpassed.mean() + despiked.mean()

# ------------------------------------------------------- 4. "oversampling"
oversampled = pd.Series(bandpassed).rolling(
    OVERSAMPLE_WINDOW, center=True, min_periods=1
).mean().to_numpy()

df["bioelectric_denoised"] = oversampled


# --------------------------------------------------- 5. notch (not applied)
def notch_50_60(x, fs, freq=50.0, Q=30.0):
    """50/60 Hz notch -- only valid once fs > 100-120 Hz. Not called here."""
    b, a = iirnotch(freq / (fs / 2), Q)
    return filtfilt(b, a, x)


if nyq < 60:
    print(f"Skipping 50/60 Hz notch: Nyquist ({nyq:.3f} Hz) is far below 50/60 Hz "
          f"-- there is no mains-hum content in this signal to remove. "
          f"Apply notch_50_60() on-device if firmware ever logs at >=200 Hz.")

# ------------------------------------------------------------- 6. save csv
out_cols = ["wall_clock_time", "bioelectric_raw", "bioelectric_denoised"]
df[out_cols].to_csv("bioelectric_denoised.csv", index=False)
print("Saved bioelectric_denoised.csv")

# ------------------------------------------------------------------ plots
plt.figure(figsize=(14, 5))
plt.plot(df["wall_clock_time"], df["bioelectric_raw"], lw=0.4, alpha=0.5, label="raw")
plt.plot(df["wall_clock_time"], df["bioelectric_denoised"], lw=1.2, label="denoised")
plt.axvline(pd.Timestamp(LEAF_DAMAGE_TS), color="red", ls="--", lw=1, label="leaf-damage stimulus (21:30)")
plt.title("PhytoSense++ bioelectric_raw - full trial, before vs after denoising")
plt.xlabel("time")
plt.ylabel("ADC counts (12-bit, 0-4095)")
plt.legend()
plt.tight_layout()
plt.savefig("bioelectric_full_trial.png", dpi=150)
plt.close()

# zoom +/- 30 min around the leaf-damage event, this is the key sanity check
zoom_lo = pd.Timestamp(LEAF_DAMAGE_TS) - pd.Timedelta(minutes=30)
zoom_hi = pd.Timestamp(LEAF_DAMAGE_TS) + pd.Timedelta(minutes=30)
zoom = df[(df["wall_clock_time"] >= zoom_lo) & (df["wall_clock_time"] <= zoom_hi)]

plt.figure(figsize=(14, 5))
plt.plot(zoom["wall_clock_time"], zoom["bioelectric_raw"], lw=0.6, alpha=0.5, label="raw")
plt.plot(zoom["wall_clock_time"], zoom["bioelectric_denoised"], lw=1.6, label="denoised")
plt.axvline(pd.Timestamp(LEAF_DAMAGE_TS), color="red", ls="--", lw=1.2, label="leaf-damage stimulus (21:30)")
plt.title("Zoom: +/-30 min around leaf-damage event - transient survives denoising?")
plt.xlabel("time")
plt.ylabel("ADC counts (12-bit, 0-4095)")
plt.legend()
plt.tight_layout()
plt.savefig("bioelectric_zoom_leafdamage.png", dpi=150)
plt.close()

print("Saved bioelectric_full_trial.png and bioelectric_zoom_leafdamage.png")
