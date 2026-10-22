# PhytoSense++

**A low-cost embedded system that reads a plant's own bioelectric signal, checks its quality on the device, learns that plant's normal behaviour in a fixed amount of memory, and flags sustained deviations.**

_Embedded Systems Project — VIT Chennai — faculty-supported team of 3_

> 🔒 **Private repository.** Keep private until the paper decision is made (see [Status](#status)).

---

## 1. What works today (honest status)

| Capability | Status | Evidence |
| --- | --- | --- |
| Bioelectric acquisition (AD8232 → ESP32-S3 ADC, 20× oversampling per 1 s sample) | ✅ Working | `firmware/src/main.cpp`, `data/` |
| Signal-quality gate (`contact`, `rail_hi`, `rail_lo`, `flat`, `jump`) | ✅ Working | `analysis/replay_eval.py`, dashboard |
| Bounded-memory personalised baseline (ring buffer of the last 1800 good samples, 7.2 KB) | ✅ Working | firmware + `analysis/window_sweep.py` |
| Deviation alert with persistence rule (\|z\| > 3 for 10 consecutive good samples) | ✅ Builds for N16R8; validated offline by replay; not yet run on the device | `analysis/benchmark.py`, `analysis/alarm_tuning.py` |
| Baseline reset after 10 min of bad data | ✅ Firmware only (not in the benchmark) | `firmware/src/main.cpp` |
| Environment sensing (DHT11 temperature/humidity, BMP280 pressure) and microSD CSV logging | ✅ Working | `data/*.csv` |
| Reliability analysis of logged runs | ✅ Done | `analysis/reliability_report.py` |
| Replay dashboard (gate, baseline band, alerts, fault injection) | ✅ Working | `dashboard/` |
| Detector comparison benchmark (baseline, winsorised, freeze-on-deviation, CUSUM, Page-Hinkley, stability-based re-learn) | ✅ Done, reproducible | `analysis/benchmark.py`, `analysis/tradeoff.py` |
| Environment compensation (regression on temperature/humidity/pressure) | ❌ Negative result: unstable across days, higher false alarms | `analysis/env_compensated*.py` |
| Soil-moisture channel | ⚠️ Not validated — the reading tracks the bioelectric channel (r ≈ 0.98) | see Limitations |
| Buzzer alert | ⚙️ Code present, disabled during long recordings (`ENABLE_BUZZER 0`) | `firmware/src/buzzer.cpp` |
| Relay / pump irrigation control | ⚙️ Driver present, **not wired into the main loop** | `firmware/src/relay_control.cpp` |
| Explainable diagnosis, forecasting, on-device TensorFlow Lite Micro model | 🔭 Future work — not implemented | — |
| Detection of real plant stress events (leaf damage, drought) | 🔭 Not yet validated — see Limitations | `analysis/event_eval.py` |

## 2. Key results

### 2.1 Firmware footprint (ESP32-S3, N16R8, `esp32-s3-n16r8` env)

| Resource | Used | Total | Share |
| --- | --- | --- | --- |
| RAM (`.dram0.data` + `.dram0.bss`) | 27,500 B | 327,680 B | 8.4% |
| Flash (app image) | 362,837 B | 6,553,600 B (app partition, `default_16MB.csv`) | 5.5% |

Measured with `pio run` (PlatformIO `checkprogsize`). Build confirmed with `--flash_size 16MB`.

### 2.2 Other results

| Result | Value | How measured |
| --- | --- | --- |
| Baseline memory | 7.2 KB (1800 × float32), constant for any run length | design |
| Long-run stability | 10.1 h continuous run, **0 reboots**, 99.1% availability (earlier firmware: a reboot about every 30 s) | `analysis/reliability_report.py` |
| False alarms (single-sample rule) | about 29 / hour with \|z\| > 3 on one sample | offline replay of ≈ 18 h of clean, unlabelled recordings |
| False alarms (persistence rule) | about 0.4 / hour with the 10-sample persistence rule | same replay |
| Catch rate at +6 SD (synthetic steps, 29 events) | 90% with 9 s latency (earlier protocol) | firmware-mirror replay, `analysis/window_sweep.py` |
| Window size | Plateau between 5 and 30 min. 1–2 min is unstable; ≥ 1 h loses sensitivity because slow drift inflates the SD. A 10-min window needs only 2.4 KB | `analysis/window_sweep.py` |
| Fault handling | Railed or invalid stretches are rejected by the gate and never update the baseline; no alerts are raised on them | `analysis/replay_eval.py`, dashboard fault injection |

### 2.3 Detector benchmark (current protocol)

The benchmark compares detectors on the same synthetic event streams, with the same scoring rule and the same threshold-selection procedure.

- **Detectors:** firmware baseline; winsorised update (clip to ±3 SD); freeze-on-deviation; CUSUM (k = 0.5, h ∈ {8…512}); Page-Hinkley (δ = 0.5, λ ∈ {10…640}); stability-based re-learn rule (BAND ∈ {1.0, 2.0} SD, W = 60 post-onset samples, T ∈ {600, 900, 1800} samples).
- **Events:** step +6 SD (60 s); sustained +3, +4, +6 SD (600 s); drift +6 SD (1800 s ramp); spike +10 SD (3 s); railed (60 s); permanent +6 SD from onset to end.
- **Scoring:** excess = hit rate − clean-stream alert rate in the same window, so background false alarms do not inflate detection.
- **Threshold selection:** leave-one-day-out. On training days, pick the setting with the highest mean excess under a false-alarm budget of ≤ 1/h. The held-out day is never used for selection.
- **Uncertainty:** bootstrap over days (2000 draws, seed 0).
- **Amplitude scale:** MAD-based. Events whose shifted samples hit ADC rails are dropped and counted.

Results (fill from `out/bench_summary.csv`, `bench_folds.csv`, `bench_cost.csv`):

| Detector | Transient recovery | Permanent-shift absorption | False alarms / h | Memory |
| --- | --- | --- | --- | --- |
| Firmware baseline | [TBD] | [TBD] | [TBD] | 7.2 KB |
| Freeze-on-deviation | [TBD] | [TBD] | [TBD] | 7.2 KB |
| CUSUM | [TBD] | [TBD] | [TBD] | [TBD] |
| Page-Hinkley | [TBD] | [TBD] | [TBD] | [TBD] |
| Stability-based re-learn | [TBD] | [TBD] | [TBD] | [TBD] |

Summary of what the benchmark shows so far: CUSUM and Page-Hinkley, and the freeze rule, recover from transients more completely than the stability rule. The stability rule has the lowest false-alarm rate and absorbs permanent shifts faster than freeze-on-deviation. It does not dominate on every metric.

## 3. System overview

```
AD8232 + Ag/AgCl electrodes ──► ESP32-S3 ADC (GPIO2) ──┐
DHT11 (GPIO15), BMP280 (I2C 0x76/0x77) ────────────────┤
Leads-off pins LO+ (GPIO4) / LO- (GPIO5) ──────────────┤
                                                       ▼
        Signal-quality gate ──► bounded-memory baseline (ring buffer) ──► z-score
                                                       │
                              persistence rule (10 consecutive samples)
                                                       ▼
                    status: cold_start | low_confidence | ok | deviation
                                                       ▼
                         microSD CSV log (CS = GPIO10) · serial · buzzer (optional)
```

**Core idea:** the gate decides whether a sample may be trusted at all, so bad electrode contact or a railed front-end cannot corrupt the learned baseline or trigger false stress alerts.

### Pin map (as used in firmware)

| Pin | Function |
| --- | --- |
| GPIO2 | AD8232 output (bioelectric) |
| GPIO1 | Soil sensor input (not validated) |
| GPIO4 / GPIO5 | AD8232 LO+ / LO- (leads-off) |
| GPIO8 / GPIO9 | I2C SDA / SCL (BMP280) |
| GPIO15 | DHT11 |
| GPIO10 | microSD chip-select |
| GPIO6 | Relay IN (driver present, unused) |
| GPIO7 | Buzzer (disabled by default) |

### Board

**ESP32-S3 N16R8** (16 MB flash, 8 MB PSRAM). PlatformIO env `esp32-s3-n16r8`: `board_upload.flash_size = 16MB`, `board_build.partitions = default_16MB.csv`, `board_build.arduino.memory_type = qio_opi`. The firmware does not allocate PSRAM; all buffers are static. The build log still prints the board-definition name "N8", which is cosmetic and comes from the stock board JSON.

## 4. Repository structure

```
firmware/    PlatformIO project (main loop, SD logger, buzzer, relay driver)
analysis/    benchmark, tradeoff, env_compensated*, reliability_report, event_eval,
             alarm_tuning, window_sweep, replay_eval
dashboard/   Streamlit replay dashboard (app.py + engine.py)
data/        Logged recordings (CSV)
docs/        Execution plan, connection diagrams, master document
hardware/    Circuit diagrams and wiring images
paper/       IEEE conference paper (data/ and figures/ hold frozen outputs)
sim/         Wokwi sketch
out/         Generated results (git-ignored)
```

## 5. How to run

**Firmware**

```bash
cd firmware
pio run                 # build only
pio run -t upload       # flash to ESP32-S3 (needs the board connected)
pio device monitor      # serial output at 115200
```

**Analyses** (from the repo root; need `pandas numpy matplotlib`)

```bash
python analysis/benchmark.py            # detector comparison (run in background; takes several minutes)
python analysis/tradeoff.py             # trade-off figure and drop-one-day sensitivity
python analysis/reliability_report.py   # uptime, gaps, reboots, usable-signal per day
python analysis/alarm_tuning.py         # false alarms vs catch rate, threshold x persistence
python analysis/window_sweep.py         # baseline window size vs memory and accuracy
python analysis/run_revised_audit.py    # revised data audit, fault replay, gate ablation, simulation, focused tests
```

The revised audit writes separate artifacts under `out/revised/` and `reports/`; it does not overwrite the original benchmark outputs. See `reports/final_research_report.md` for analyses that remain incomplete, including the elapsed-time rerun of the six-detector benchmark.

**Dashboard**

```bash
python -m pip install -r dashboard/requirements.txt
python -m streamlit run dashboard/app.py
```

Demo moves: pick the _Oct 13-14 railed front-end_ dataset to see the gate reject 83% of samples; on _v7 trial_ inject a **railed** fault (rejected, no alert) and a **step +6 SD** (alert after about 10 samples).

## 6. Data

| File | Content |
| --- | --- |
| `data/phytosense_trial_log.csv` | Main log; early firmware, includes a railed front-end period; only ~16 h are clean |
| `data/trial_v7.csv` | 2.7 h run on firmware v7 |
| `data/preflight_90min.csv` | 2.6 h preflight run |

The main log spans several recording days (not continuous weeks). Early rows contain implausible temperature and pressure values from an earlier sensor fault; the analyses exclude them.

## 7. Limitations (please read)

- **Stress detection on real plants is not yet validated.** The leaf-cut on 18 Oct was done before logging resumed, so there is no pre-event baseline; the 12 Sep event shows no clear transient in noisy data. A properly logged repeat (≥ 1 h before, ≥ 1 h after, noted timestamp) is the main open experiment.
- **Benchmark events are synthetic.** Injected shifts do not capture real plant physiology. Detector rankings may change on real stress data.
- **Environment compensation does not generalise across days.** Linear regression on temperature, humidity and pressure gave unstable coefficients and higher false alarms under leave-one-day-out. It is reported as a negative result, not used in the firmware.
- **The soil channel is unreliable.** It reads about 85 / 4095 and tracks the bioelectric channel; it is excluded from all results and from the dashboard.
- **Closed-loop irrigation is not implemented in the main loop.** Only the relay driver exists.
- **Persistence rule and stability-based re-learn:** the persistence rule builds but has not been run on the device; the stability-based rule exists only in the offline benchmark.
- **Clean data totals about 21 h** (about 16 h in the main log); results are preliminary.
- **Few recording days.** Threshold selection and the bootstrap use only the available days, so the confidence intervals are wide.

## 8. Future work

Closed-loop irrigation driven by a validated soil sensor; on-device explainability (which feature drove the alert); short-horizon forecasting; a repeated, labelled leaf-damage and drought experiment with latency measurements; power-consumption measurement and battery-life estimate; on-device run of the persistence rule and of the stability-based re-learn rule.

## 9. Documentation

- `docs/PhytoSense_Execution_Plan_REVISED.docx` — build and paper plan
- `docs/PhytoSense_Connection_Diagrams.docx` — pin diagrams and wiring
- `docs/PhytoSense_Master_Document_REVISED.docx` — master reference

## 10. Team

Three-person team, VIT Chennai, Embedded Systems course project, faculty-supported. Work is shared across members.

## Status

- **No patent filing.** The team has decided not to file a provisional patent.
- **Paper:** IEEE conference paper in preparation. Do not submit to any venue until the team has confirmed the author list, AI-assistance disclosure, and venue policy.
- **Visibility:** the repository stays private until the paper decision is made. Confirm the decision before making it public.

## License

**TBD.** Decide before adding a license file.
