# PhytoSense++

**A multimodal edge-AI framework for early plant stress prediction, explainable diagnosis, autonomous precision irrigation, and predictive crop-health analytics.**

*Embedded Systems Project — VIT Chennai — Faculty-Supported Team of 3*

> 🔒 **Private repository.** Do not make public and do not submit any associated paper until the provisional patent has been filed. See [IP Status](#ip-status--publication-timeline) below.

---

## Table of Contents

- [Overview](#overview)
- [Core Novelty](#core-novelty)
- [System Architecture](#system-architecture)
- [Hardware](#hardware)
- [Software Stack](#software-stack)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Build & Verification Workflow](#build--verification-workflow)
- [Project Roadmap](#project-roadmap)
- [Documentation](#documentation)
- [Team](#team)
- [IP Status & Publication Timeline](#ip-status--publication-timeline)
- [License](#license)

---

## Overview

PhytoSense++ is a non-invasive, clip-on device that reads a plant's own bioelectric signal (via surface electrodes on leaf/stem) alongside soil moisture, temperature, humidity, and light. Instead of relying on a fixed population threshold, it learns that *specific* plant's normal signal pattern on-device and flags deviation as early stress — before visible symptoms appear — then closes the loop with autonomous irrigation and forward-looking health forecasts.

## Core Novelty

| # | Contribution | Description |
|---|---|---|
| 1 | **Personalized, bounded-memory baseline learning** | A fixed-size, self-refreshing model of one plant's normal signal — not a population average. |
| 2 | **Electrode-contact-quality self-diagnosis** | An ECG/EEG impedance self-check technique applied to plant tissue for the first time, separating genuine stress from bad electrode contact. |
| 3 | **On-device explainable diagnosis** | Lightweight feature-attribution (embedded-feasible proxy for SHAP/Grad-CAM) that names which signal drove each alert. |
| 4 | **Autonomous precision irrigation + predictive analytics** | Closed-loop relay/pump actuation driven by the fused stress classifier, plus a short-horizon forecasting layer surfaced via a BLE/Wi-Fi dashboard. |

No reviewed system currently combines all four in a single field-deployable embedded pipeline — this combination is the project's novelty claim for both the research paper and the patent filing.

## System Architecture

```
 Sensing Layer
   Bioelectric (AD8232) · Soil moisture · Temp/Humidity (BME280) · Light (BH1750)
        |
 Signal Conditioning
   Denoising -> Feature extraction -> Electrode-contact-quality self-check
        |
 On-Device Models (TensorFlow Lite Micro)
   Personalized baseline · Fusion classifier · Explainability · Forecasting
        |
 Decision & Control Logic
   Closed-loop irrigation trigger = stress classification + soil moisture + forecast
        |
   +----------------+------------------+
   |                |                  |
Local Output    Actuation        Remote Output
OLED + buzzer   Relay->Pump->Tube  BLE/Wi-Fi -> Dashboard
                -> Plant
```

Full diagrams (master hardware view, phase-by-phase wiring, software data flow) are in [`docs/PhytoSense_Connection_Diagrams.docx`](./docs).

## Hardware

**Compute:** ESP32-S3 (N8R8 PSRAM) — central compute, running inference and control logic
**Secondary:** ESP32 (38-pin) — early bring-up / dev board

| Subsystem | Components |
|---|---|
| Bioelectric sensing | AD8232 amplifier, Ag/AgCl electrode discs, ADS1115 16-bit ADC |
| Environmental sensing | BME280 (temp/humidity), BH1750 (light), capacitive soil moisture sensor |
| Irrigation actuation | 1-channel 5V relay, 6V DC water pump, 1m tube |
| Local I/O | 0.96" OLED display, 5V buzzer |
| Power | 6V 100mA solar panel, TP4056 USB-C charger, 3800mAh Li-ion battery, LM2596 buck converter |
| Prototyping | MB102 breadboard, dot PCB (6×4cm), jumper wires |

Full BOM with sourcing notes: [`docs/PhytoSense_Execution_Plan.docx`](./docs)
Full pin-level connection table: [`docs/PhytoSense_Connection_Diagrams.docx`](./docs)

### Key pin map (ESP32-S3)

| Pin | Connects to | Type |
|---|---|---|
| GPIO8 | I2C SDA — ADS1115, BME280, BH1750, OLED | I2C |
| GPIO9 | I2C SCL — ADS1115, BME280, BH1750, OLED | I2C |
| GPIO4 | AD8232 LO+ (leads-off detect) | Digital in |
| GPIO5 | AD8232 LO- (leads-off detect) | Digital in |
| GPIO6 | Relay IN (irrigation control) | Digital out |
| GPIO7 | Buzzer + | Digital out |

> ⚠️ Confirm these against your specific board's silkscreen before wiring — some ESP32-S3 breakouts remap GPIOs, and GPIO8/9 can be reserved for onboard flash on certain variants.

## Software Stack

| Layer | Tools |
|---|---|
| Firmware | PlatformIO (VS Code) / ESP-IDF, Arduino libraries (Adafruit BME280, ADS1X15, U8g2/SSD1306, ArduinoJson) |
| On-device ML | TensorFlow Lite Micro + ESP-NN |
| Model prototyping | Python, scikit-learn / TensorFlow, XGBoost |
| Explainability | Permutation-importance / decision-path attribution |
| Data & dashboard | SD/SPIFFS or Firebase/ThingSpeak, BLE/Wi-Fi companion app |
| Analysis | Python (pandas, matplotlib) |
| Design | KiCad (schematic/PCB), Fritzing (breadboard docs), draw.io/Figma (diagrams) |
| Simulation | [Wokwi](https://wokwi.com) — ESP32-S3, I2C bus, and relay logic verified pre-hardware |

## Repository Structure

```
phytosense-plus-plus/
├── firmware/     PlatformIO project — one module per sensor
├── hardware/     Schematics, wiring diagrams, BOM.csv, KiCad files
├── data/         Logged sensor readings, by test date and plant group
├── analysis/     Python scripts/notebooks generating paper figures
├── dashboard/    BLE/Wi-Fi companion app (mobile/web)
├── docs/         Execution plan, connection diagrams, replication guide, drafts
├── .gitignore
└── README.md
```

## Getting Started

```bash
git clone <this-repo-url>
cd phytosense-plus-plus
```

**Firmware:**
```bash
cd firmware
pio run              # build
pio run -t upload    # flash to ESP32-S3
pio device monitor    # serial output
```

**Before touching real hardware:** simulate the I2C bus and relay logic in [Wokwi](https://wokwi.com) — see the verification checklist in `docs/`.

## Build & Verification Workflow

Recommended order, to catch mistakes before they're physical:

1. **Wokwi** — simulate firmware logic (I2C addressing, relay trigger conditions)
2. **Breadboard** — wire against `docs/PhytoSense_Connection_Diagrams.docx`, verify power rail with a multimeter before connecting sensors
3. **Fritzing** — produce clean documentation once the design is locked
4. **KiCad** — final schematic + PCB layout for the soldered build

## Project Roadmap

| Phase | Focus |
|---|---|
| 1 | Design finalization, BOM ordering, literature grounding |
| 2 | Analog front-end bring-up (AD8232 + ADS1115), invention disclosure drafted |
| 3 | Sensor + irrigation deployment across 3 plant test groups, **provisional patent filed** |
| 4 | Software pipeline: fusion classifier, explainability, forecasting |
| 5 | Full integration, dashboard, PCB, paper submission, repo made public |

Full timeline: [`docs/PhytoSense_Execution_Plan.docx`](./docs)

## Documentation

- [`docs/PhytoSense_Execution_Plan.docx`](./docs) — complete build/patent/paper execution plan
- [`docs/PhytoSense_Connection_Diagrams.docx`](./docs) — pin diagrams, wiring, software architecture
- Team task board, work log, patent contribution log, decisions log — tracked outside git (see team spreadsheet)

## Team

Three-person team, VIT Chennai, Embedded Systems course project — faculty-supported. Work is shared across all members rather than fixed hardware/software roles; see the Patent Contribution Log for per-idea attribution.

## IP Status & Publication Timeline

**Provisional patent filing in progress.**

- This repository must remain **private** until the provisional patent application has been filed.
- The associated research paper must not be submitted to any venue before filing, for the same reason.
- Once the provisional is filed, the repository may be made public and the paper submitted, per the team's execution plan.
- See `docs/PhytoSense_Execution_Plan.docx` for the full patent and paper filing timeline, and the team's Patent Contribution Log for per-idea inventorship records.

## License

**TBD** — to be decided *after* the provisional patent is filed, since licensing terms interact with IP rights. Do not add a license file before that point.
