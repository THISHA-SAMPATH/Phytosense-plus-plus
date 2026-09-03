// dht22_driver.cpp
// DHT22 (AM2302) — single-wire digital humidity/temp sensor on GPIO15.
// Added because BMP280 does not measure humidity.

#include <DHT.h>

#define DHT22_PIN 15
#define DHT22_TYPE DHT22

DHT dht22(DHT22_PIN, DHT22_TYPE);

bool dht22_init() {
  dht22.begin();
  // DHT22 needs ~2s after power-up before its first valid reading —
  // this delay is intentional, don't remove it.
  delay(2000);
  float testRead = dht22.readHumidity();
  return !isnan(testRead);
}

float dht22_read_humidity() {
  return dht22.readHumidity();        // % RH
}

float dht22_read_temperature() {
  return dht22.readTemperature();     // degrees Celsius (backup/cross-check vs BMP280)
}