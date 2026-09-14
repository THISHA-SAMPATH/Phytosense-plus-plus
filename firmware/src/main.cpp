// main.cpp — PhytoSense++ Phase 4 data-logging firmware (v3 — CONFIRMED HARDWARE)
//
// This version reflects what was actually tested and confirmed working on
// the physical board, replacing the earlier ADS1115-based approach.
//
// KEY CHANGE FROM EARLIER VERSIONS:
//   Bioelectric (AD8232) and soil moisture are now read on DIRECT ESP32-S3
//   ADC pins, not through the ADS1115 external ADC.
//   TRADEOFF (flag this in Master Document Sec 14, Limitations):
//     ESP32-S3's native ADC is 12-bit and known to be noisier/less linear
//     at low signal levels than the ADS1115's 16-bit external ADC that was
//     originally specified in the Hardware Requirements section. This was
//     a pragmatic choice to unblock the Phase 3 trial on schedule — it
//     should be disclosed as a limitation, not silently substituted.
//     Switching back to ADS1115 later is possible without losing prior
//     CSV data, since the column format is unchanged.
//
// CONFIRMED HARDWARE (as tested):
//   - GY-91 combo board: BMP280 @ 0x76 + MPU9250 @ 0x68 (MPU9250 not
//     used for PhytoSense sensing — plant stress detection doesn't need
//     motion data — left uninitialized to keep this file focused)
//   - HW-611 separate module: BMP280 or BME280 @ 0x77 (address collision
//     with GY-91 avoided by tying HW-611's SDO pin to 3V3 — confirm this
//     is physically done; if HW-611 reads FAIL, check that pad first)
//   - DHT11 on GPIO15 (NOT DHT22 — corrected from earlier version)
//   - AD8232 OUTPUT on direct ADC pin (GPIO2), LO+/LO- on GPIO4/GPIO5
//   - Soil moisture AOUT on direct ADC pin (GPIO1)
//
// What this file DOES:
//   - Reads bioelectric + electrode contact status + soil + both BMP280s
//     (GY-91 as primary, HW-611 as secondary/cross-check) + DHT11 humidity
//   - Applies cold-start / low-confidence failure-mode states
//     (Connection Diagrams Sec 5.1)
//   - Logs every sample to Serial AND microSD (if present) as one CSV row
//
// What this file still does NOT do (later Phase 4 steps, not this file):
//   - Denoising/filtering, personalized baseline model, confidence-gated
//     updates beyond the basic LO+/- check, fusion classifier,
//     explainability, irrigation control, forecasting.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <DHT.h>

// --- Pin assignments (CONFIRMED working hardware mapping) ---
#define SDA_PIN       8
#define SCL_PIN       9

#define DHT_PIN       15
#define DHT_TYPE      DHT11

#define SOIL_PIN      1     // direct ADC1 pin
#define ECG_PIN       2     // direct ADC1 pin (AD8232 OUTPUT)
#define LO_PLUS_PIN   4
#define LO_MINUS_PIN  5

#define GY91_BMP_ADDR 0x76
#define HW611_ADDR    0x77

// --- Objects ---
Adafruit_BMP280 gyBmp;    // GY-91's onboard BMP280 (primary)
Adafruit_BMP280 hwBmp;    // HW-611 separate module (secondary/cross-check)
DHT dht11(DHT_PIN, DHT_TYPE);

bool gyBmpOk = false;
bool hwBmpOk = false;

// --- Forward declarations from other driver files (unchanged from repo) ---
void relay_init();
void buzzer_init();
bool oled_init();

bool sd_logger_init();
bool sd_logger_is_ready();
bool sd_logger_write_row(unsigned long timestampMs, int16_t bioelectricRaw,
                          bool loPlus, bool loMinus, int16_t soilRaw,
                          float tempC, float humidityPct, float pressureHpa,
                          const char* readingStatus);

// --- Sampling interval ---
const unsigned long SAMPLE_INTERVAL_MS = 1000;
unsigned long lastSampleTime = 0;

// --- Cold-start baseline state (Connection Diagrams Sec 5.1) ---
unsigned long validReadingCount = 0;
const unsigned long COLD_START_THRESHOLD = 200;  // placeholder N; tune from real Phase 3 data
bool baselineReady = false;

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0) < 3000) delay(10);  // native USB needs time to enumerate
  delay(300);

  analogReadResolution(12);
  analogSetPinAttenuation(SOIL_PIN, ADC_11db);
  analogSetPinAttenuation(ECG_PIN,  ADC_11db);

  pinMode(LO_PLUS_PIN, INPUT);
  pinMode(LO_MINUS_PIN, INPUT);

  Wire.begin(SDA_PIN, SCL_PIN);

  gyBmpOk = gyBmp.begin(GY91_BMP_ADDR);
  hwBmpOk = hwBmp.begin(HW611_ADDR);
  dht11.begin();

  bool sdOk = sd_logger_init();
  relay_init();
  buzzer_init();
  bool oledOk = oled_init();

  Serial.println("PhytoSense++ Phase 4 logging firmware boot (v3 - direct ADC)");
  Serial.printf("GY-91 BMP280(0x76): %s | HW-611 BMP280(0x77): %s | DHT11: OK | SD: %s | OLED: %s\n",
                gyBmpOk ? "OK" : "FAIL", hwBmpOk ? "OK" : "FAIL",
                sdOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");

  if (!gyBmpOk && !hwBmpOk) {
    Serial.println("WARNING: neither BMP280 responded. Check I2C wiring, "
                    "and confirm HW-611's SDO pad is bridged to 3V3 "
                    "(otherwise it also tries to answer at 0x76 and "
                    "collides with the GY-91).");
  }
  if (!sdOk) {
    Serial.println("NOTE: SD not ready — logging to Serial only. "
                    "Expected if no card is inserted.");
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleTime = now;

  // --- Electrode contact status ---
  bool loPlus  = digitalRead(LO_PLUS_PIN);
  bool loMinus = digitalRead(LO_MINUS_PIN);
  bool contactBad = loPlus || loMinus;

  // --- Bioelectric + soil (direct ADC) ---
  int16_t bioelectricRaw = analogRead(ECG_PIN);
  int16_t soilRaw        = analogRead(SOIL_PIN);

  // --- Environmental: prefer GY-91, fall back to HW-611 if GY-91 fails ---
  float tempC = NAN, pressureHpa = NAN;
  if (gyBmpOk) {
    tempC       = gyBmp.readTemperature();
    pressureHpa = gyBmp.readPressure() / 100.0F;
  } else if (hwBmpOk) {
    tempC       = hwBmp.readTemperature();
    pressureHpa = hwBmp.readPressure() / 100.0F;
  }
  float humidityPct = dht11.readHumidity();

  // --- Failure-mode states (Connection Diagrams Sec 5.1) ---
  const char* status;
  if (contactBad) {
    status = "low_confidence";
  } else if (!baselineReady) {
    status = "cold_start";
    validReadingCount++;
    if (validReadingCount >= COLD_START_THRESHOLD) {
      baselineReady = true;
      Serial.println(">>> Cold-start complete — baseline now considered ready <<<");
    }
  } else {
    status = "ok";
  }

  // --- Serial output ---
  Serial.printf("[%lu] bio=%d lo+=%d lo-=%d soil=%d temp=%.2fC hum=%.2f%% "
                "pres=%.2fhPa status=%s\n",
                now, bioelectricRaw, loPlus, loMinus, soilRaw,
                tempC, humidityPct, pressureHpa, status);

  // --- SD log ---
  if (sd_logger_is_ready()) {
    sd_logger_write_row(now, bioelectricRaw, loPlus, loMinus, soilRaw,
                         tempC, humidityPct, pressureHpa, status);
  }
}