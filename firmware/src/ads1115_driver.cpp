#include <Adafruit_ADS1X15.h>

Adafruit_ADS1115 ads;

bool ads1115_init() {
  return ads.begin();
}

int16_t ads1115_read_bioelectric() {
  return ads.readADC_SingleEnded(0);  // A0 = AD8232 OUTPUT.
}

int16_t ads1115_read_soil() {
  return ads.readADC_SingleEnded(1);  // A1 = soil moisture AOUT.
}