#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>

Adafruit_BME280 bme;

bool bme280_init() {
  return bme.begin(0x76);  // Try 0x77 if this fails on your board.
}

float bme280_read_temperature() {
  return bme.readTemperature();
}

float bme280_read_humidity() {
  return bme.readHumidity();
}
