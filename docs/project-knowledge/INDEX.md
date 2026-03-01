# AI Rover - Project Knowledge Base

## Overview
An AI-powered rover built at home. The system has two main software layers:
1. **Arduino firmware** - Low-level motor/sensor control on the rover hardware
2. **AI "Brain"** - Agent-based intelligence (OpenClaw) that makes decisions and commands the rover

Key challenge: developing and testing the brain software remotely without a physical connection to the rover.

## Critical Rules
- OpenClaw skill code must be identical for simulator and real hardware (only serial port path changes)
- Arduino firmware must never use `delay()` — non-blocking loop only
- All serial messages are ASCII, newline-terminated, one per line
- Watchdog: 500ms timeout, auto-stop motors if no command received

## Domains
- [hardware.md](domains/hardware.md) - Physical components, architecture diagram, design decisions
- [arduino.md](domains/arduino.md) - Pin wiring, motor control logic, firmware state, available pins
- [brain.md](domains/brain.md) - OpenClaw agent, skill design, AI reasoning chain
- [comms.md](domains/comms.md) - Serial protocol spec, simulator design

## Design Documents
- [2026-03-01-rover-brain-design.md](../plans/2026-03-01-rover-brain-design.md) - Full system design (protocol, firmware, simulator, skill)

## Project Layout
```
rover/
├── arduino/
│   └── rover_test/rover_test.ino   # current integration test sketch
├── docs/
│   ├── plans/                      # design documents
│   └── project-knowledge/          # this knowledge base
└── rover.pdf                       # original hardware spec from Notion
```

## Build Order
1. Arduino firmware (serial parser, motor control, watchdog, STATUS)
2. Python simulator (virtual serial, same protocol, terminal logging)
3. OpenClaw skill (TypeScript, tool registration, serial bridge)
4. End-to-end test

## Recent Learnings
| Date | Domain | Summary |
|------|--------|---------|
| 2026-03-01 | design | Full brain design completed — protocol, firmware, simulator, skill |
| 2026-03-01 | comms | Start/stop streaming model with 500ms watchdog safety net |
| 2026-03-01 | comms | 9 commands, 4 response types, ASCII newline-terminated |
| 2026-03-01 | brain | OpenClaw skill exposes 8 tools, LLM maps intent to speed values |
| 2026-03-01 | hardware | Split brain: Pi (AI) ↔ USB Serial ↔ Arduino (motors) ↔ TB6612FNG |
| 2026-03-01 | arduino | 7 pins used (D6-D12), D0-D5/D13/A0-A7 available for sensors |
