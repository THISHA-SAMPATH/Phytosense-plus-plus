// PhytoSense++ — Wokwi simulation starter sketch
// Matches diagram.json wiring exactly.

#include <Wire.h>
#include <Adafruit_BMP085.h>   // works for BMP180
#include <Adafruit_SSD1306.h>
#include <Adafruit_GFX.h>
#include <DHT.h>
#include <SPI.h>
#include <SD.h>

// ---- I2C bus pins (BMP180 + OLED share this bus) ----
#define SDA_PIN 8
#define SCL_PIN 9

// ---- DHT22 (digital, NOT on I2C) ----
#define DHT_PIN 15
#define DHT_TYPE DHT22
DHT dht(DHT_PIN, DHT_TYPE);

// ---- Analog stub pins (potentiometers standing in for real sensors) ----
#define AD8232_STUB_PIN 1   // stub for AD8232 output -> normally ADS1115 A0
#define SOIL_STUB_PIN   2   // stub for capacitive soil sensor -> normally ADS1115 A1
#define BH1750_STUB_PIN 3   // stub for BH1750 light sensor (not in Wokwi library)

// ---- AD8232 leads-off digital stubs ----
#define LO_PLUS_PIN  4
#define LO_MINUS_PIN 5

// ---- Actuation ----
#define RELAY_PIN  6
#define BUZZER_PIN 7

// ---- SD card (SPI) ----
#define SD_CS   10
#define SD_MOSI 11
#define SD_SCK  12
#define SD_MISO 13

Adafruit_BMP085 bmp;              // BMP180 stand-in for BME280
Adafruit_SSD1306 display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);

  // I2C bus
  Wire.begin(SDA_PIN, SCL_PIN);

  if (!bmp.begin()) {
    Serial.println("BMP180 not found - check I2C wiring on GPIO8/GPIO9");
  }

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED not found - check I2C wiring on GPIO8/GPIO9");
  }
  display.clearDisplay();
  display.display();

  dht.begin();

  pinMode(LO_PLUS_PIN, INPUT);
  pinMode(LO_MINUS_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  // SD card on SPI
  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  if (!SD.begin(SD_CS)) {
    Serial.println("SD card init failed - check CS/MOSI/MISO/SCK wiring");
  } else {
    Serial.println("SD card ready");
  }
}

void loop() {
  // --- Real sensors ---
  float temperature = bmp.readTemperature();
  float pressure = bmp.readPressure();
  float humidity = dht.readHumidity();          // real DHT22 reading
  float dhtTemp = dht.readTemperature();

  // --- Stubbed sensors (potentiometers standing in for real hardware) ---
  int ad8232_raw = analogRead(AD8232_STUB_PIN);   // TODO: replace with ADS1115 A0 on real hardware
  int soil_raw   = analogRead(SOIL_STUB_PIN);     // TODO: replace with ADS1115 A1 on real hardware
  int light_raw  = analogRead(BH1750_STUB_PIN);   // TODO: replace with real BH1750 I2C reading

  bool leadsOffPlus  = digitalRead(LO_PLUS_PIN);
  bool leadsOffMinus = digitalRead(LO_MINUS_PIN);

  Serial.println("---- PhytoSense++ Reading ----");
  Serial.printf("BMP180 Temp: %.2f C  Pressure: %.2f Pa\n", temperature, pressure);
  Serial.printf("DHT22 Temp: %.2f C  Humidity: %.2f %%\n", dhtTemp, humidity);
  Serial.printf("AD8232 stub raw: %d\n", ad8232_raw);
  Serial.printf("Soil stub raw: %d\n", soil_raw);
  Serial.printf("BH1750 stub raw: %d\n", light_raw);
  Serial.printf("Leads off: LO+ %d  LO- %d\n", leadsOffPlus, leadsOffMinus);

  // --- Simple threshold logic example ---
  bool stressDetected = (soil_raw < 300) || leadsOffPlus || leadsOffMinus;
  digitalWrite(RELAY_PIN, stressDetected ? HIGH : LOW);
  digitalWrite(BUZZER_PIN, stressDetected ? HIGH : LOW);

  // --- OLED display ---
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.printf("T:%.1fC H:%.1f%%\n", dhtTemp, humidity);
  display.printf("Soil:%d Light:%d\n", soil_raw, light_raw);
  display.printf("Stress:%s\n", stressDetected ? "YES" : "no");
  display.display();

  // --- Log to SD card ---
  File logFile = SD.open("/log.csv", FILE_APPEND);
  if (logFile) {
    logFile.printf("%.2f,%.2f,%.2f,%d,%d,%d,%d,%d\n",
                    temperature, dhtTemp, humidity,
                    ad8232_raw, soil_raw, light_raw,
                    leadsOffPlus, leadsOffMinus);
    logFile.close();
  } else {
    Serial.println("Failed to open log.csv for append");
  }

  delay(2000);
}
