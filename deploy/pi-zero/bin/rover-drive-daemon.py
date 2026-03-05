#!/usr/bin/env python3
import json
import os
import signal
import time
from pathlib import Path

import serial
from serial.tools import list_ports

HOME = Path.home()
STATE_DIR = HOME / "rover"
CMD_FILE = STATE_DIR / "drive_cmd"
STATE_FILE = STATE_DIR / "drive_state.json"
PID_FILE = STATE_DIR / "drive.pid"

BAUD = 9600
DEFAULT_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
SIM_PORT_FILE = HOME / "rover" / "sim_port"

running = True


def handle_sigterm(_signo, _frame):
    global running
    running = False


def find_port() -> str:
    if SIM_PORT_FILE.exists():
        sim = SIM_PORT_FILE.read_text(encoding="utf-8").strip()
        if sim and os.path.exists(sim):
            return sim
    for p in DEFAULT_PORTS:
        if os.path.exists(p):
            return p
    for p in list_ports.comports():
        d = p.device
        if d.startswith("/dev/ttyUSB") or d.startswith("/dev/ttyACM"):
            return d
    raise RuntimeError("No serial port found")


def read_cmd():
    if not CMD_FILE.exists():
        return ("stop", 0)
    try:
        raw = CMD_FILE.read_text(encoding="utf-8").strip().split()
        if not raw:
            return ("stop", 0)
        action = raw[0].lower()
        speed = int(raw[1]) if len(raw) > 1 else 160
        speed = max(0, min(255, speed))
        return (action, speed)
    except Exception:
        return ("stop", 0)


def map_cmd(action: str, speed: int) -> str:
    m = {
        "forward": "FORWARD",
        "backward": "BACKWARD",
        "left": "LEFT",
        "right": "RIGHT",
        "spin_left": "SPIN_LEFT",
        "spin_right": "SPIN_RIGHT",
        "stop": "STOP",
    }
    op = m.get(action, "STOP")
    if op == "STOP":
        return "STOP"
    return f"{op} {speed}"


def write_state(payload):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    state = {
        "running": True,
        "pid": os.getpid(),
        "port": None,
        "action": "stop",
        "speed": 0,
        "last_status": "",
        "last_reply": "",
        "last_error": "",
        "last_watchdog": False,
        "updated_at": int(time.time() * 1000),
    }

    try:
        port = find_port()
        state["port"] = port
        write_state(state)

        with serial.Serial(port=port, baudrate=BAUD, timeout=0.05) as ser:
            time.sleep(1.2)
            ser.reset_input_buffer()

            last_sent = 0.0
            last_status_req = 0.0
            last_cmd = ""

            while running:
                action, speed = read_cmd()
                cmd = map_cmd(action, speed)

                now = time.time()
                if (cmd != last_cmd) or (now - last_sent >= 0.20):
                    ser.write((cmd + "\n").encode("utf-8"))
                    ser.flush()
                    last_sent = now
                    last_cmd = cmd
                    state["action"] = action
                    state["speed"] = speed

                if now - last_status_req >= 1.0:
                    ser.write(b"STATUS\n")
                    ser.flush()
                    last_status_req = now

                for _ in range(20):
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if not line:
                        break
                    if line == "STOPPED:WATCHDOG":
                        state["last_watchdog"] = True
                    elif line.startswith("STATUS:"):
                        state["last_status"] = line
                        state["last_watchdog"] = False
                    elif line.startswith("ERR"):
                        state["last_error"] = line
                    else:
                        state["last_reply"] = line

                state["updated_at"] = int(time.time() * 1000)
                write_state(state)
                time.sleep(0.02)

    except Exception as e:
        state["last_error"] = f"daemon_error:{e}"
        state["updated_at"] = int(time.time() * 1000)
        write_state(state)
        raise
    finally:
        state["running"] = False
        state["updated_at"] = int(time.time() * 1000)
        write_state(state)
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
