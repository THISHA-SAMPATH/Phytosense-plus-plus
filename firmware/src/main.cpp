// main.cpp — PhytoSense++ Phase 4 data-logging firmware
//
// What this file DOES right now:
//   - Reads bioelectric signal (ADS1115 A0) + electrode contact status (LO+/LO-)
//   - Reads soil moisture (ADS1115 A1), temp+pressure (BMP280), humidity (DHT22),
//     light (BH1750)
//   - Applies the cold-start / low-confidence failure-mode states from
//     Connection Diagrams Sec 5.1 (basic version — flags only, doesn't act yet)
//   - Logs every sample to Serial AND microSD as one CSV row
//
// What this file DELIBERATELY DOES NOT do yet (Phase 4 next steps, not this file):
//   - Denoising/filtering (bandpass, notch, oversampling)
//   - The personalized bounded-memory baseline model
//   - Confidence-gated update logic (beyond the basic LO+/- check below)
//   - Fusion classifier, explainability, irrigation control, forecasting
// Those are separate modules to be added on top of this raw logging pipeline —
// don't skip ahead and start the plant trial only once THIS file is verified
// producing sane numbers with a live electrode on a real leaf.

#include <Arduino.h>
#include <Wire.h>

// --- Forward declarations from other driver files ---
bool bmp280_init();
float bmp280_read_temperature();
float bmp280_read_pressure();

bool dht22_init();
float dht22_read_humidity();
float dht22_read_temperature();

bool bh1750_init();
float bh1750_read_lux();

bool ads1115_init();
int16_t ads1115_read_bioelectric();
int16_t ads1115_read_soil();

void relay_init();
void buzzer_init();
bool oled_init();

bool sd_logger_init();
bool sd_logger_is_ready();
bool sd_logger_write_row(unsigned long timestampMs, int16_t bioelectricRaw,
                          bool loPlus, bool loMinus, int16_t soilRaw,
                          float tempC, float humidityPct, float pressureHpa,
                          float lightLux, const char* readingStatus);

// --- Pin assignments (per Connection Diagrams pin table) ---
#define LO_PLUS_PIN  4   // AD8232 LO+ (leads-off detect)
#define LO_MINUS_PIN 5   // AD8232 LO- (leads-off detect)

// --- Sampling interval ---
const unsigned long SAMPLE_INTERVAL_MS = 1000;  // 1 sample/sec for now.
unsigned long lastSampleTime = 0;

// --- Cold-start baseline state (Connection Diagrams Sec 5.1) ---
// This is just a counter/flag for now — the actual bounded-memory
// baseline model (Phase 4, next step) will replace this placeholder logic.
unsigned long validReadingCount = 0;
const unsigned long COLD_START_THRESHOLD = 200;  // placeholder N; tune from real Phase 3 data
bool baselineReady = false;

void setup() {
  Serial.begin(115200);
  Wire.begin();  // GPIO8 SDA, GPIO9 SCL by default on most ESP32-S3 boards.

  pinMode(LO_PLUS_PIN, INPUT);
  pinMode(LO_MINUS_PIN, INPUT);

  bool bmpOk   = bmp280_init();
  bool dhtOk   = dht22_init();
  bool bhOk    = bh1750_init();
  bool adsOk   = ads1115_init();
  bool sdOk    = sd_logger_init();
  relay_init();
  buzzer_init();
  bool oledOk  = oled_init();

  Serial.println("PhytoSense++ Phase 4 logging firmware boot");
  Serial.printf("BMP280: %s | DHT22: %s | BH1750: %s | ADS1115: %s | SD: %s | OLED: %s\n",
                bmpOk ? "OK" : "FAIL", dhtOk ? "OK" : "FAIL",
                bhOk ? "OK" : "FAIL", adsOk ? "OK" : "FAIL",
                sdOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");

  if (!sdOk) {
    Serial.println("WARNING: SD not ready — logging to Serial only. "
                    "Check wiring on GPIO10/11/12/13 and card insertion.");
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleTime = now;

  // --- Read electrode contact status first ---
  bool loPlus  = digitalRead(LO_PLUS_PIN);
  bool loMinus = digitalRead(LO_MINUS_PIN);
  bool contactBad = loPlus || loMinus;  // HIGH on either = poor contact

  // --- Read all sensors ---
  int16_t bioelectricRaw = ads1115_read_bioelectric();
  int16_t soilRaw        = ads1115_read_soil();
  float tempC            = bmp280_read_temperature();
  float pressureHpa      = bmp280_read_pressure();
  float humidityPct      = dht22_read_humidity();
  float lightLux         = bh1750_read_lux();

  // --- Determine reading status (Sec 5.1 failure-mode states) ---
  const char* status;
  if (contactBad) {
    status = "low_confidence";   // discarded, but logged explicitly — not silently dropped
  } else if (!baselineReady) {
    status = "cold_start";       // logged normally, but no alert/action yet
    validReadingCount++;
    if (validReadingCount >= COLD_START_THRESHOLD) {
      baselineReady = true;
      Serial.println(">>> Cold-start complete — baseline now considered ready <<<");
    }
  } else {
    status = "ok";
  }

  // --- Serial output (human-readable, for live debugging) ---
  Serial.printf("[%lu] bio=%d lo+=%d lo-=%d soil=%d temp=%.2fC hum=%.2f%% "
                "pres=%.2fhPa lux=%.2f status=%s\n",
                now, bioelectricRaw, loPlus, loMinus, soilRaw,
                tempC, humidityPct, pressureHpa, lightLux, status);

  // --- SD log (CSV, what actually feeds your Results section later) ---
  if (sd_logger_is_ready()) {
    sd_logger_write_row(now, bioelectricRaw, loPlus, loMinus, soilRaw,
                         tempC, humidityPct, pressureHpa, lightLux, status);
  }
}