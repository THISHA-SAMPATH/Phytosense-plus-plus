#include <Arduino.h>

#define BUZZER_PIN 7  // GPIO7

void buzzer_init() {
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
}

void buzzer_alert(bool on) {
  digitalWrite(BUZZER_PIN, on ? HIGH : LOW);
}
