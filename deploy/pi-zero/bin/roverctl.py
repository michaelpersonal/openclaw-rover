#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
import serial
from serial.tools import list_ports

BAUD = 9600
TIMEOUT = 0.25
OPEN_SETTLE_SECONDS = 1.2
DEFAULT_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
SIM_PORT_FILE = os.path.expanduser("~/rover/sim_port")
SENSOR_FACING_REAR = False
SENSOR_HEADING_OFFSET = 180 if SENSOR_FACING_REAR else 0


def _existing(path: str | None) -> str | None:
    return path if path and os.path.exists(path) else None


def find_port(explicit: str | None) -> str:
    p = _existing(explicit)
    if p:
        return p
    if os.path.exists(SIM_PORT_FILE):
        try:
            sim = open(SIM_PORT_FILE, "r", encoding="utf-8").read().strip()
            p = _existing(sim)
            if p:
                return p
        except Exception:
            pass
    for p in DEFAULT_PORTS:
        if os.path.exists(p):
            return p
    for p in list_ports.comports():
        d = p.device
        if d.startswith("/dev/ttyUSB") or d.startswith("/dev/ttyACM"):
            return d
    raise RuntimeError("No serial port found (sim/hardware): sim_port, /dev/ttyUSB*, /dev/ttyACM*")


def expected_for(cmd: str) -> str:
    if cmd == "PING":
        return "PONG"
    if cmd == "STATUS":
        return "STATUS:"
    if cmd == "SCAN":
        return "SCAN:"
    return "OK"


def _send_cmd_with_ser(ser: serial.Serial, cmd: str, attempts: int = 10, wait_s: float = 1.0) -> str:
    op = cmd.split(" ", 1)[0]
    expect = expected_for(op)

    first_non_watchdog = ""
    for _attempt in range(attempts):
        ser.write((cmd.strip() + "\n").encode("utf-8"))
        ser.flush()
        t_end = time.time() + wait_s
        while time.time() < t_end:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if line == "STOPPED:WATCHDOG":
                continue
            if not first_non_watchdog:
                first_non_watchdog = line
            if line.startswith("ERR") or line.startswith("STOPPED:"):
                return line
            if line.startswith(expect):
                return line

    if first_non_watchdog:
        return first_non_watchdog
    raise RuntimeError(f"No response from rover for command: {cmd}")


def send_cmd(port: str, cmd: str) -> str:
    with serial.Serial(port=port, baudrate=BAUD, timeout=TIMEOUT) as ser:
        time.sleep(OPEN_SETTLE_SECONDS)
        ser.reset_input_buffer()
        if cmd.startswith("SPIN_TO"):
            return _send_cmd_with_ser(ser, cmd, attempts=2, wait_s=6.0)
        return _send_cmd_with_ser(ser, cmd)


def clamp_speed(v: int) -> int:
    return max(0, min(255, v))


def normalize_angle(a: int) -> int:
    return ((a % 360) + 360) % 360


def parse_status_line(line: str) -> dict[str, str]:
    if not line.startswith("STATUS:"):
        return {}
    body = line[len("STATUS:"):]
    out: dict[str, str] = {}
    for seg in body.split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            out[k] = v
    return out


def parse_dist_cm(status_line: str) -> int:
    parts = parse_status_line(status_line)
    dist_raw = parts.get("dist", "999")
    m = re.search(r"(\d+)", dist_raw)
    return int(m.group(1)) if m else 999


def format_scan_rows(rows: list[tuple[int, int]], mode: str) -> str:
    best = max(rows, key=lambda x: x[1])
    recommended_move = "backward" if SENSOR_FACING_REAR else "forward"
    lines = [f"SCAN:{mode}"]
    for logical, dist in rows:
        status = "BLOCKED" if dist < 20 else "clear"
        lines.append(f"angle={logical} dist={dist}cm state={status}")
    lines.append(f"best_angle={best[0]} best_dist={best[1]}cm recommend_move={recommended_move}")
    return "\n".join(lines)


def scan_with_step_spin(ser: serial.Serial) -> str:
    rows: list[tuple[int, int]] = []
    logical = 0
    samples = 12
    step_deg = 30
    spin_step_s = 0.11

    for i in range(samples):
        st = _send_cmd_with_ser(ser, "STATUS")
        if st.startswith("ERR") or st.startswith("STOPPED:"):
            return st
        dist = parse_dist_cm(st)
        rows.append((logical, dist))

        if i < samples - 1:
            _send_cmd_with_ser(ser, "SPIN_LEFT 120")
            time.sleep(spin_step_s)
            _send_cmd_with_ser(ser, "STOP")
            time.sleep(0.04)
            logical = normalize_angle(logical + step_deg)

    _send_cmd_with_ser(ser, "STOP")
    return format_scan_rows(rows, "full_360_fallback_12x30")


def scan_environment(port: str) -> str:
    with serial.Serial(port=port, baudrate=BAUD, timeout=TIMEOUT) as ser:
        time.sleep(OPEN_SETTLE_SECONDS)
        ser.reset_input_buffer()

        # Prefer firmware-native SCAN when available and fast.
        try:
            fw_scan = _send_cmd_with_ser(ser, "SCAN", attempts=1, wait_s=3.0)
            if fw_scan.startswith("SCAN:"):
                return fw_scan
        except Exception:
            pass

        # SPIN_TO is currently unstable on this rover; use fast fallback directly.
        return scan_with_step_spin(ser)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rover serial control bridge")
    parser.add_argument("action", choices=["forward", "backward", "left", "right", "spin_left", "spin_right", "spin_to", "scan", "stop", "status", "ping"])
    parser.add_argument("value", nargs="?", type=int)
    parser.add_argument("--port", default=None)
    args = parser.parse_args()

    port = find_port(args.port)
    mapping = {
        "forward": "FORWARD",
        "backward": "BACKWARD",
        "left": "LEFT",
        "right": "RIGHT",
        "spin_left": "SPIN_LEFT",
        "spin_right": "SPIN_RIGHT",
        "spin_to": "SPIN_TO",
        "stop": "STOP",
        "status": "STATUS",
        "ping": "PING",
    }

    if args.action == "scan":
        reply = scan_environment(port)
        print(f"port={port} cmd=SCAN")
        print(reply)
        return 2 if reply.startswith("ERR") else 0

    op = mapping[args.action]
    if args.action in {"forward", "backward", "left", "right", "spin_left", "spin_right"}:
        if args.value is None:
            raise RuntimeError("Speed is required for movement commands")
        cmd = f"{op} {clamp_speed(args.value)}"
    elif args.action == "spin_to":
        if args.value is None:
            raise RuntimeError("Angle is required for spin_to")
        cmd = f"{op} {normalize_angle(args.value)}"
    else:
        cmd = op

    reply = send_cmd(port, cmd)
    print(f"port={port} cmd={cmd} reply={reply}")
    return 2 if reply.startswith("ERR") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error={e}", file=sys.stderr)
        raise SystemExit(1)
