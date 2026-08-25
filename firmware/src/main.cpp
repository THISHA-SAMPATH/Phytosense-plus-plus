#include <Arduino.h>
#include <Wire.h>

bool bme280_init();
bool bh1750_init();
bool ads1115_init();
void relay_init();
void buzzer_init();
bool oled_init();

void setup() {
  Serial.begin(115200);
  Wire.begin();  // GPIO8 SDA, GPIO9 SCL by default on most ESP32-S3 boards.

  bool bmeOk = bme280_init();
  bool bhOk = bh1750_init();
  bool adsOk = ads1115_init();
  relay_init();
  buzzer_init();
  bool oledOk = oled_init();

  Serial.println("PhytoSense++ skeleton boot");
  Serial.printf("BME280: %s | BH1750: %s | ADS1115: %s | OLED: %s\n",
                bmeOk ? "OK" : "FAIL", bhOk ? "OK" : "FAIL",
                adsOk ? "OK" : "FAIL", oledOk ? "OK" : "FAIL");
}

void loop() {
  Serial.println("alive");
  delay(2000);
}
