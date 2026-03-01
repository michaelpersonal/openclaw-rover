# AI Rover Brain — System Design

**Date**: 2026-03-01
**Scope**: Movement commands only. No sensors/vision yet.

## System Overview

Three layers connected by USB Serial:

```
┌─────────────────────────────────────┐
│  OpenClaw (on Raspberry Pi)         │
│  - Receives natural language intent │
│  - Plans movement sequences         │
│  - Sends high-level commands        │
│  - Monitors rover state via STATUS  │
└──────────────┬──────────────────────┘
               │ USB Serial @ 9600 baud
               │ Text protocol, newline-terminated
┌──────────────┴──────────────────────┐
│  Arduino Nano Firmware              │
│  - Parses commands                  │
│  - Translates to motor control      │
│  - Watchdog auto-stop (500ms)       │
│  - Reports telemetry on request     │
└──────────────┬──────────────────────┘
               │ GPIO + PWM
┌──────────────┴──────────────────────┐
│  TB6612FNG → DC Motors              │
└─────────────────────────────────────┘
```

For development, a **Python simulator** replaces the Arduino — speaks the same protocol over a virtual serial port so the OpenClaw skill works identically against real hardware or simulation.

## Serial Protocol

All messages are ASCII text, newline-terminated (`\n`). One command per line, one response per line.

### Commands (Pi → Arduino)

| Command | Format | Example | Behavior |
|---------|--------|---------|----------|
| FORWARD | `FORWARD <speed>` | `FORWARD 180` | Both motors forward |
| BACKWARD | `BACKWARD <speed>` | `BACKWARD 150` | Both motors reverse |
| LEFT | `LEFT <speed>` | `LEFT 120` | Left motor stop, right motor forward |
| RIGHT | `RIGHT <speed>` | `RIGHT 120` | Right motor stop, left motor forward |
| SPIN_LEFT | `SPIN_LEFT <speed>` | `SPIN_LEFT 100` | Left reverse, right forward |
| SPIN_RIGHT | `SPIN_RIGHT <speed>` | `SPIN_RIGHT 100` | Left forward, right reverse |
| STOP | `STOP` | `STOP` | All motors off |
| PING | `PING` | `PING` | Heartbeat check |
| STATUS | `STATUS` | `STATUS` | Request telemetry |

- Speed: 0–255 (PWM value). Invalid values get clamped.
- Commands are case-sensitive.
- Unknown commands get an `ERR` response.

### Responses (Arduino → Pi)

| Response | Format | When |
|----------|--------|------|
| OK | `OK` | Command accepted and executing |
| ERR | `ERR:<message>` | Parse failure or invalid command |
| PONG | `PONG` | Reply to PING |
| STATUS | `STATUS:motors=<L>,<R>;uptime=<ms>;cmds=<n>;last_cmd=<ms>;loop=<hz>` | Reply to STATUS |
| STOPPED | `STOPPED:WATCHDOG` | Auto-stopped due to 500ms timeout |

Motor values in STATUS: `F180` (forward 180), `R120` (reverse 120), `S` (stopped).

### Future Commands (not built now)

- `CURVE <left_speed> <right_speed>` — direct differential control for smooth arcs
- `SPEED <value>` — set default speed without changing direction
- `SCAN` / `READ_SENSORS` — sensor data (when sensors added)
- `CALIBRATE` — motor speed correction
- `SLEEP` / `WAKE` — low-power standby mode

## Arduino Firmware

### Architecture

Non-blocking state machine. No `delay()` calls.

```
setup():
  - Configure motor pins (D6–D12)
  - STBY → HIGH (enable driver)
  - Motors off
  - Serial.begin(9600)
  - Record boot time

loop():
  1. Watchdog check — if >500ms since last command:
     - Auto-stop motors
     - Send STOPPED:WATCHDOG (once, don't spam)
  2. Serial read — byte-by-byte into 64-byte buffer until \n
     - Buffer overflow → discard, send ERR:OVERFLOW
  3. Parse command — split on space, extract name + optional speed
  4. Execute — call setMotors(leftSpeed, leftDir, rightSpeed, rightDir)
  5. Send response (OK / ERR / PONG / STATUS)
  6. Track stats (command count, last command time, loop rate)
```

### Pin Mapping

| Arduino Pin | TB6612FNG | Function |
|-------------|-----------|----------|
| 6 | PWMA | Left motor speed (PWM) |
| 7 | AIN2 | Left motor direction 2 |
| 8 | AIN1 | Left motor direction 1 |
| 9 | BIN1 | Right motor direction 1 |
| 10 | BIN2 | Right motor direction 2 |
| 11 | PWMB | Right motor speed (PWM) |
| 12 | STBY | Standby (HIGH = enabled) |

### Motor Helper

Single function `setMotors(leftSpeed, leftDir, rightSpeed, rightDir)` centralizes all GPIO writes. All commands call this.

### Watchdog

- Timer: `millis()` comparison against last command timestamp
- Timeout: 500ms
- Fires once per timeout (flag resets on next command)
- Sends `STOPPED:WATCHDOG` when triggered

## Simulator

Python script that creates a virtual serial port pair and emulates the Arduino.

```
OpenClaw skill ──→ /dev/pts/X (virtual serial) ──→ Simulator
```

### Responsibilities

- Maintain virtual motor state (left/right speed + direction)
- Parse the same command set as real firmware
- Respond with identical protocol (OK, ERR, STATUS, etc.)
- Implement 500ms watchdog
- Log to terminal: `[12.3s] FORWARD 180 → motors: L=F180 R=F180`
- Track uptime, command count, loop rate for STATUS responses

### Implementation

- Uses Python `pty` module for virtual serial port pair
- Prints which `/dev/pts/X` to connect to on startup
- No external dependencies beyond Python stdlib

### Key Principle

The OpenClaw skill code is identical whether talking to the simulator or the real rover. The only difference is which serial port path is configured.

## OpenClaw Skill

TypeScript skill that registers rover control tools with the OpenClaw agent.

### Tools

| Tool | Args | Serial Command |
|------|------|----------------|
| `rover_forward` | `speed: number` | `FORWARD <speed>` |
| `rover_backward` | `speed: number` | `BACKWARD <speed>` |
| `rover_left` | `speed: number` | `LEFT <speed>` |
| `rover_right` | `speed: number` | `RIGHT <speed>` |
| `rover_spin_left` | `speed: number` | `SPIN_LEFT <speed>` |
| `rover_spin_right` | `speed: number` | `SPIN_RIGHT <speed>` |
| `rover_stop` | none | `STOP` |
| `rover_status` | none | `STATUS` (returns parsed telemetry) |

### Behavior

1. On startup: opens serial port (configurable path)
2. Registers tools with OpenClaw agent runtime
3. Includes system prompt snippet explaining rover capabilities and speed semantics
4. Each tool call: sends command, reads response, returns result to LLM
5. Handles serial errors gracefully

### System Prompt Snippet

Tells the LLM:
- You control a 2WD rover via movement tools
- Speed 0–255: 0=stopped, ~80=slow, ~150=medium, ~200=fast, 255=max
- LEFT/RIGHT = turn by stopping one motor, SPIN = pivot in place
- Call rover_status to check current state
- Always call rover_stop when done moving

## Build Order

1. **Arduino firmware** — serial parser, motor control, watchdog, STATUS
2. **Python simulator** — virtual serial, same protocol, terminal logging
3. **OpenClaw skill** — TypeScript, tool registration, serial bridge
4. **End-to-end test** — chat with OpenClaw → simulator shows movement

## Development Workflow

### Local (no rover)

1. `python simulator.py` → prints virtual serial port path
2. Start OpenClaw with rover skill pointing at simulator port
3. Chat naturally → AI calls tools → simulator logs motor state

### On the rover

1. Flash Arduino firmware via `arduino-cli` or PlatformIO
2. Start OpenClaw on the Pi, skill points at `/dev/ttyUSB0`
3. Same skill, same commands, real motors spin
