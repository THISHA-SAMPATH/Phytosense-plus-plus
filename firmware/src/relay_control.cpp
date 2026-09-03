#include <Arduino.h>

#define RELAY_PIN 6  // GPIO6

void relay_init() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);  // Pump off by default.
}

void relay_set_pump(bool on) {
  digitalWrite(RELAY_PIN, on ? HIGH : LOW);
}