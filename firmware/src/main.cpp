// main.cpp — PhytoSense++ Phase 4 data-logging firmware (v4 — ADC CROSSTALK FIX)
//
// v4 CHANGE FROM v3: fixes a confirmed ADC channel-crosstalk issue where
// bioelectric_raw and soil_raw were found to be 99.77% correlated in trial
// data — i.e., essentially reading the same value. Root cause: back-to-back
// analogRead() calls on different ESP32 ADC1 channels with no settling time
// between them, a known ESP32 multiplexer-switching artifact. Fix: a
// discarded dummy read + short delay after switching channels, before the
// real reading is taken.
//
// Everything else is unchanged from v3 — see that version's header comment
// for the full pipeline description (bmp280 dual-chip handling, DHT11,
// cold-start / low-confidence states, SD + Serial logging).

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <DHT.h>

// --- Pin assignments (confirmed working hardware mapping) ---
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
Adafruit_BMP280 gyBmp;
Adafruit_BMP280 hwBmp;
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

// --- Cold-start baseline state ---
unsigned long validReadingCount = 0;
const unsigned long COLD_START_THRESHOLD = 200;
bool baselineReady = false;

// --- NEW (v4): settling delay used between ADC channel switches ---
const int ADC_CHANNEL_SETTLE_US = 50;

// --- NEW (v4): crosstalk-safe multi-channel ADC read helper ---
// Discards one reading immediately after switching to a new channel, then
// waits ADC_CHANNEL_SETTLE_US before taking the reading that's actually used.
// This clears residual charge left on the ADC's sample-and-hold capacitor
// by whichever channel was read immediately before it.
int16_t readAdcChannelClean(int pin) {
  analogRead(pin);                       // dummy read, discarded
  delayMicroseconds(ADC_CHANNEL_SETTLE_US);
  return analogRead(pin);                // real reading
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

  Serial.println("PhytoSense++ Phase 4 logging firmware boot (v4 - ADC crosstalk fix)");
  Serial.printf("GY-91 BMP280(0x76): %s | HW-611 BMP280(0x77): %s | DHT11: OK | SD: %s | OLED: %s\n",
                gyBmpOk ? "OK" : "FAIL", hwBmpOk ? "OK" : "FAIL",
                sdOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");

  if (!gyBmpOk && !hwBmpOk) {
    Serial.println("WARNING: neither BMP280 responded. Check I2C wiring and HW-611 SDO->3V3 bridge.");
  }
  if (!sdOk) {
    Serial.println("NOTE: SD not ready — logging to Serial only.");
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleTime = now;

  bool loPlus  = digitalRead(LO_PLUS_PIN);
  bool loMinus = digitalRead(LO_MINUS_PIN);
  bool contactBad = loPlus || loMinus;

  // --- v4 FIX: crosstalk-safe reads instead of plain back-to-back analogRead() ---
  int16_t bioelectricRaw = readAdcChannelClean(ECG_PIN);
  int16_t soilRaw        = readAdcChannelClean(SOIL_PIN);

  float tempC = NAN, pressureHpa = NAN;
  if (gyBmpOk) {
    tempC       = gyBmp.readTemperature();
    pressureHpa = gyBmp.readPressure() / 100.0F;
  } else if (hwBmpOk) {
    tempC       = hwBmp.readTemperature();
    pressureHpa = hwBmp.readPressure() / 100.0F;
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

  Serial.printf("[%lu] bio=%d lo+=%d lo-=%d soil=%d temp=%.2fC hum=%.2f%% "
                "pres=%.2fhPa status=%s\n",
                now, bioelectricRaw, loPlus, loMinus, soilRaw,
                tempC, humidityPct, pressureHpa, status);

  if (sd_logger_is_ready()) {
    sd_logger_write_row(now, bioelectricRaw, loPlus, loMinus, soilRaw,
                         tempC, humidityPct, pressureHpa, status);
  }
}
