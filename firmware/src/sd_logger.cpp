// sd_logger.cpp
// microSD logging over SPI. Pin mapping: GPIO10=CS, GPIO11=MOSI, GPIO12=SCK, GPIO13=MISO
//
// v5 CHANGE: bioelectricRaw/soilRaw are now floats (oversampled averages),
// not int16_t — matches v5 main.cpp's anti-alias oversampling fix.

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

  if (!SD.exists(LOG_FILENAME)) {
    File f = SD.open(LOG_FILENAME, FILE_WRITE);
    if (f) {
      f.println("timestamp_ms,bioelectric_raw,lo_plus,lo_minus,soil_raw,"
                "temp_c,humidity_pct,pressure_hpa,reading_status");
      f.close();
    }
  }

  sdReady = true;
  return true;
}

bool sd_logger_is_ready() {
  return sdReady;
}

bool sd_logger_write_row(unsigned long timestampMs,
                          float bioelectricRaw,
                          bool loPlus,
                          bool loMinus,
                          float soilRaw,
                          float tempC,
                          float humidityPct,
                          float pressureHpa,
                          const char* readingStatus) {
  if (!sdReady) return false;

  File f = SD.open(LOG_FILENAME, FILE_APPEND);
  if (!f) {
    sdReady = false;
    return false;
  }

  f.printf("%lu,%.2f,%d,%d,%.2f,%.2f,%.2f,%.2f,%s\n",
           timestampMs, bioelectricRaw, loPlus ? 1 : 0, loMinus ? 1 : 0,
           soilRaw, tempC, humidityPct, pressureHpa, readingStatus);
  f.close();
  return true;
}

