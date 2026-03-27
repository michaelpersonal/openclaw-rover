#!/usr/bin/env python3
import json
import os
import re
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
AUTO_RECOVER_MIN_DIST_CM = 20
DEFAULT_RECOVERY_SPEED = 60
SCAN_STEP_SAMPLES = 12
SCAN_STEP_DEG = 30
SCAN_SPIN_STEP_S = 0.11

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
    mapping = {
        "forward": "FORWARD",
        "backward": "BACKWARD",
        "left": "LEFT",
        "right": "RIGHT",
        "spin_left": "SPIN_LEFT",
        "spin_right": "SPIN_RIGHT",
        "stop": "STOP",
    }
    op = mapping.get(action, "STOP")
    if op == "STOP":
        return "STOP"
    return f"{op} {speed}"


def normalize_angle(value: int) -> int:
    return ((value % 360) + 360) % 360


def parse_status_line(line: str) -> dict[str, str]:
    if "STATUS:" not in line:
        return {}
    body = line.split("STATUS:", 1)[1]
    out: dict[str, str] = {}
    for seg in body.split(";"):
        if "=" in seg:
            key, value = seg.split("=", 1)
            out[key] = value
    return out


def parse_heading(status_line: str) -> int | None:
    parts = parse_status_line(status_line)
    raw = parts.get("heading", "")
    match = re.search(r"(\d+)", raw)
    return int(match.group(1)) if match else None


def parse_scan_value(key: str, scan_out: str) -> str:
    match = re.search(rf"{re.escape(key)}=([^\s]+)", scan_out)
    return match.group(1) if match else ""


def parse_dist_cm(status_line: str) -> int:
    parts = parse_status_line(status_line)
    raw = parts.get("dist", "999")
    match = re.search(r"(\d+)", raw)
    return int(match.group(1)) if match else 999


def format_scan_rows(rows: list[tuple[int, int]]) -> str:
    best = max(rows, key=lambda item: item[1])
    lines = ["SCAN:full_360_fallback_12x30"]
    for logical, dist in rows:
        state = "BLOCKED" if dist < AUTO_RECOVER_MIN_DIST_CM else "clear"
        lines.append(f"angle={logical} dist={dist}cm state={state}")
    lines.append(f"best_angle={best[0]} best_dist={best[1]}cm recommend_move=forward")
    return "\n".join(lines)


def expected_for(cmd: str) -> str:
    op = cmd.split(" ", 1)[0]
    if op == "STATUS":
        return "STATUS:"
    if op == "SCAN":
        return "SCAN:"
    if op == "SPIN_TO":
        return "OK"
    return "OK"


def write_state(payload):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def set_recovery_state(
    state: dict,
    recovery_state: str,
    *,
    reason: str = "",
    scan: str = "",
    move: str = "",
    heading: int | None = None,
):
    state["recovery_state"] = recovery_state
    state["recovery_reason"] = reason
    if scan:
        state["recovery_scan"] = scan
    if move:
        state["recovery_move"] = move
    if heading is not None:
        state["recovery_heading"] = heading


def clear_recovery_state(state: dict):
    state["recovery_state"] = ""
    state["recovery_reason"] = ""
    state["recovery_scan"] = ""
    state["recovery_move"] = ""
    state["recovery_heading"] = None


def promote_obstacle_event(state):
    state["last_event"] = "STOPPED:OBSTACLE"
    state["last_error"] = "ERR:OBSTACLE"
    state["action"] = "stop"
    state["speed"] = 0
    try:
        CMD_FILE.write_text("stop 0\n", encoding="utf-8")
    except Exception:
        pass


def process_line(state, line: str) -> bool:
    if not line:
        return False

    if "STOPPED:OBSTACLE" in line or "ERR:OBSTACLE" in line:
        promote_obstacle_event(state)
        return True

    if "STOPPED:WATCHDOG" in line:
        state["last_event"] = "STOPPED:WATCHDOG"
        state["last_watchdog"] = True

    status_idx = line.find("STATUS:")
    if status_idx >= 0:
        state["last_status"] = line[status_idx:]
        state["last_watchdog"] = False
        return False

    if line.startswith("ERR"):
        state["last_error"] = line
        return False

    state["last_reply"] = line
    return False


def read_serial_lines(ser: serial.Serial, rx_buf: bytes) -> tuple[bytes, list[str]]:
    waiting = ser.in_waiting
    if waiting:
        rx_buf += ser.read(waiting)

    lines: list[str] = []
    while b"\n" in rx_buf:
        raw_line, rx_buf = rx_buf.split(b"\n", 1)
        line = raw_line.decode("utf-8", errors="replace").strip()
        if line:
            lines.append(line)
    return rx_buf, lines


def send_cmd_with_reply(
    ser: serial.Serial,
    rx_buf: bytes,
    state: dict,
    cmd: str,
    *,
    wait_s: float = 1.0,
    attempts: int = 2,
) -> tuple[bytes, str]:
    expect = expected_for(cmd)
    first_nonempty = ""

    for _ in range(attempts):
        ser.write((cmd + "\n").encode("utf-8"))
        deadline = time.time() + wait_s
        while time.time() < deadline:
            rx_buf, lines = read_serial_lines(ser, rx_buf)
            for line in lines:
                process_line(state, line)
                if line == "STOPPED:WATCHDOG":
                    continue
                if not first_nonempty:
                    first_nonempty = line
                if line.startswith("ERR") or line.startswith("STOPPED:"):
                    return rx_buf, line
                if line.startswith(expect):
                    return rx_buf, line
            time.sleep(0.02)

    if first_nonempty:
        return rx_buf, first_nonempty
    raise RuntimeError(f"No response from rover for command: {cmd}")


def run_scan(ser: serial.Serial, rx_buf: bytes, state: dict) -> tuple[bytes, str]:
    rx_buf, reply = send_cmd_with_reply(ser, rx_buf, state, "SCAN", wait_s=3.0, attempts=1)
    if reply == "STOPPED:OBSTACLE":
        ser.reset_input_buffer()
        rx_buf = b""
        rx_buf, reply = send_cmd_with_reply(ser, rx_buf, state, "SCAN", wait_s=3.0, attempts=1)
    if reply.startswith("SCAN:"):
        lines = [reply]
        deadline = time.time() + 1.5
        while time.time() < deadline:
            rx_buf, chunk = read_serial_lines(ser, rx_buf)
            for line in chunk:
                process_line(state, line)
                if line.startswith("angle=") or "best_angle=" in line:
                    lines.append(line)
                    if "best_angle=" in line and "recommend_move=" in line:
                        return rx_buf, "\n".join(lines)
            time.sleep(0.02)
        return rx_buf, "\n".join(lines)

    if reply.startswith("ERR:UNKNOWN_CMD:SCAN"):
        rows: list[tuple[int, int]] = []
        logical = 0
        for i in range(SCAN_STEP_SAMPLES):
            rx_buf, status_line = send_cmd_with_reply(ser, rx_buf, state, "STATUS", wait_s=1.0, attempts=2)
            if status_line.startswith("ERR") or status_line.startswith("STOPPED:"):
                return rx_buf, status_line
            rows.append((logical, parse_dist_cm(status_line)))
            if i < SCAN_STEP_SAMPLES - 1:
                rx_buf, spin_reply = send_cmd_with_reply(ser, rx_buf, state, "SPIN_LEFT 120", wait_s=1.0, attempts=2)
                if spin_reply.startswith("ERR") or spin_reply.startswith("STOPPED:"):
                    return rx_buf, spin_reply
                time.sleep(SCAN_SPIN_STEP_S)
                rx_buf, stop_reply = send_cmd_with_reply(ser, rx_buf, state, "STOP", wait_s=0.8, attempts=1)
                if stop_reply.startswith("ERR") or stop_reply.startswith("STOPPED:"):
                    return rx_buf, stop_reply
                time.sleep(0.04)
                logical = normalize_angle(logical + SCAN_STEP_DEG)
        rx_buf, _ = send_cmd_with_reply(ser, rx_buf, state, "STOP", wait_s=0.8, attempts=1)
        return rx_buf, format_scan_rows(rows)

    if reply.startswith("ERR") or reply.startswith("STOPPED:"):
        return rx_buf, reply
    raise RuntimeError("No scan response from rover")


def rotate_by_scan_angle(
    ser: serial.Serial,
    rx_buf: bytes,
    state: dict,
    logical_angle: int,
) -> tuple[bytes, int]:
    angle = normalize_angle(logical_angle)
    if angle == 0:
        return rx_buf, 0

    if angle <= 180:
        direction = "SPIN_LEFT 120"
        signed_angle = angle
    else:
        direction = "SPIN_RIGHT 120"
        signed_angle = angle - 360

    steps = int(round(abs(signed_angle) / SCAN_STEP_DEG))
    for _ in range(steps):
        rx_buf, spin_reply = send_cmd_with_reply(ser, rx_buf, state, direction, wait_s=1.0, attempts=2)
        if spin_reply.startswith("ERR") or spin_reply.startswith("STOPPED:"):
            return rx_buf, signed_angle
        time.sleep(SCAN_SPIN_STEP_S)
        rx_buf, stop_reply = send_cmd_with_reply(ser, rx_buf, state, "STOP", wait_s=0.8, attempts=1)
        if stop_reply.startswith("ERR") or stop_reply.startswith("STOPPED:"):
            return rx_buf, signed_angle
        time.sleep(0.04)

    return rx_buf, signed_angle


def motors_are_stopped(status_line: str) -> bool:
    parts = parse_status_line(status_line)
    motors = parts.get("motors", "")
    return motors == "S,S"


def attempt_local_recovery(
    ser: serial.Serial,
    rx_buf: bytes,
    state: dict,
    requested_speed: int,
) -> tuple[bytes, bool]:
    start_heading = parse_heading(state.get("last_status", ""))
    recovery_speed = requested_speed or DEFAULT_RECOVERY_SPEED
    recovery_speed = max(1, min(255, recovery_speed))

    set_recovery_state(state, "scanning", reason="STOPPED:OBSTACLE")
    write_state(state)

    try:
        CMD_FILE.write_text("stop 0\n", encoding="utf-8")
    except Exception:
        pass

    try:
        ser.reset_input_buffer()
        rx_buf = b""
        rx_buf, _ = send_cmd_with_reply(ser, rx_buf, state, "STOP", wait_s=0.8, attempts=1)
    except Exception:
        pass

    try:
        rx_buf, scan_out = run_scan(ser, rx_buf, state)
    except Exception as exc:
        set_recovery_state(state, "failed", reason=f"scan_error:{exc}")
        state["last_error"] = f"ERR:AUTO_RECOVER_SCAN:{exc}"
        write_state(state)
        return rx_buf, False

    set_recovery_state(state, "scanning", reason="STOPPED:OBSTACLE", scan=scan_out)
    write_state(state)

    best_angle_raw = parse_scan_value("best_angle", scan_out)
    best_dist_raw = parse_scan_value("best_dist", scan_out).removesuffix("cm")
    recommend_move = parse_scan_value("recommend_move", scan_out).lower()

    if not best_angle_raw or not best_dist_raw or recommend_move not in {"forward", "backward", "left", "right", "spin_left", "spin_right"}:
        set_recovery_state(state, "failed", reason="scan_parse_failed", scan=scan_out)
        state["last_error"] = "ERR:AUTO_RECOVER_PARSE"
        write_state(state)
        return rx_buf, False

    best_angle = int(best_angle_raw)
    best_dist = int(best_dist_raw)
    if best_dist < AUTO_RECOVER_MIN_DIST_CM:
        set_recovery_state(state, "blocked", reason=f"best_dist={best_dist}cm", scan=scan_out)
        state["last_error"] = "ERR:AUTO_RECOVER_BLOCKED"
        write_state(state)
        return rx_buf, False

    if start_heading is None:
        set_recovery_state(state, "failed", reason="missing_heading", scan=scan_out, move=recommend_move)
        state["last_error"] = "ERR:AUTO_RECOVER_HEADING"
        write_state(state)
        return rx_buf, False

    target_heading = normalize_angle(start_heading + best_angle)
    set_recovery_state(
        state,
        "spinning",
        reason="STOPPED:OBSTACLE",
        scan=scan_out,
        move=recommend_move,
        heading=target_heading,
    )
    state["last_error"] = ""
    write_state(state)

    rx_buf, signed_angle = rotate_by_scan_angle(ser, rx_buf, state, best_angle)
    latest_error = state.get("last_error", "")
    if latest_error.startswith("ERR") or latest_error == "ERR:OBSTACLE":
        set_recovery_state(
            state,
            "failed",
            reason=f"spin_failed:{latest_error}",
            scan=scan_out,
            move=recommend_move,
            heading=target_heading,
        )
        state["last_error"] = f"ERR:AUTO_RECOVER_SPIN:{latest_error}"
        write_state(state)
        return rx_buf, False

    state["recovery_heading"] = normalize_angle(start_heading + signed_angle)

    try:
        CMD_FILE.write_text(f"{recommend_move} {recovery_speed}\n", encoding="utf-8")
    except Exception:
        pass

    move_cmd = map_cmd(recommend_move, recovery_speed)
    rx_buf, move_reply = send_cmd_with_reply(ser, rx_buf, state, move_cmd, wait_s=1.0, attempts=2)
    if move_reply.startswith("ERR") or move_reply.startswith("STOPPED:"):
        set_recovery_state(
            state,
            "failed",
            reason=f"resume_failed:{move_reply}",
            scan=scan_out,
            move=recommend_move,
            heading=target_heading,
        )
        state["last_error"] = f"ERR:AUTO_RECOVER_RESUME:{move_reply}"
        write_state(state)
        return rx_buf, False

    rx_buf, status_reply = send_cmd_with_reply(ser, rx_buf, state, "STATUS", wait_s=1.0, attempts=2)
    if status_reply.startswith("ERR") or status_reply.startswith("STOPPED:") or motors_are_stopped(status_reply):
        set_recovery_state(
            state,
            "failed",
            reason=f"resume_not_moving:{status_reply}",
            scan=scan_out,
            move=recommend_move,
            heading=target_heading,
        )
        state["last_error"] = f"ERR:AUTO_RECOVER_RESUME:{status_reply}"
        write_state(state)
        return rx_buf, False

    state["action"] = recommend_move
    state["speed"] = recovery_speed
    state["last_event"] = f"AUTO_RECOVERED:{recommend_move.upper()}"
    state["last_error"] = ""
    state["last_status"] = status_reply
    set_recovery_state(
        state,
        "resumed",
        reason="STOPPED:OBSTACLE",
        scan=scan_out,
        move=recommend_move,
        heading=target_heading,
    )
    write_state(state)
    return rx_buf, True


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
        "recovery_state": "",
        "recovery_reason": "",
        "recovery_scan": "",
        "recovery_move": "",
        "recovery_heading": None,
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
                            last_cmd = cmd
                            state["action"] = action
                            state["speed"] = speed

                        if now - last_status_req >= 0.35:
                            ser.write(b"STATUS\n")
                            last_status_req = now

                        obstacle_detected = False
                        rx_buf, lines = read_serial_lines(ser, rx_buf)
                        for line in lines:
                            if process_line(state, line):
                                obstacle_detected = True

                        if obstacle_detected and action != "stop":
                            rx_buf, recovered = attempt_local_recovery(ser, rx_buf, state, speed)
                            last_cmd = ""
                            last_sent = 0.0
                            last_status_req = 0.0
                            if not recovered:
                                state["action"] = "stop"
                                state["speed"] = 0

                        state["updated_at"] = int(time.time() * 1000)
                        write_state(state)
                        time.sleep(0.02)

            except Exception as exc:
                state["last_error"] = f"daemon_error:{type(exc).__name__}:{exc}"
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
