// main.cpp — PhytoSense++ Phase 4 data-logging firmware (v5 — RE-TRIAL READY)
//
// v5 = v4 (ADC crosstalk fix) PLUS two more fixes required by the 16 Sep 2026
// independent audit before any new trial data can be trusted:
//
//   FIX A — On-device oversampling (anti-alias):
//     The audit found narrow interference lines at 0.25/0.33/0.50 Hz in the
//     bioelectric spectrum — the signature of periodic interference aliased
//     by sampling at exactly 1Hz with no filtering beforehand. Fix: instead
//     of one analogRead() per second, take OVERSAMPLE_COUNT samples spread
//     across each 1-second cycle and log their average. This acts as a
//     simple on-device low-pass filter, removing energy above ~Nyquist of
//     the oversampling rate before it can alias down into the logged signal.
//
//   FIX B — BMP280 plausibility check (no more silent glitch values):
//     Previously, an I2C read failure on the BMP280 could return a
//     nonsensical value (e.g. 177.40C) which was logged as-is. Now, any
//     reading outside a physically plausible range is logged as NaN
//     instead — an honest "no valid reading" rather than a silent glitch
//     that pollutes downstream analysis.
//
// Everything else (pin mapping, cold-start/low-confidence states, SD/Serial
// logging) is unchanged from v3/v4.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <DHT.h>

// --- Pin assignments ---
#define SDA_PIN       8
#define SCL_PIN       9
#define DHT_PIN       15
#define DHT_TYPE      DHT11
#define SOIL_PIN      1
#define ECG_PIN       2
#define LO_PLUS_PIN   4
#define LO_MINUS_PIN  5
#define GY91_BMP_ADDR 0x76
#define HW611_ADDR    0x77

Adafruit_BMP280 gyBmp;
Adafruit_BMP280 hwBmp;
DHT dht11(DHT_PIN, DHT_TYPE);

bool gyBmpOk = false;
bool hwBmpOk = false;

void relay_init();
void buzzer_init();
bool oled_init();
bool sd_logger_init();
bool sd_logger_is_ready();
bool sd_logger_write_row(unsigned long timestampMs, float bioelectricRaw,
                          bool loPlus, bool loMinus, float soilRaw,
                          float tempC, float humidityPct, float pressureHpa,
                          const char* readingStatus);

const unsigned long SAMPLE_INTERVAL_MS = 1000;
unsigned long lastSampleTime = 0;

unsigned long validReadingCount = 0;
const unsigned long COLD_START_THRESHOLD = 200;
bool baselineReady = false;

const int ADC_CHANNEL_SETTLE_US = 50;

// --- FIX A: oversampling config ---
// 20 samples spread across each ~1s cycle = effective ~20Hz internal rate,
// averaged down to the 1Hz logged output. Adjust OVERSAMPLE_COUNT upward
// later if a higher-rate raw session (per audit action #4) shows the real
// interference needs more averaging to suppress.
const int OVERSAMPLE_COUNT = 20;
const int OVERSAMPLE_SPACING_MS = 40;   // 20 samples * 40ms = 800ms, fits in the 1s cycle

int16_t readAdcChannelClean(int pin) {
  analogRead(pin);                       // dummy read, discarded (v4 crosstalk fix)
  delayMicroseconds(ADC_CHANNEL_SETTLE_US);
  return analogRead(pin);
}

// Oversampled, crosstalk-safe read: averages OVERSAMPLE_COUNT clean readings
void readBothChannelsOversampled(float &bioAvgOut, float &soilAvgOut) {
  long bioSum = 0, soilSum = 0;
  for (int i = 0; i < OVERSAMPLE_COUNT; i++) {
    bioSum  += readAdcChannelClean(ECG_PIN);
    soilSum += readAdcChannelClean(SOIL_PIN);
    delay(OVERSAMPLE_SPACING_MS);
  }
  bioAvgOut  = (float)bioSum  / OVERSAMPLE_COUNT;
  soilAvgOut = (float)soilSum / OVERSAMPLE_COUNT;
}

// --- FIX B: plausibility-checked environmental reads ---
float readTempPlausible(Adafruit_BMP280 &bmp) {
  float t = bmp.readTemperature();
  if (isnan(t) || t < -10.0f || t > 60.0f) return NAN;   // reject implausible/garbage reads
  return t;
}
float readPressurePlausible(Adafruit_BMP280 &bmp) {
  float p = bmp.readPressure() / 100.0F;
  if (isnan(p) || p < 850.0f || p > 1100.0f) return NAN;
  return p;
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0) < 3000) delay(10);
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

  Serial.println("PhytoSense++ Phase 4 logging firmware boot (v5 - oversampled + plausibility-checked)");
  Serial.printf("GY-91 BMP280(0x76): %s | HW-611 BMP280(0x77): %s | DHT11: OK | SD: %s | OLED: %s\n",
                gyBmpOk ? "OK" : "FAIL", hwBmpOk ? "OK" : "FAIL",
                sdOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");
  Serial.printf("Oversampling: %d samples/cycle @ %dms spacing\n", OVERSAMPLE_COUNT, OVERSAMPLE_SPACING_MS);

  if (!sdOk) {
    Serial.println("NOTE: SD not ready — logging to Serial only.");
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }

  bool loPlus  = digitalRead(LO_PLUS_PIN);
  bool loMinus = digitalRead(LO_MINUS_PIN);
  bool contactBad = loPlus || loMinus;

  // --- FIX A applied here: oversampled reads instead of a single sample ---
  float bioelectricRaw, soilRaw;
  readBothChannelsOversampled(bioelectricRaw, soilRaw);
  lastSampleTime = millis();   // account for time spent oversampling

  // --- FIX B applied here: plausibility-checked, NaN on failure ---
  float tempC = NAN, pressureHpa = NAN;
  if (gyBmpOk) {
    tempC       = readTempPlausible(gyBmp);
    pressureHpa = readPressurePlausible(gyBmp);
  }
  if ((isnan(tempC) || isnan(pressureHpa)) && hwBmpOk) {
    if (isnan(tempC))       tempC       = readTempPlausible(hwBmp);
    if (isnan(pressureHpa)) pressureHpa = readPressurePlausible(hwBmp);
  }
  float humidityPct = dht11.readHumidity();

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

  Serial.printf("[%lu] bio=%.1f lo+=%d lo-=%d soil=%.1f temp=%.2fC hum=%.2f%% "
                "pres=%.2fhPa status=%s\n",
                now, bioelectricRaw, loPlus, loMinus, soilRaw,
                tempC, humidityPct, pressureHpa, status);

  if (sd_logger_is_ready()) {
    sd_logger_write_row(now, bioelectricRaw, loPlus, loMinus, soilRaw,
                         tempC, humidityPct, pressureHpa, status);
  }
}
