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
        speed = int(raw[1]) if len(raw) > 1 else 80
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


def promote_obstacle_event(state):
    state["last_event"] = "STOPPED:OBSTACLE"
    state["last_error"] = "ERR:OBSTACLE"
    state["action"] = "stop"
    state["speed"] = 0
    try:
        CMD_FILE.write_text("stop 0\n", encoding="utf-8")
    except Exception:
        pass


def process_line(state, line: str):
    if not line:
        return

    if "STOPPED:OBSTACLE" in line or "ERR:OBSTACLE" in line:
        promote_obstacle_event(state)
        return

    if "STOPPED:WATCHDOG" in line:
        state["last_event"] = "STOPPED:WATCHDOG"
        state["last_watchdog"] = True

    status_idx = line.find("STATUS:")
    if status_idx >= 0:
        state["last_status"] = line[status_idx:]
        state["last_watchdog"] = False
        return

    if line.startswith("ERR"):
        state["last_error"] = line
        return

    state["last_reply"] = line


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
        "last_event": "",
        "updated_at": int(time.time() * 1000),
    }

    try:
        while running:
            try:
                port = find_port()
                state["port"] = port
                write_state(state)

                with serial.Serial(port=port, baudrate=BAUD, timeout=0, write_timeout=0.2) as ser:
                    time.sleep(1.2)
                    ser.reset_input_buffer()

                    rx_buf = b""
                    last_sent = 0.0
                    last_status_req = 0.0
                    last_cmd = ""

                    while running:
                        action, speed = read_cmd()
                        cmd = map_cmd(action, speed)

                        now = time.time()
                        if (cmd != last_cmd) or (now - last_sent >= 0.12):
                            ser.write((cmd + "\n").encode("utf-8"))
                            last_sent = now
                            if cmd != last_cmd:
                                state["last_event"] = ""
                            last_cmd = cmd
                            state["action"] = action
                            state["speed"] = speed

                        if now - last_status_req >= 0.35:
                            ser.write(b"STATUS\n")
                            last_status_req = now

                        waiting = ser.in_waiting
                        if waiting:
                            rx_buf += ser.read(waiting)
                            while b"\n" in rx_buf:
                                raw_line, rx_buf = rx_buf.split(b"\n", 1)
                                line = raw_line.decode("utf-8", errors="replace").strip()
                                process_line(state, line)

                        state["updated_at"] = int(time.time() * 1000)
                        write_state(state)
                        time.sleep(0.02)

            except Exception as e:
                state["last_error"] = f"daemon_error:{type(e).__name__}:{e}"
                state["updated_at"] = int(time.time() * 1000)
                write_state(state)
                time.sleep(0.4)

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
