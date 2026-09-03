// bmp280_driver.cpp
// Replaces bme280_driver.cpp — BMP280 gives temperature + pressure only
// (no humidity; DHT22 fills that gap, see dht22_driver.cpp).
// Shared I2C bus: GPIO8 = SDA, GPIO9 = SCL.

#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>

Adafruit_BMP280 bmp;

bool bmp280_init() {
  // Try 0x76 first (common default); if it fails on your board, the
  // module may be strapped to 0x77 instead — swap and re-flash if needed.
  bool ok = bmp.begin(0x76);
  if (!ok) {
    ok = bmp.begin(0x77);
  }
  return ok;
}

float bmp280_read_temperature() {
  return bmp.readTemperature();       // degrees Celsius
}

float bmp280_read_pressure() {
  return bmp.readPressure() / 100.0F; // convert Pa -> hPa
}