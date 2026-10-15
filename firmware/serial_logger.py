"""
PhytoSense++ — Serial-to-CSV logger (v6, laptop stopgap, pre-microSD)

Reads the lines printed by firmware v6 and writes a CSV, with a column for
EVENT MARKERS: type a short note in this window and press Enter while it runs
(e.g.  water_withheld ) and it is stamped on the next logged row.

Setup (one-time):   pip install pyserial
Run:                python serial_logger.py COM6 stress_run1.csv
                    (COM port from Device Manager; the file name is optional)

Safe to stop (Ctrl+C) and restart — it appends. It refuses to append to a file
whose header differs (so old v5 logs can't be mixed with v6 columns).

Events logged automatically: device_reboot (uptime went backwards) and
serial_reconnect (USB port dropped and came back).
Suggested manual events: baseline_start, water_withheld, first_wilting_seen,
rewatered, electrode_touched, electrode_repositioned, note_<anything>
"""

import sys
import csv
import re
import time
import queue
import threading
from datetime import datetime

try:
    import serial
except ImportError:
    print("Missing dependency. Run this first:\n    pip install pyserial")
    sys.exit(1)

BAUD_RATE = 115200
DEFAULT_OUTPUT = "phytosense_trial_v6.csv"

NUM = r"[-+]?(?:\d+(?:\.\d+)?|nan|inf)"
BASE_PATTERN = re.compile(
    r"\[(?P<uptime_ms>\d+)\]\s+"
    rf"bio=(?P<bio>{NUM})\s+"
    r"lo\+=(?P<lo_plus>\d)\s+"
    r"lo-=(?P<lo_minus>\d)\s+"
    rf"soil=(?P<soil>{NUM})\s+"
    rf"temp=(?P<temp>{NUM})C\s+"
    rf"hum=(?P<hum>{NUM})%\s+"
    rf"pres=(?P<pres>{NUM})hPa\s+"
    r"status=(?P<status>\w+)",
    re.IGNORECASE,
)
EXTRA_PATTERN = re.compile(
    rf"bmin=(?P<bmin>\d+)\s+bmax=(?P<bmax>\d+)\s+nsat=(?P<nsat>\d+)\s+"
    rf"z=(?P<z>{NUM})\s+reason=(?P<reason>\w+)",
    re.IGNORECASE,
)

CSV_HEADER = [
    "wall_clock_time", "uptime_ms", "bioelectric_raw", "lo_plus", "lo_minus",
    "soil_raw", "temp_c", "humidity_pct", "pressure_hpa", "reading_status",
    "bio_min", "bio_max", "n_sat", "z_score", "gate_reason", "event",
]

events = queue.Queue()


def stdin_reader():
    """Collect typed event markers; they are attached to the next data row."""
    while True:
        line = sys.stdin.readline()
        if not line:          # stdin closed
            return
        line = line.strip()
        if line:
            events.put(line)
            print(f"  >> event queued: {line}")


def ensure_header(path):
    try:
        with open(path, "r", newline="") as f:
            first = f.readline().strip()
    except FileNotFoundError:
        first = ""
    if first:
        if first != ",".join(CSV_HEADER):
            print(f"ERROR: {path} already exists with a different header.")
            print("Use a new file name (e.g. an old v5 log must not be appended to).")
            sys.exit(1)
        return
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow(CSV_HEADER)


def open_port(port):
    try:
        return serial.Serial(port, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open {port}: {e}")
        print("Check the port in Device Manager and close any other program "
              "(e.g. PlatformIO Serial Monitor) using it. Retrying in 2 s...")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python serial_logger.py <COM_PORT> [output.csv]")
        sys.exit(1)

    port = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT
    ensure_header(output)

    threading.Thread(target=stdin_reader, daemon=True).start()
    print(f"Logging to {output} — Ctrl+C to stop. Type an event name + Enter to mark it.\n")

    rows_written = 0
    ser = None
    last_uptime = None
    pending_auto = []          # auto events waiting for the next row

    try:
        with open(output, "a", newline="") as f:
            writer = csv.writer(f)
            while True:
                if ser is None:
                    ser = open_port(port)
                    if ser is None:
                        time.sleep(2)
                        continue
                    if rows_written > 0:
                        pending_auto.append("serial_reconnect")
                try:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                except (serial.SerialException, OSError) as e:
                    print(f"[{datetime.now():%H:%M:%S}] Serial link lost ({e}) — reconnecting...")
                    try:
                        ser.close()
                    except Exception:
                        pass
                    ser = None
                    continue
                if not raw:
                    continue

                m = BASE_PATTERN.search(raw)
                if not m:
                    print(f"(non-data line) {raw}")
                    continue
                d = m.groupdict()
                x = EXTRA_PATTERN.search(raw)
                e = x.groupdict() if x else {"bmin": "", "bmax": "", "nsat": "", "z": "", "reason": ""}

                uptime = int(d["uptime_ms"])
                if last_uptime is not None and uptime < last_uptime:
                    pending_auto.append("device_reboot")
                last_uptime = uptime

                ev = list(pending_auto)
                pending_auto.clear()
                while not events.empty():
                    ev.append(events.get_nowait())

                writer.writerow([
                    datetime.now().isoformat(timespec="milliseconds"),
                    d["uptime_ms"], d["bio"], d["lo_plus"], d["lo_minus"],
                    d["soil"], d["temp"], d["hum"], d["pres"], d["status"],
                    e["bmin"], e["bmax"], e["nsat"], e["z"], e["reason"],
                    "; ".join(ev),
                ])
                f.flush()
                rows_written += 1
                if rows_written % 60 == 0:
                    print(f"...{rows_written} rows | last: bio={d['bio']} status={d['status']} reason={e['reason']}")
    except KeyboardInterrupt:
        print(f"\nStopped. Rows logged this session: {rows_written}")
    finally:
        if ser is not None:
            ser.close()


if __name__ == "__main__":
    main()