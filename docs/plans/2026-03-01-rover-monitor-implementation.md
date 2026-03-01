# Rover Telemetry Monitor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Live TUI dashboard showing rover motor state, vitals, and command history, fed by telemetry streamed from the OpenClaw plugin over a Unix socket.

**Architecture:** The OpenClaw plugin polls STATUS every 250ms and broadcasts parsed JSON lines over a Unix socket (`/tmp/rover-telemetry.sock`). A Python TUI client (`monitor/rover_monitor.py`) connects to the socket and renders a live dashboard using `rich`. The plugin is the sole serial port owner.

**Tech Stack:** TypeScript (plugin), Python + rich (TUI), Unix domain sockets (transport)

---

### Task 1: Plugin Telemetry — STATUS Parser + Socket Server

Add telemetry infrastructure to the OpenClaw plugin: a function to parse STATUS responses into structured objects, a Unix socket server that broadcasts JSON lines to connected clients, and a 250ms background poller.

**Files:**
- Modify: `openclaw-plugin/index.ts`

**Reference:** Design doc at `docs/plans/2026-03-01-rover-monitor-design.md`

**Step 1: Add imports and telemetry types**

At the top of `index.ts`, add `net` and `fs` imports and the telemetry types:

```typescript
import * as net from "net";
import * as fs from "fs";
```

After the `let pending` declaration (line 20), add telemetry state:

```typescript
const SOCK_PATH = "/tmp/rover-telemetry.sock";
let socketServer: net.Server | null = null;
let socketClients: Set<net.Socket> = new Set();
let pollerInterval: ReturnType<typeof setInterval> | null = null;
```

**Step 2: Add STATUS parser function**

After the `toolResult` function (line 46), add a parser that turns the raw STATUS string into a structured object:

```typescript
function parseStatus(raw: string): Record<string, unknown> | null {
  // STATUS:motors=F150,F150;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz
  if (!raw.startsWith("STATUS:")) return null;
  const body = raw.slice(7); // strip "STATUS:"
  const parts: Record<string, string> = {};
  for (const seg of body.split(";")) {
    const eq = seg.indexOf("=");
    if (eq > 0) parts[seg.slice(0, eq)] = seg.slice(eq + 1);
  }

  // Parse motors
  const motorParts = (parts.motors || "S,S").split(",");
  function parseMotor(s: string) {
    if (s === "S") return { dir: "S", speed: 0 };
    return { dir: s[0], speed: parseInt(s.slice(1), 10) || 0 };
  }

  return {
    type: "status",
    motors: { left: parseMotor(motorParts[0]), right: parseMotor(motorParts[1] || "S") },
    uptime: parseInt(parts.uptime || "0", 10),
    cmds: parseInt(parts.cmds || "0", 10),
    lastCmd: parseInt((parts.last_cmd || "0").replace("ms", ""), 10),
    loopHz: parseInt((parts.loop || "0").replace("hz", ""), 10),
    ts: Date.now(),
  };
}
```

**Step 3: Add broadcast and socket server functions**

After `parseStatus`, add:

```typescript
function broadcast(msg: Record<string, unknown>) {
  const line = JSON.stringify(msg) + "\n";
  for (const client of socketClients) {
    try {
      client.write(line);
    } catch {
      socketClients.delete(client);
    }
  }
}

function startSocketServer(logger: PluginApi["logger"]) {
  // Remove stale socket file
  try { fs.unlinkSync(SOCK_PATH); } catch {}

  socketServer = net.createServer((client) => {
    socketClients.add(client);
    client.on("close", () => socketClients.delete(client));
    client.on("error", () => socketClients.delete(client));
  });
  socketServer.listen(SOCK_PATH, () => {
    logger.info(`Telemetry socket: ${SOCK_PATH}`);
  });
  socketServer.on("error", (err) => {
    logger.error(`Telemetry socket error: ${err.message}`);
  });
}
```

**Step 4: Add background STATUS poller**

After the socket server functions, add:

```typescript
function startPoller(logger: PluginApi["logger"]) {
  pollerInterval = setInterval(() => {
    if (!port || !port.isOpen || pending !== null) return; // skip if busy
    // Use sendCommand for the poll — it sets pending, so concurrent tool calls won't collide
    sendCommand("STATUS")
      .then((raw) => {
        const parsed = parseStatus(raw);
        if (parsed) broadcast(parsed);
      })
      .catch(() => {}); // silently ignore poll failures
  }, 250);
}
```

**Step 5: Wire up socket server and poller in register()**

Inside the `register` function, after `api.logger.info(`Rover connected...`)` (line 77), add:

```typescript
      startSocketServer(api.logger);
      startPoller(api.logger);
```

**Step 6: Update data handler to broadcast events**

Update the `parser.on("data")` handler. Replace the watchdog block to also broadcast:

```typescript
      parser.on("data", (line: string) => {
        const trimmed = line.trim();
        if (trimmed === "STOPPED:WATCHDOG") {
          api.logger.warn(`Rover: ${trimmed}`);
          broadcast({ type: "event", event: "STOPPED:WATCHDOG", ts: Date.now() });
          return;
        }
        if (pending) {
          const resolve = pending;
          pending = null;
          resolve(trimmed);
        } else {
          api.logger.warn(`Rover: ${trimmed}`);
        }
      });
```

**Step 7: Update tool execute functions to broadcast commands**

Wrap each movement tool's execute to broadcast the command event. Replace the `rover_forward` execute (and similarly for all movement tools + stop) with a pattern like:

```typescript
    async execute(_id, params) {
      const resp = await sendCommand(`FORWARD ${params.speed}`);
      broadcast({ type: "command", cmd: "FORWARD", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
```

Apply the same pattern to: `rover_backward`, `rover_left`, `rover_right`, `rover_spin_left`, `rover_spin_right`, `rover_stop` (no speed param).

**Step 8: Format rover_status output**

Replace the `rover_status` execute function:

```typescript
    async execute() {
      const resp = await sendCommand("STATUS");
      const parsed = parseStatus(resp);
      if (!parsed) return toolResult(resp);
      const m = parsed.motors as { left: { dir: string; speed: number }; right: { dir: string; speed: number } };
      const dirName = (d: string) => d === "F" ? "▲" : d === "R" ? "▼" : "■";
      const motorDesc = (motor: { dir: string; speed: number }) =>
        motor.dir === "S" ? "stopped" : `${dirName(motor.dir)} ${motor.speed}`;
      const uptimeSec = Math.floor((parsed.uptime as number) / 1000);
      const h = Math.floor(uptimeSec / 3600);
      const m2 = Math.floor((uptimeSec % 3600) / 60);
      const s = uptimeSec % 60;
      const upStr = `${String(h).padStart(2, "0")}:${String(m2).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
      const formatted = [
        `Motors: Left ${motorDesc(m.left)}, Right ${motorDesc(m.right)}`,
        `Uptime: ${upStr}`,
        `Commands: ${parsed.cmds} (last ${parsed.lastCmd}ms ago)`,
        `Loop: ${parsed.loopHz} hz`,
      ].join("\n");
      return toolResult(formatted);
    },
```

**Step 9: Test the plugin changes manually**

Start the simulator, then test the plugin loads and the socket works:

```bash
# Terminal 1: start simulator
python3 -u simulator/rover_sim.py

# Terminal 2: test socket output
# (after starting OpenClaw or just checking the socket exists)
socat - UNIX-CONNECT:/tmp/rover-telemetry.sock
```

Expected: JSON lines streaming every 250ms with type "status".

**Step 10: Commit**

```bash
git add openclaw-plugin/index.ts
git commit -m "feat(openclaw): add telemetry socket server and STATUS poller"
```

---

### Task 2: TUI Monitor — Core Display

Build the Python TUI monitor that connects to the telemetry socket and renders motor state, vitals, and event log.

**Files:**
- Create: `monitor/rover_monitor.py`
- Create: `monitor/requirements.txt`

**Step 1: Create requirements.txt**

```
rich>=13.0
```

**Step 2: Install dependencies**

```bash
pip install rich
```

**Step 3: Write the monitor script**

Create `monitor/rover_monitor.py`:

```python
"""Rover Telemetry Monitor — live TUI dashboard."""
import json
import socket
import sys
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
        bar_style = "dim"
    elif direction == "F":
        arrow = "▲"
        label = f"F{speed}"
        filled = round(speed / 255 * width)
        style = "green"
        bar_style = "green"
    elif direction == "R":
        arrow = "▼"
        label = f"R{speed}"
        filled = round(speed / 255 * width)
        style = "red"
        bar_style = "red"
    else:
        arrow = "?"
        label = "???"
        filled = 0
        style = "dim"
        bar_style = "dim"

    pct = round(speed / 255 * 100) if speed > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    text = Text()
    text.append(f" {arrow} {label:<6} ", style=style)
    text.append(bar, style=bar_style)
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
        Layout(name="vitals", size=4),
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

    vitals = Text()
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
            style = "white"
            event_table.add_row(ts, Text(cmd_str, style=style), Text(f"→ {resp}", style="dim"))
        elif ev.get("type") == "event":
            event_name = ev.get("event", "")
            style = "yellow" if "WATCHDOG" in event_name else "red" if "ERR" in event_name else "white"
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
                    pass  # no data ready
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

                time.sleep(0.05)  # ~20fps check rate, Live refreshes at 4fps

            except KeyboardInterrupt:
                break

    console.print("[bold]Monitor stopped.[/bold]")


if __name__ == "__main__":
    main()
```

**Step 4: Test the monitor connects and renders**

With the simulator and OpenClaw plugin running:

```bash
python3 monitor/rover_monitor.py
```

Expected: Live dashboard showing motor state, vitals updating every 250ms, and command events appearing when tools are called.

If the socket doesn't exist yet, it should show "Waiting for plugin..." and retry.

**Step 5: Commit**

```bash
git add monitor/rover_monitor.py monitor/requirements.txt
git commit -m "feat(monitor): add live TUI telemetry dashboard"
```

---

### Task 3: Unit Tests for Monitor Parsing

**Files:**
- Create: `monitor/test_monitor.py`

**Step 1: Write tests**

```python
"""Tests for rover monitor parsing and display functions."""
import pytest
from rover_monitor import parse_message, motor_bar, format_uptime


class TestParseMessage:
    def test_status_message(self):
        msg = parse_message('{"type":"status","motors":{"left":{"dir":"F","speed":150},"right":{"dir":"F","speed":150}},"uptime":12340,"cmds":47,"lastCmd":230,"loopHz":8200,"ts":1772381533}')
        assert msg is not None
        assert msg["type"] == "status"
        assert msg["motors"]["left"]["dir"] == "F"
        assert msg["motors"]["left"]["speed"] == 150
        assert msg["uptime"] == 12340

    def test_command_message(self):
        msg = parse_message('{"type":"command","cmd":"FORWARD","speed":150,"response":"OK","ts":1772381534}')
        assert msg is not None
        assert msg["type"] == "command"
        assert msg["cmd"] == "FORWARD"
        assert msg["response"] == "OK"

    def test_event_message(self):
        msg = parse_message('{"type":"event","event":"STOPPED:WATCHDOG","ts":1772381535}')
        assert msg is not None
        assert msg["type"] == "event"
        assert msg["event"] == "STOPPED:WATCHDOG"

    def test_malformed_json(self):
        assert parse_message("not json at all") is None
        assert parse_message("{broken") is None
        assert parse_message("") is None

    def test_empty_object(self):
        msg = parse_message("{}")
        assert msg is not None  # valid JSON, just empty


class TestMotorBar:
    def test_stopped(self):
        bar = motor_bar("S", 0)
        assert "STOP" in bar.plain
        assert "0%" in bar.plain

    def test_forward(self):
        bar = motor_bar("F", 150)
        assert "▲" in bar.plain
        assert "F150" in bar.plain

    def test_reverse(self):
        bar = motor_bar("R", 200)
        assert "▼" in bar.plain
        assert "R200" in bar.plain

    def test_full_speed(self):
        bar = motor_bar("F", 255)
        assert "100%" in bar.plain

    def test_zero_speed_forward(self):
        bar = motor_bar("F", 0)
        assert "0%" in bar.plain


class TestFormatUptime:
    def test_zero(self):
        assert format_uptime(0) == "00:00:00"

    def test_seconds(self):
        assert format_uptime(5000) == "00:00:05"

    def test_minutes(self):
        assert format_uptime(90000) == "00:01:30"

    def test_hours(self):
        assert format_uptime(3661000) == "01:01:01"
```

**Step 2: Run the tests**

```bash
cd monitor && python3 -m pytest test_monitor.py -v
```

Expected: All tests pass.

**Step 3: Commit**

```bash
git add monitor/test_monitor.py
git commit -m "test(monitor): add unit tests for parsing and display helpers"
```

---

### Task 4: End-to-End Smoke Test

Verify the full pipeline: simulator → plugin → socket → TUI.

**Files:** No new files — manual verification.

**Step 1: Start the simulator**

```bash
python3 -u simulator/rover_sim.py
# Note the pty path (e.g., /dev/pts/6)
```

**Step 2: Update OpenClaw config with correct pty path**

Ensure `~/.openclaw/openclaw.json` has the correct `serialPort` in `plugins.entries.rover-control.config`.

**Step 3: Start the TUI monitor**

```bash
python3 monitor/rover_monitor.py
```

Expected: Shows "Waiting for plugin..." until OpenClaw starts.

**Step 4: Start OpenClaw and send a command**

```bash
GEMINI_API_KEY=<key> openclaw agent --local --session-id monitor-test --message "move forward slowly, then turn right, then stop"
```

**Step 5: Verify the TUI shows**

- Motor bars updating (green bars for forward, direction changes for right turn, dim for stop)
- Vitals updating every 250ms (uptime ticking, command count incrementing)
- Event log showing FORWARD, RIGHT, STOP commands with → OK responses
- STOPPED:WATCHDOG events in yellow between commands

**Step 6: Verify disconnect/reconnect**

Kill the OpenClaw process. The TUI should show "Waiting for plugin..." and reconnect when OpenClaw restarts.

**Step 7: Commit docs update**

```bash
# Update project knowledge
git add docs/project-knowledge/INDEX.md
git commit -m "docs: update knowledge base with telemetry monitor"
```

---

### Task 5: Update Project Files

Update README, AI_HANDOFF, and knowledge base.

**Files:**
- Modify: `README.md`
- Modify: `AI_HANDOFF.md`
- Modify: `docs/project-knowledge/INDEX.md`
- Modify: `docs/project-knowledge/domains/brain.md`

**Step 1: Update README**

Add a "Monitor" section after "Install the OpenClaw plugin":

```markdown
### Run the telemetry monitor

```bash
pip install rich
python3 monitor/rover_monitor.py
```

The monitor connects to the OpenClaw plugin's telemetry socket and shows live motor state, vitals, and command history.
```

Update the project structure tree to include `monitor/`.

**Step 2: Update AI_HANDOFF.md**

Add monitor to "What's built and working" and update project structure.

**Step 3: Update knowledge base**

Add entries to INDEX.md recent learnings and update brain.md with telemetry architecture.

**Step 4: Commit**

```bash
git add README.md AI_HANDOFF.md docs/project-knowledge/INDEX.md docs/project-knowledge/domains/brain.md
git commit -m "docs: add telemetry monitor to README, AI handoff, and knowledge base"
```
