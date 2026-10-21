# Simulation (Wokwi) — pre-hardware starter

This is the early, pre-hardware Wokwi simulation used to check wiring and pin assignments before building. It is **not** the final firmware and does not run the gate, baseline or persistence logic. Those are in `firmware/` and are validated by replay (`analysis/`, `dashboard/`).

| Item                              | Simulation                       | Final hardware / firmware            |
| --------------------------------- | -------------------------------- | ------------------------------------ |
| Temperature / humidity            | DHT22 on GPIO15                  | DHT11 on GPIO15                      |
| Pressure                          | BMP180 (I2C)                     | BMP280 (I2C, 0x76 / 0x77)            |
| Bioelectric input                 | Potentiometer stub on GPIO2      | AD8232 on GPIO2 (direct ADC)         |
| Soil input                        | Potentiometer stub on GPIO1      | Soil sensor on GPIO1 (not validated) |
| Display                           | SSD1306 OLED                     | None fitted                          |
| Light sensor                      | Potentiometer stub (GPIO3)       | None fitted                          |
| Leads-off, relay, buzzer, SD card | GPIO4/5, GPIO6, GPIO7, SPI CS 10 | Same pins                            |

Use this only to show the pin plan. Use the dashboard for the demo.
