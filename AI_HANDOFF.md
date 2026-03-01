# AI Handoff

Context document for any AI assistant picking up this project.

## What This Project Is

An AI-controlled 2WD rover. A Raspberry Pi Zero 2W runs an OpenClaw agent that interprets natural language ("go forward slowly") and sends serial commands to an Arduino Nano, which drives two DC motors via a TB6612FNG motor driver.

## Current State (2026-03-01)

**What's built and working:**
- Arduino firmware (`arduino/rover/rover.ino`) — compiles clean for `arduino:avr:nano` (12% flash, 22% RAM). Parses 9 serial commands, controls motors, has 500ms watchdog and STATUS telemetry.
- Python simulator (`simulator/rover_sim.py`) — emulates the Arduino over a virtual serial port (pty). 27 tests passing. Full e2e test passing.
- OpenClaw plugin (`openclaw-plugin/`) — registers 8 tools (rover_forward, rover_backward, rover_left, rover_right, rover_spin_left, rover_spin_right, rover_stop, rover_status). Not yet tested with actual OpenClaw runtime.

**What's NOT built yet:**
- No sensors or camera (future)
- No vision/perception pipeline
- OpenClaw plugin not integration-tested with the OpenClaw runtime
- Not yet deployed to the actual Pi or Arduino hardware

## How to Build and Test

```bash
# Arduino: compile-check (no upload without hardware)
arduino-cli compile --fqbn arduino:avr:nano arduino/rover/

# Simulator: run all 27 tests
python3 -m pytest simulator/ -v

# Simulator: run interactive e2e demo
python3 simulator/e2e_test.py
```

## Key Files You Should Read First

1. `docs/plans/2026-03-01-rover-brain-design.md` — full system design (protocol, architecture, all decisions)
2. `docs/project-knowledge/INDEX.md` — knowledge base index with learnings
3. `docs/project-knowledge/domains/arduino.md` — pin wiring, motor mapping, direction truth table
4. `docs/project-knowledge/domains/comms.md` — serial protocol summary

## Architecture

```
OpenClaw (Pi) ──USB Serial 9600 baud──→ Arduino Nano ──GPIO/PWM──→ TB6612FNG ──→ Motors
```

Three software layers:
1. **OpenClaw plugin** (`openclaw-plugin/index.ts`) — TypeScript, registers tools with the agent, bridges serial port
2. **Arduino firmware** (`arduino/rover/rover.ino`) — C++, parses commands, drives motors, watchdog
3. **Simulator** (`simulator/rover_sim.py`) — Python, replaces Arduino for local development

The plugin code is identical for simulator and real hardware. Only the serial port path changes.

## Serial Protocol

ASCII, newline-terminated, 9600 baud. Commands: FORWARD, BACKWARD, LEFT, RIGHT, SPIN_LEFT, SPIN_RIGHT, STOP, PING, STATUS. All take an optional speed (0–255). Responses: OK, ERR:\<msg\>, PONG, STATUS:\<telemetry\>, STOPPED:WATCHDOG.

500ms watchdog: if no command received, motors auto-stop and `STOPPED:WATCHDOG` is sent once.

## Pin Wiring (Arduino Nano → TB6612FNG)

| Pin | Function | Motor |
|-----|----------|-------|
| D6  | PWMA (speed) | Left |
| D7  | AIN2 (dir)   | Left |
| D8  | AIN1 (dir)   | Left |
| D9  | BIN1 (dir)   | Right |
| D10 | BIN2 (dir)   | Right |
| D11 | PWMB (speed) | Right |
| D12 | STBY (enable)| Both |

Available for future sensors: D2–D5, D13, A0–A7.

## Gotchas and Learnings

- **pty echo**: Virtual serial ports have echo enabled by default. Must call `tty.setraw()` on both master and slave fds, otherwise responses loop back as commands (causes `ERR:UNKNOWN_CMD:OK`).
- **No `delay()` in firmware**: The Arduino loop is fully non-blocking so serial reads and watchdog checks happen promptly.
- **Speed clamping**: Both firmware and simulator clamp speed to 0–255. Negative values become 0, values >255 become 255.
- **Motor A = Left, Motor B = Right**: Based on typical 2WD chassis wiring. May need to swap if the physical rover turns the wrong way.
- **Watchdog fires once**: After timeout, sends `STOPPED:WATCHDOG` once and sets a flag. Flag resets on next command.

## Next Steps

1. **Deploy to hardware** — Flash firmware to Nano, verify motors spin correctly, confirm left/right assignment
2. **Install OpenClaw on Pi** — Set up OpenClaw, install the rover plugin, configure serial port
3. **Add sensors** — Ultrasonic distance sensor, camera, etc. Will need new serial commands and firmware extensions
4. **Vision pipeline** — Camera on Pi, image processing, object detection for "go to my wife" type commands

## GitHub

https://github.com/michaelpersonal/openclaw-rover
