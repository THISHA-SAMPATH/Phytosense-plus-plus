// sd_logger.cpp
// microSD logging over SPI. Pin mapping per Connection Diagrams pin table:
//   GPIO10 = CS, GPIO11 = MOSI, GPIO12 = SCK, GPIO13 = MISO
// These are NOT the ESP32-S3's default VSPI pins, so we build a custom
// SPIClass instance rather than calling SD.begin() with defaults.

#include <SPI.h>
#include <SD.h>

#define SD_CS_PIN   10
#define SD_MOSI_PIN 11
#define SD_SCK_PIN  12
#define SD_MISO_PIN 13

static SPIClass sdSPI(HSPI);
static const char* LOG_FILENAME = "/phytosense_log.csv";
static bool sdReady = false;

bool sd_logger_init() {
  sdSPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);

  if (!SD.begin(SD_CS_PIN, sdSPI)) {
    sdReady = false;
    return false;
  }

  // Write a CSV header row only if the file doesn't already exist,
  // so re-flashing mid-trial doesn't wipe or duplicate headers.
  if (!SD.exists(LOG_FILENAME)) {
    File f = SD.open(LOG_FILENAME, FILE_WRITE);
    if (f) {
      f.println("timestamp_ms,bioelectric_raw,lo_plus,lo_minus,soil_raw,"
                "temp_c,humidity_pct,pressure_hpa,light_lux,"
                "reading_status");
      f.close();
    }
  }

  sdReady = true;
  return true;
}

bool sd_logger_is_ready() {
  return sdReady;
}

// One CSV row per call. reading_status should be one of:
//   "ok", "cold_start", "low_confidence"
// per the failure-mode states defined in Connection Diagrams Sec 5.1 —
// never silently drop a discarded reading, log it explicitly instead.
bool sd_logger_write_row(unsigned long timestampMs,
                          int16_t bioelectricRaw,
                          bool loPlus,
                          bool loMinus,
                          int16_t soilRaw,
                          float tempC,
                          float humidityPct,
                          float pressureHpa,
                          float lightLux,
                          const char* readingStatus) {
  if (!sdReady) return false;

  File f = SD.open(LOG_FILENAME, FILE_APPEND);
  if (!f) {
    sdReady = false;  // card may have been removed mid-run
    return false;
  }

  f.printf("%lu,%d,%d,%d,%d,%.2f,%.2f,%.2f,%.2f,%s\n",
           timestampMs, bioelectricRaw, loPlus ? 1 : 0, loMinus ? 1 : 0,
           soilRaw, tempC, humidityPct, pressureHpa, lightLux, readingStatus);
  f.close();
  return true;
}