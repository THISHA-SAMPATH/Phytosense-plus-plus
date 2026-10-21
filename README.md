# PhytoSense++

**A low-cost embedded system that reads a plant's own bioelectric signal, checks its quality on the device, learns that plant's normal behaviour in a fixed amount of memory, and flags sustained deviations.**

_Embedded Systems Project — VIT Chennai — faculty-supported team of 3_

> 🔒 **Private repository.** Do not make it public, and do not submit any associated paper, until the provisional patent has been filed (see [IP status](#ip-status)).

---

## 1. What works today (honest status)

| Capability                                                                                | Status                                                                   | Evidence                                               |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------ |
| Bioelectric acquisition (AD8232 → ESP32-S3 ADC, 20× oversampling per 1 s sample)          | ✅ Working                                                               | `firmware/src/main.cpp`, `data/`                       |
| Signal-quality gate (`contact`, `rail_hi`, `rail_lo`, `flat`, `jump`)                     | ✅ Working                                                               | `analysis/replay_eval.py`, dashboard                   |
| Bounded-memory personalised baseline (ring buffer of the last 1800 good samples, 7.2 KB)  | ✅ Working                                                               | firmware + `analysis/window_sweep.py`                  |
| Deviation alert with persistence rule (z > 3 for 10 consecutive good samples)             | ✅ Compiles; validated offline by replay; not yet run on the device      | `analysis/alarm_tuning.py`, `analysis/window_sweep.py` |
| Environment sensing (DHT11 temperature/humidity, BMP280 pressure) and microSD CSV logging | ✅ Working                                                               | `data/*.csv`                                           |
| Reliability analysis of logged runs                                                       | ✅ Done                                                                  | `analysis/reliability_report.py`                       |
| Replay dashboard (gate, baseline band, alerts, fault injection)                           | ✅ Working                                                               | `dashboard/`                                           |
| Soil-moisture channel                                                                     | ⚠️ Not validated — the reading tracks the bioelectric channel (r ≈ 0.98) | see Limitations                                        |
| Buzzer alert                                                                              | ⚙️ Code present, disabled during long recordings (`ENABLE_BUZZER 0`)     | `firmware/src/buzzer.cpp`                              |
| Relay / pump irrigation control                                                           | ⚙️ Driver present, **not wired into the main loop**                      | `firmware/src/relay_control.cpp`                       |
| Explainable diagnosis, forecasting, on-device TensorFlow Lite Micro model                 | 🔭 Future work — not implemented                                         | —                                                      |
| Detection of real plant stress events (leaf damage, drought)                              | 🔭 Not yet validated — see Limitations                                   | `analysis/event_eval.py`                               |

## 2. Key results

| Result                                           | Value                                                                                                                                                                 | How measured                                             |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Firmware footprint (ESP32-S3)                    | RAM 27,500 B (8.4%), Flash 362,893 B (10.9% of the app partition)                                                                                                     | `pio run`                                                |
| Baseline memory                                  | 7.2 KB (1800 × float32), constant for any run length                                                                                                                  | design                                                   |
| Long-run stability                               | 10.1 h continuous run, **0 reboots**, 99.1% availability (earlier firmware: a reboot about every 30 s)                                                                | `analysis/reliability_report.py`                         |
| False alarms                                     | about 29 / hour with a single-sample z > 3 rule → about 0.4 / hour with the 10-sample persistence rule                                                                | offline replay of ≈ 18 h of clean, unlabelled recordings |
| Catch rate at +6 SD (synthetic steps, 29 events) | 90% with 9 s latency                                                                                                                                                  | firmware-mirror replay, `analysis/window_sweep.py`       |
| Window size                                      | Results are on a plateau between 5 and 30 min. 1–2 min is unstable, and ≥ 1 h loses sensitivity because slow drift inflates the SD. A 10-min window needs only 2.4 KB | `analysis/window_sweep.py`                               |
| Fault handling                                   | Railed or invalid stretches are rejected by the gate and never update the baseline; no alerts are raised on them                                                      | `analysis/replay_eval.py`, dashboard fault injection     |

Catch rates use **synthetic injected steps**. False-alarm figures are on **unlabelled** data, so real environmental events are counted as false alarms.

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

| Pin           | Function                          |
| ------------- | --------------------------------- |
| GPIO2         | AD8232 output (bioelectric)       |
| GPIO1         | Soil sensor input (not validated) |
| GPIO4 / GPIO5 | AD8232 LO+ / LO- (leads-off)      |
| GPIO8 / GPIO9 | I2C SDA / SCL (BMP280)            |
| GPIO15        | DHT11                             |
| GPIO10        | microSD chip-select               |
| GPIO6         | Relay IN (driver present, unused) |
| GPIO7         | Buzzer (disabled by default)      |

> Confirm the board variant: PlatformIO resolves the board to **ESP32-S3-DevKitC-1-N8 (8 MB flash, no PSRAM)**, while older notes mention N8R8 / N16R8. Check the chip label and keep `platformio.ini` consistent with it.

## 4. Repository structure

```
firmware/    PlatformIO project (main loop, SD logger, buzzer, relay driver)
analysis/    replay_eval, reliability_report, event_eval, alarm_tuning, window_sweep, ...
dashboard/   Streamlit replay dashboard (app.py + engine.py)
data/        Logged recordings (CSV)
docs/        Execution plan, connection diagrams, master document
hardware/    Circuit diagrams and wiring images (add exported diagrams here)
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
python analysis/reliability_report.py   # uptime, gaps, reboots, usable-signal per day
python analysis/event_eval.py           # plots around the leaf-cut events
python analysis/alarm_tuning.py         # false alarms vs catch rate, threshold x persistence
python analysis/window_sweep.py         # baseline window size vs memory and accuracy
```

**Dashboard**

```bash
python -m pip install -r dashboard/requirements.txt
python -m streamlit run dashboard/app.py
```

Demo moves: pick the _Oct 13-14 railed front-end_ dataset to see the gate reject 83% of samples; on _v7 trial_ inject a **railed** fault (rejected, no alert) and a **step +6 SD** (alert after about 10 samples).

## 6. Data

| File                            | Content                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| `data/phytosense_trial_log.csv` | Main log; early firmware, includes a railed front-end period; only ~16 h are clean |
| `data/trial_v7.csv`             | 2.7 h run on firmware v7                                                           |
| `data/preflight_90min.csv`      | 2.6 h preflight run                                                                |

The main log spans several recording days (not continuous weeks). Early rows contain implausible temperature and pressure values from an earlier sensor fault; the analyses exclude them.

## 7. Limitations (please read)

- **Stress detection on real plants is not yet validated.** The leaf-cut on 18 Oct was done before logging resumed, so there is no pre-event baseline; the 12 Sep event shows no clear transient in noisy data. A properly logged repeat (≥ 1 h before, ≥ 1 h after, noted timestamp) is the main open experiment.
- **The soil channel is unreliable.** It reads about 85 / 4095 and tracks the bioelectric channel; it is excluded from all results and from the dashboard.
- **Closed-loop irrigation is not implemented in the main loop.** Only the relay driver exists.
- Persistence rule: not yet flashed to or tested on the device.
- Thresholds were tuned and evaluated on the same recordings; a held-out split is future work.
- Clean data totals about 21 h; results are preliminary.

## 8. Future work

Closed-loop irrigation driven by a validated soil sensor; on-device explainability (which feature drove the alert); short-horizon forecasting; a repeated, labelled leaf-damage and drought experiment with latency measurements; power-consumption measurement and battery-life estimate; held-out evaluation and comparison against Hampel, EWMA and median/MAD detectors.

## 9. Documentation

- `docs/PhytoSense_Execution_Plan_REVISED.docx` — build, patent and paper plan
- `docs/PhytoSense_Connection_Diagrams.docx` — pin diagrams and wiring
- `docs/PhytoSense_Master_Document_REVISED.docx` — master reference

## 10. Team

Three-person team, VIT Chennai, Embedded Systems course project, faculty-supported. Work is shared across members; per-idea attribution is kept in the team's Patent Contribution Log.

## IP status

**Provisional patent filing in progress.** The repository must stay private, and the associated paper must not be submitted to any venue, until the provisional application has been filed. See the Execution Plan for the timeline.

## License

**TBD** — to be decided after the provisional patent is filed. Do not add a license file before then.
