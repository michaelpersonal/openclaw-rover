# Rover Telemetry Monitor Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Live real-time TUI dashboard showing rover motor state, vitals, and command history, fed by telemetry streamed from the OpenClaw plugin over a Unix socket.

**Architecture:** The OpenClaw plugin polls STATUS every 250ms and broadcasts parsed telemetry as JSON lines over a Unix socket. A Python TUI client connects to the socket and renders a live dashboard using `rich`. The same data path works for simulator and real hardware.

**Tech Stack:** TypeScript (plugin additions), Python + rich (TUI client)

---

## Architecture

```
Arduino/Simulator
    ↕ serial (STATUS every 250ms)
OpenClaw Plugin (telemetry server)
    ↕ Unix socket (/tmp/rover-telemetry.sock)
TUI Monitor (rich live display)
```

The plugin is the single owner of the serial port. The monitor never touches serial directly.

## Plugin Additions (index.ts)

### Background STATUS Poller

After serial port connects, start a 250ms interval that:
1. Checks if `pending === null` (no tool call in flight)
2. Sends `STATUS\n` over serial
3. Parses the response into structured telemetry
4. Broadcasts to connected socket clients

Skips the poll when a tool call is in progress to avoid response conflicts.

### Unix Socket Server

Listens on `/tmp/rover-telemetry.sock`. Accepts multiple clients. Broadcasts JSON lines — if no clients are connected, events are silently dropped.

### Message Types

Three JSON line types broadcast to clients:

```json
{"type":"status","motors":{"left":{"dir":"F","speed":150},"right":{"dir":"F","speed":150}},"uptime":12340,"cmds":47,"lastCmd":230,"loopHz":8200,"ts":1772381533}
{"type":"command","cmd":"FORWARD","speed":150,"response":"OK","ts":1772381534}
{"type":"event","event":"STOPPED:WATCHDOG","ts":1772381535}
```

- **status** — parsed STATUS telemetry (every 250ms poll)
- **command** — emitted when a tool call sends a command (name + response)
- **event** — unsolicited messages like STOPPED:WATCHDOG

### Conflict Avoidance

The poller checks `pending === null` before sending STATUS. If a tool call is in flight, the poll is skipped. This prevents:
- The poller's STATUS response being consumed by an in-flight tool call
- A tool call response being consumed by the poller

### Formatted rover_status Output

The `rover_status` tool formats its response for LLM readability:

```
Motors: Left ▲ 150, Right ▲ 150 (moving forward)
Uptime: 00:12:34
Commands: 47 (last 230ms ago)
Loop: 8200 hz
```

## TUI Monitor (monitor/rover_monitor.py)

### Layout

```
┌─ Rover Monitor ────────────────────────────────┐
│                                                 │
│  LEFT MOTOR    ▲ F150  ████████░░░░░░░░░░  59%  │
│  RIGHT MOTOR   ▲ F150  ████████░░░░░░░░░░  59%  │
│                                                 │
│  Uptime: 00:12:34   Loop: 8200 hz               │
│  Commands: 47        Last cmd: 230ms ago         │
│                                                 │
│  ── Recent Events ──────────────────────────────│
│  16:32:01  FORWARD 150      → OK                │
│  16:32:04  STATUS            → motors=F150,F150  │
│  16:32:05  STOPPED:WATCHDOG                      │
│  16:32:06  STOP              → OK                │
└─────────────────────────────────────────────────┘
```

### Panels

1. **Motor Panel** — Two horizontal bars. Direction arrow (▲ forward, ▼ reverse, ■ stopped), speed value, visual bar 0-255. Green=forward, red=reverse, dim=stopped.

2. **Vitals Panel** — Uptime (HH:MM:SS), loop rate, total commands, time since last command.

3. **Event Log** — Last ~20 events. Timestamp + command/event + response. Commands in white, watchdog in yellow, errors in red.

### Connection Handling

- Connects to `/tmp/rover-telemetry.sock`
- Reads JSON lines, updates display state
- On disconnect: shows "Disconnected — waiting for plugin..." and retries every 2 seconds
- Clean exit on Ctrl+C

### Dependencies

- `rich` (pure Python)
- `monitor/requirements.txt`

### Usage

```bash
python3 monitor/rover_monitor.py
```

## Testing

1. **Unit tests** — TUI JSON line parser against all three message types + malformed input
2. **Integration test** — Simulator + plugin + socket → verify valid JSON output
3. **Manual smoke test** — Simulator + OpenClaw + monitor side by side, send commands, watch updates

## File Changes

- **Modify:** `openclaw-plugin/index.ts` — add poller, socket server, command events, formatted status
- **Create:** `monitor/rover_monitor.py` — TUI client
- **Create:** `monitor/requirements.txt` — rich dependency
- **Create:** `monitor/test_monitor.py` — unit tests for JSON parsing
