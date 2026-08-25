#include <BH1750.h>
#include <Wire.h>

BH1750 lightMeter;

bool bh1750_init() {
  return lightMeter.begin();
}

float bh1750_read_lux() {
  return lightMeter.readLightLevel();
}
