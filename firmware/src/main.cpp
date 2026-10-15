// main.cpp — PhytoSense++ v6: recording firmware + on-device signal-quality gate
//
// Changes vs v5 (logging behaviour is kept; every new CSV column is additive):
//   1. Per-cycle ADC stats: min / max / how many raw samples sat at the ADC ceiling.
//   2. Signal-quality gate with a reason code: contact | rail_hi | rail_lo | flat | jump.
//   3. Fixed-size ring-buffer baseline (bounded memory) that learns ONLY from good samples.
//   4. status is now: cold_start | low_confidence | ok | deviation.
//   5. Serial warning when the signal stays railed; optional OLED status; optional buzzer (off).
//
// NOTE: firmware cannot FIX a railed analog front-end, it can only detect it.
// Gate thresholds below are first values taken from the 12-14 Oct 2026 log.
// Re-derive them from the post-fix bench log before you trust them.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <DHT.h>
#include <math.h>
#include <string.h>

// ---------------- Build-time switches ----------------
#define ENABLE_OLED_STATUS 1   // show status on the OLED every 5 s (if the OLED is detected)
#define ENABLE_BUZZER      0   // keep 0 during the multi-day recording; set 1 for the demo video

// ---------------- Pin assignments (unchanged) ----------------
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
bool oledOk  = false;

void relay_init();
void buzzer_init();
void buzzer_alert(bool on);
bool oled_init();
void oled_show_status(const char* status, float bio, float z, const char* reason);
bool sd_logger_init();
bool sd_logger_is_ready();
bool sd_logger_write_row(unsigned long timestampMs, float bioelectricRaw,
                          bool loPlus, bool loMinus, float soilRaw,
                          float tempC, float humidityPct, float pressureHpa,
                          const char* readingStatus);

// ---------------- Sampling ----------------
const unsigned long SAMPLE_INTERVAL_MS = 1000;
unsigned long lastSampleTime = 0;

const int ADC_CHANNEL_SETTLE_US   = 50;
const int OVERSAMPLE_COUNT        = 20;   // raw samples averaged into each logged value
const int OVERSAMPLE_SPACING_MS   = 40;   // 20 x 40 ms = 800 ms, fits inside the 1 s cycle

// ---------------- Gate thresholds (initial, from the Oct log) ----------------
const int   RAIL_SAMPLE_VALUE     = 4090;   // a raw sample >= this counts as "at the ceiling"
const int   RAIL_MIN_SAMPLES      = 5;      // >= 5 of 20 samples at the ceiling => railed
const float RAIL_HI_AVG           = 4090.0f;
const float RAIL_LO_AVG           = 50.0f;
const int   FLAT_WINDOW           = 60;     // seconds of history for the flat-line check
const float FLAT_STD_MAX          = 2.0f;   // railed stretch had SD ~0; clean data never went below ~7
const float JUMP_MAX              = 1200.0f;// clean data's largest 1 s step was ~914 counts

// ---------------- Bounded-memory baseline ----------------
const int   BASELINE_N            = 1800;   // fixed memory: last 1800 GOOD samples (~30 min)
const int   MIN_BASELINE_SAMPLES  = 200;    // cold-start threshold (same as before)
const float DEVIATION_Z           = 3.0f;
const unsigned long BASELINE_RESET_AFTER_BAD_S = 600;  // 10 min of bad data => forget baseline

static float baseRing[BASELINE_N];
static int   baseHead  = 0;
static int   baseCount = 0;

static float flatRing[FLAT_WINDOW];
static int   flatHead  = 0;
static int   flatCount = 0;

float prevBio = 0;
bool  prevValid = false;
unsigned long badSeconds = 0;
unsigned long railedSeconds = 0;

// ---------------- ADC helpers ----------------
struct AdcCycle {
  float bioAvg;
  float soilAvg;
  int   bioMin;
  int   bioMax;
  int   bioNSat;
};

int16_t readAdcChannelClean(int pin) {
  analogRead(pin);                        // dummy read, discarded (crosstalk fix from v4)
  delayMicroseconds(ADC_CHANNEL_SETTLE_US);
  return analogRead(pin);
}

AdcCycle readCycle() {
  AdcCycle c;
  long bioSum = 0, soilSum = 0;
  c.bioMin = 4095;
  c.bioMax = 0;
  c.bioNSat = 0;
  for (int i = 0; i < OVERSAMPLE_COUNT; i++) {
    int b = readAdcChannelClean(ECG_PIN);
    int s = readAdcChannelClean(SOIL_PIN);
    bioSum  += b;
    soilSum += s;
    if (b < c.bioMin) c.bioMin = b;
    if (b > c.bioMax) c.bioMax = b;
    if (b >= RAIL_SAMPLE_VALUE) c.bioNSat++;
    delay(OVERSAMPLE_SPACING_MS);
  }
  c.bioAvg  = (float)bioSum  / OVERSAMPLE_COUNT;
  c.soilAvg = (float)soilSum / OVERSAMPLE_COUNT;
  return c;
}

// ---------------- Environmental reads (plausibility-checked, unchanged) ----------------
float readTempPlausible(Adafruit_BMP280 &bmp) {
  float t = bmp.readTemperature();
  if (isnan(t) || t < -10.0f || t > 60.0f) return NAN;
  return t;
}
float readPressurePlausible(Adafruit_BMP280 &bmp) {
  float p = bmp.readPressure() / 100.0F;
  if (isnan(p) || p < 850.0f || p > 1100.0f) return NAN;
  return p;
}

// ---------------- Baseline + flat-line helpers ----------------
void baselinePush(float v) {
  baseRing[baseHead] = v;
  baseHead = (baseHead + 1) % BASELINE_N;
  if (baseCount < BASELINE_N) baseCount++;
}

void baselineStats(float &mean, float &sd) {
  double s = 0;
  for (int i = 0; i < baseCount; i++) s += baseRing[i];
  double m = s / baseCount;
  double v = 0;
  for (int i = 0; i < baseCount; i++) {
    double d = baseRing[i] - m;
    v += d * d;
  }
  mean = (float)m;
  sd = (baseCount > 1) ? (float)sqrt(v / (baseCount - 1)) : 0.0f;
}

void baselineReset() {
  baseCount = 0;
  baseHead = 0;
}

void flatPush(float v) {
  flatRing[flatHead] = v;
  flatHead = (flatHead + 1) % FLAT_WINDOW;
  if (flatCount < FLAT_WINDOW) flatCount++;
}

// returns a large number until a full window exists, so "flat" cannot fire early
float flatStd() {
  if (flatCount < FLAT_WINDOW) return 1e9f;
  double s = 0;
  for (int i = 0; i < FLAT_WINDOW; i++) s += flatRing[i];
  double m = s / FLAT_WINDOW;
  double v = 0;
  for (int i = 0; i < FLAT_WINDOW; i++) {
    double d = flatRing[i] - m;
    v += d * d;
  }
  return (float)sqrt(v / (FLAT_WINDOW - 1));
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
  oledOk = oled_init();

  Serial.println("PhytoSense++ firmware boot (v6 - recording + on-device quality gate)");
  Serial.printf("GY-91 BMP280(0x76): %s | HW-611 BMP280(0x77): %s | SD: %s | OLED: %s\n",
                gyBmpOk ? "OK" : "FAIL", hwBmpOk ? "OK" : "FAIL",
                sdOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");
  Serial.printf("Oversampling: %d samples/cycle @ %dms | baseline ring: %d samples | cold start: %d\n",
                OVERSAMPLE_COUNT, OVERSAMPLE_SPACING_MS, BASELINE_N, MIN_BASELINE_SAMPLES);
  if (!sdOk) Serial.println("NOTE: SD not ready - logging to Serial only.");
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleTime < SAMPLE_INTERVAL_MS) return;
  lastSampleTime = now;   // anchor to the START of the cycle (v5 timing fix)

  bool loPlus  = digitalRead(LO_PLUS_PIN);
  bool loMinus = digitalRead(LO_MINUS_PIN);
  bool contactBad = loPlus || loMinus;

  AdcCycle c = readCycle();

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
  if (isnan(humidityPct) || humidityPct < 0.0f || humidityPct > 100.0f) humidityPct = NAN;

  // ---------------- Signal-quality gate ----------------
  flatPush(c.bioAvg);
  bool railHi = (c.bioAvg >= RAIL_HI_AVG) || (c.bioNSat >= RAIL_MIN_SAMPLES);
  bool railLo = (c.bioAvg <= RAIL_LO_AVG);
  bool flat   = (flatStd() < FLAT_STD_MAX);
  bool jump   = prevValid && (fabsf(c.bioAvg - prevBio) > JUMP_MAX);
  prevBio = c.bioAvg;
  prevValid = true;

  const char* reason = "none";
  if (contactBad)    reason = "contact";
  else if (railHi)   reason = "rail_hi";
  else if (railLo)   reason = "rail_lo";
  else if (flat)     reason = "flat";
  else if (jump)     reason = "jump";
  bool good = (strcmp(reason, "none") == 0);

  if (good) badSeconds = 0; else badSeconds++;
  if (badSeconds == BASELINE_RESET_AFTER_BAD_S) {
    baselineReset();
    Serial.println(">>> 10 min of bad signal - baseline forgotten, will re-learn <<<");
  }
  if (railHi) {
    railedSeconds++;
    if (railedSeconds % 300 == 0) {
      Serial.printf("!!! SIGNAL RAILED for %lu min - check electrode / AD8232 offset !!!\n",
                    railedSeconds / 60);
    }
  } else {
    railedSeconds = 0;
  }

  // ---------------- Baseline scoring (causal: score first, then update) ----------------
  float z = NAN;
  const char* status;
  if (!good) {
    status = "low_confidence";                 // never updates the baseline, never alerts
  } else if (baseCount < MIN_BASELINE_SAMPLES) {
    status = "cold_start";
    baselinePush(c.bioAvg);
  } else {
    float mean, sd;
    baselineStats(mean, sd);
    z = (c.bioAvg - mean) / (sd + 1e-6f);
    status = (fabsf(z) > DEVIATION_Z) ? "deviation" : "ok";
    baselinePush(c.bioAvg);
  }

  Serial.printf("[%lu] bio=%.1f lo+=%d lo-=%d soil=%.1f temp=%.2fC hum=%.2f%% "
                "pres=%.2fhPa status=%s bmin=%d bmax=%d nsat=%d z=%.2f reason=%s\n",
                now, c.bioAvg, loPlus, loMinus, c.soilAvg,
                tempC, humidityPct, pressureHpa, status,
                c.bioMin, c.bioMax, c.bioNSat, z, reason);

  sd_logger_write_row(now, c.bioAvg, loPlus, loMinus, c.soilAvg,
                      tempC, humidityPct, pressureHpa, status);

#if ENABLE_OLED_STATUS
  static unsigned int cycleCount = 0;
  if (oledOk && (cycleCount++ % 5 == 0)) {
    oled_show_status(status, c.bioAvg, z, reason);
  }
#endif

#if ENABLE_BUZZER
  buzzer_alert(strcmp(status, "deviation") == 0);   // silent for low_confidence / cold_start
#endif
}