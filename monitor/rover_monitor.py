"""Rover Telemetry Monitor — live TUI dashboard."""
import json
import socket
import time
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

SOCK_PATH = "/tmp/rover-telemetry.sock"
MAX_EVENTS = 20


def parse_message(line: str) -> dict | None:
    """Parse a JSON line from the telemetry socket."""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


def motor_bar(direction: str, speed: int, width: int = 20) -> Text:
    """Render a motor speed bar with direction indicator."""
    if direction == "S":
        arrow = "■"
        label = "STOP"
        filled = 0
        style = "dim"
    elif direction == "F":
        arrow = "▲"
        label = f"F{speed}"
        filled = round(speed / 255 * width)
        style = "green"
    elif direction == "R":
        arrow = "▼"
        label = f"R{speed}"
        filled = round(speed / 255 * width)
        style = "red"
    else:
        arrow = "?"
        label = "???"
        filled = 0
        style = "dim"

    pct = round(speed / 255 * 100) if speed > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    text = Text()
    text.append(f" {arrow} {label:<6} ", style=style)
    text.append(bar, style=style)
    text.append(f" {pct:>3}%", style=style)
    return text


def format_uptime(ms: int) -> str:
    """Format milliseconds as HH:MM:SS."""
    total_sec = ms // 1000
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_display(state: dict, events: list[dict]) -> Layout:
    """Build the full TUI layout from current state."""
    layout = Layout()
    layout.split_column(
        Layout(name="motors", size=6),
        Layout(name="vitals", size=6),
        Layout(name="events"),
    )

    # Motor panel
    motors = state.get("motors", {})
    left = motors.get("left", {"dir": "S", "speed": 0})
    right = motors.get("right", {"dir": "S", "speed": 0})

    motor_text = Text()
    motor_text.append("  LEFT   ")
    motor_text.append_text(motor_bar(left["dir"], left["speed"]))
    motor_text.append("\n")
    motor_text.append("  RIGHT  ")
    motor_text.append_text(motor_bar(right["dir"], right["speed"]))

    layout["motors"].update(Panel(motor_text, title="Motors", border_style="blue"))

    # Vitals panel
    uptime = format_uptime(state.get("uptime", 0))
    cmds = state.get("cmds", 0)
    last_cmd = state.get("lastCmd", 0)
    loop_hz = state.get("loopHz", 0)
    dist = state.get("dist", 999)
    heading = state.get("heading", 0)

    vitals = Text()
    if dist < 20:
        vitals.append(f"  Distance: {dist}cm ", style="bold red")
        vitals.append("BLOCKED\n", style="bold red")
    elif dist < 999:
        vitals.append(f"  Distance: {dist}cm\n")
    else:
        vitals.append(f"  Distance: clear\n")
    vitals.append(f"  Heading: {heading}deg\n")
    vitals.append(f"  Uptime: {uptime}      Loop: {loop_hz} hz\n")
    vitals.append(f"  Commands: {cmds}        Last cmd: {last_cmd}ms ago")

    layout["vitals"].update(Panel(vitals, title="Vitals", border_style="blue"))

    # Events panel
    event_table = Table(show_header=False, expand=True, box=None, padding=(0, 1))
    event_table.add_column("time", style="dim", width=10)
    event_table.add_column("event", ratio=1)
    event_table.add_column("response", ratio=1)

    for ev in events[-MAX_EVENTS:]:
        ts = datetime.fromtimestamp(ev.get("ts", 0) / 1000).strftime("%H:%M:%S")
        if ev.get("type") == "command":
            cmd = ev.get("cmd", "")
            speed = ev.get("speed", "")
            cmd_str = f"{cmd} {speed}".strip() if speed != "" else cmd
            resp = ev.get("response", "")
            event_table.add_row(ts, Text(cmd_str, style="white"), Text(f"→ {resp}", style="dim"))
        elif ev.get("type") == "event":
            event_name = ev.get("event", "")
            style = "yellow" if "WATCHDOG" in event_name else "red bold" if "OBSTACLE" in event_name else "cyan" if "SCAN" in event_name else "red" if "ERR" in event_name else "white"
            event_table.add_row(ts, Text(event_name, style=style), Text(""))

    layout["events"].update(Panel(event_table, title="Recent Events", border_style="blue"))

    return layout


def connect_socket() -> socket.socket | None:
    """Try to connect to the telemetry Unix socket."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCK_PATH)
        sock.setblocking(False)
        return sock
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None


def main():
    console = Console()
    state: dict = {}
    events: list[dict] = []
    sock: socket.socket | None = None
    buf = ""

    console.print("[bold blue]Rover Monitor[/bold blue] — connecting to telemetry socket...")

    with Live(console=console, refresh_per_second=4, screen=True) as live:
        while True:
            try:
                # Connect if needed
                if sock is None:
                    sock = connect_socket()
                    if sock is None:
                        live.update(
                            Panel(
                                "[dim]Waiting for plugin... (no socket at /tmp/rover-telemetry.sock)[/dim]",
                                title="Rover Monitor",
                                border_style="yellow",
                            )
                        )
                        time.sleep(2)
                        continue

                # Read available data
                try:
                    data = sock.recv(4096)
                    if not data:
                        sock.close()
                        sock = None
                        continue
                    buf += data.decode("utf-8", errors="replace")
                except BlockingIOError:
                    pass
                except (ConnectionResetError, BrokenPipeError, OSError):
                    sock.close()
                    sock = None
                    continue

                # Process complete JSON lines
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    msg = parse_message(line)
                    if msg is None:
                        continue
                    if msg.get("type") == "status":
                        state = msg
                    elif msg.get("type") in ("command", "event"):
                        events.append(msg)
                        if len(events) > MAX_EVENTS * 2:
                            events = events[-MAX_EVENTS:]

                # Render
                if state:
                    live.update(build_display(state, events))

                time.sleep(0.05)

            except KeyboardInterrupt:
                break

    console.print("[bold]Monitor stopped.[/bold]")


if __name__ == "__main__":
    main()
