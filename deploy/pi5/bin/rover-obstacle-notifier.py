#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

CHECK_INTERVAL_S = 1.0
TELEGRAM_TARGET = "6154094703"
ROVER_AGENT = "rover"
STATE_DIR = Path.home() / ".openclaw" / "workspaces" / "rover" / "state"
LATCH_FILE = STATE_DIR / "obstacle_notifier_latch.json"
LOG_FILE = Path.home() / ".openclaw" / "workspaces" / "rover" / "logs" / "obstacle-notifier.log"


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def fetch_drive_state() -> dict:
    cp = run(["ssh", "roverpi", "cat", str(Path.home() / "rover" / "drive_state.json")], timeout=8)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout).strip() or "ssh state read failed")
    return json.loads(cp.stdout)


def is_obstacle(state: dict) -> bool:
    return state.get("last_event") == "STOPPED:OBSTACLE" or state.get("last_error") == "ERR:OBSTACLE"


def load_latch() -> dict:
    if not LATCH_FILE.exists():
        return {"latched": False, "last_state_updated_at": 0}
    try:
        return json.loads(LATCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"latched": False, "last_state_updated_at": 0}


def save_latch(latched: bool, updated_at: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LATCH_FILE.write_text(json.dumps({"latched": latched, "last_state_updated_at": updated_at}) + "\n", encoding="utf-8")


def trigger_agent_obstacle_flow(state: dict) -> None:
    status_line = state.get("last_status") or ""
    message = (
        "SYSTEM_EVENT: STOPPED:OBSTACLE\n"
        "Source: rover-drive async monitor\n"
        "Instruction: execute obstacle auto-recovery now.\n"
        "1) confirm blocked/stopped\n"
        "2) run rover scan immediately\n"
        "3) send concise Telegram status + scan recommendation\n"
        f"Telemetry: {status_line}"
    )
    cp = run(
        [
            str(Path.home() / ".local" / "bin" / "openclaw"),
            "agent",
            "--agent", ROVER_AGENT,
            "--channel", "telegram",
            "--to", TELEGRAM_TARGET,
            "--reply-account", "rover",
            "--message", message,
            "--deliver",
            "--timeout", "120",
        ],
        timeout=130,
    )
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    log(f"agent_trigger rc={cp.returncode} out={out[:500]} err={err[:500]}")


def main() -> None:
    log("obstacle notifier started")
    while True:
        latch = load_latch()
        latched = bool(latch.get("latched", False))

        try:
            state = fetch_drive_state()
            updated_at = int(state.get("updated_at") or 0)
            obstacle = is_obstacle(state)

            if obstacle and not latched:
                log(f"obstacle edge detected updated_at={updated_at}")
                trigger_agent_obstacle_flow(state)
                latched = True
            elif not obstacle and latched:
                log("obstacle cleared")
                latched = False

            save_latch(latched, updated_at)
        except Exception as e:
            log(f"loop_error {type(e).__name__}: {e}")

        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    main()
