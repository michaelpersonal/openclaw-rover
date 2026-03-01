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
- [2026-03-01-rover-monitor-design.md](../plans/2026-03-01-rover-monitor-design.md) - Telemetry monitor design (socket, TUI, polling)

## Project Layout
```
rover/
├── arduino/
│   ├── rover/rover.ino             # production firmware (serial parser + motor control)
│   └── rover_test/rover_test.ino   # original integration test sketch
├── simulator/
│   ├── rover_sim.py                # Python simulator (virtual serial port)
│   ├── test_rover_sim.py           # 21 unit tests
│   └── test_serial_integration.py  # 6 integration tests (pty round-trip)
├── openclaw-plugin/
│   ├── index.ts                    # Plugin entry — 8 tools + telemetry server
│   ├── openclaw.plugin.json        # Plugin manifest
│   ├── package.json                # Dependencies (serialport)
│   └── skills/rover/SKILL.md       # LLM instructions for rover control
├── monitor/
│   ├── rover_monitor.py            # Live TUI telemetry dashboard
│   ├── test_monitor.py             # 14 unit tests
│   └── requirements.txt            # Python deps (rich)
├── workspace/
│   ├── SOUL.md                     # Agent personality and values
│   ├── USER.md                     # Human user profile
│   ├── TOOLS.md                    # Environment notes (serial port setup)
│   ├── AGENTS.md                   # Agent operating manual
│   ├── IDENTITY.md                 # Agent name, emoji, vibe
│   └── HEARTBEAT.md                # Periodic task checklist
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
| 2026-03-01 | build | All 4 components built: firmware, simulator, tests, OpenClaw plugin |
| 2026-03-01 | arduino | Firmware compiles clean: 12% flash (3964B), 22% RAM (459B) on Nano |
| 2026-03-01 | simulator | 27 tests pass (21 unit + 6 integration). pty echo must be disabled via tty.setraw() |
| 2026-03-01 | brain | OpenClaw plugin uses registerTool() API, needs serialport npm package |
| 2026-03-01 | comms | Start/stop streaming model with 500ms watchdog safety net |
| 2026-03-01 | comms | 9 commands, 4 response types, ASCII newline-terminated |
| 2026-03-01 | hardware | Split brain: Pi (AI) ↔ USB Serial ↔ Arduino (motors) ↔ TB6612FNG |
| 2026-03-01 | brain | OpenClaw + Gemini → rover plugin → simulator: full pipeline verified working |
| 2026-03-01 | brain | SerialPort needs `lock: false` for pty devices; filter STOPPED:WATCHDOG from pending responses |
| 2026-03-01 | brain | Gemini correctly maps "medium speed" → 150 and sequences multi-tool calls |
| 2026-03-01 | brain | Telemetry monitor: plugin polls STATUS 250ms, streams JSON via Unix socket, TUI reads it |
| 2026-03-01 | brain | Poller and tool calls must use separate pending mechanisms to avoid response mixing |
