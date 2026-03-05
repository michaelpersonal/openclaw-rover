#!/usr/bin/env python3
import argparse
import os
import sys
import time
import serial
from serial.tools import list_ports

BAUD = 9600
TIMEOUT = 0.25
OPEN_SETTLE_SECONDS = 1.2
DEFAULT_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
SIM_PORT_FILE = os.path.expanduser("~/rover/sim_port")


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
    return "OK"


def send_cmd(port: str, cmd: str) -> str:
    op = cmd.split(" ", 1)[0]
    expect = expected_for(op)
    with serial.Serial(port=port, baudrate=BAUD, timeout=TIMEOUT) as ser:
        # Nano resets on open.
        time.sleep(OPEN_SETTLE_SECONDS)
        ser.reset_input_buffer()

        first_non_watchdog = ""
        for _attempt in range(6):
            ser.write((cmd.strip() + "\n").encode("utf-8"))
            ser.flush()
            t_end = time.time() + 0.7
            while time.time() < t_end:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line == "STOPPED:WATCHDOG":
                    continue
                if not first_non_watchdog:
                    first_non_watchdog = line
                if line.startswith("ERR"):
                    return line
                if line.startswith(expect):
                    return line

        if first_non_watchdog:
            return first_non_watchdog
        raise RuntimeError(f"No response from rover for command: {cmd}")


def clamp_speed(v: int) -> int:
    return max(0, min(255, v))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rover serial control bridge")
    parser.add_argument("action", choices=["forward", "backward", "left", "right", "spin_left", "spin_right", "stop", "status", "ping"])
    parser.add_argument("speed", nargs="?", type=int)
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
        "stop": "STOP",
        "status": "STATUS",
        "ping": "PING",
    }
    op = mapping[args.action]
    if args.action in {"forward", "backward", "left", "right", "spin_left", "spin_right"}:
        if args.speed is None:
            raise RuntimeError("Speed is required for movement commands")
        cmd = f"{op} {clamp_speed(args.speed)}"
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
