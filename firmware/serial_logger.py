"""
PhytoSense++ — Serial-to-CSV logger (laptop stopgap, pre-microSD)

Reads the Serial output your ESP32-S3 firmware prints (the
"[timestamp] bio=... lo+=... ..." lines from main.cpp) and writes it
into a clean CSV file on your laptop, continuously, until you stop it.

Setup (one-time):
  pip install pyserial

How to find your COM port:
  Device Manager -> Ports (COM & LPT) -> look for "USB Serial Device (COMx)"

How to run:
  python serial_logger.py COM6
  (replace COM6 with your actual port)

Output:
  Creates phytosense_trial_log.csv in the same folder, appending one row
  per second for as long as this script runs. Safe to stop (Ctrl+C) and
  restart later — it appends, never overwrites.
"""

import sys
import csv
import re
from datetime import datetime

try:
    import serial
except ImportError:
    print("Missing dependency. Run this first:")
    print("    pip install pyserial")
    sys.exit(1)

BAUD_RATE = 115200
OUTPUT_CSV = "phytosense_trial_log.csv"

# Matches lines like:
# [1234] bio=4095 lo+=0 lo-=0 soil=4095 temp=31.47C hum=80.00% pres=1006.90hPa status=cold_start
LINE_PATTERN = re.compile(
    r"\[(?P<uptime_ms>\d+)\]\s+"
    r"bio=(?P<bio>-?\d+)\s+"
    r"lo\+=(?P<lo_plus>\d)\s+"
    r"lo-=(?P<lo_minus>\d)\s+"
    r"soil=(?P<soil>-?\d+)\s+"
    r"temp=(?P<temp>-?\d+\.\d+)C\s+"
    r"hum=(?P<hum>-?\d+\.\d+)%\s+"
    r"pres=(?P<pres>-?\d+\.\d+)hPa\s+"
    r"status=(?P<status>\w+)"
)

CSV_HEADER = [
    "wall_clock_time", "uptime_ms", "bioelectric_raw", "lo_plus", "lo_minus",
    "soil_raw", "temp_c", "humidity_pct", "pressure_hpa", "reading_status",
]


def ensure_header(path):
    try:
        with open(path, "r", newline="") as f:
            if f.readline().strip():
                return
    except FileNotFoundError:
        pass
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow(CSV_HEADER)


def main():
    if len(sys.argv) < 2:
        print("Usage: python serial_logger.py <COM_PORT>")
        print("Example: python serial_logger.py COM6")
        sys.exit(1)

    port = sys.argv[1]
    ensure_header(OUTPUT_CSV)

    print(f"Opening {port} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open {port}: {e}")
        print("Check the port name in Device Manager, and make sure no other "
              "program (like PlatformIO's own Serial Monitor) has it open at "
              "the same time.")
        sys.exit(1)

    print(f"Logging to {OUTPUT_CSV} — press Ctrl+C to stop.\n")
    rows_written = 0

    try:
        with open(OUTPUT_CSV, "a", newline="") as f:
            writer = csv.writer(f)
            while True:
                raw = ser.readline().decode("utf-8", errors="replace").strip()
                if not raw:
                    continue

                match = LINE_PATTERN.search(raw)
                if match:
                    d = match.groupdict()
                    writer.writerow([
                        datetime.now().isoformat(timespec="seconds"),
                        d["uptime_ms"], d["bio"], d["lo_plus"], d["lo_minus"],
                        d["soil"], d["temp"], d["hum"], d["pres"], d["status"],
                    ])
                    f.flush()
                    rows_written += 1
                    if rows_written % 30 == 0:
                        print(f"...{rows_written} rows logged so far")
                else:
                    print(f"(non-data line) {raw}")
    except KeyboardInterrupt:
        print(f"\nStopped. Total rows logged this session: {rows_written}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()