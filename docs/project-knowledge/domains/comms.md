# Communications Domain

## Serial Protocol
- **Physical**: USB Serial @ 9600 baud (Pi ↔ Arduino Nano)
- **Format**: ASCII text, newline-terminated (`\n`), one message per line
- **Direction**: Bidirectional — commands down, responses up

## Command Reference
See full spec: [2026-03-01-rover-brain-design.md](../../plans/2026-03-01-rover-brain-design.md)

9 commands: FORWARD, BACKWARD, LEFT, RIGHT, SPIN_LEFT, SPIN_RIGHT, STOP, PING, STATUS
4 response types: OK, ERR, PONG, STATUS (telemetry), STOPPED:WATCHDOG

## Watchdog
- 500ms timeout — if no command received, auto-stop motors
- Sends `STOPPED:WATCHDOG` once per timeout event

## Simulator
- Python script using `pty` module for virtual serial port pair
- Speaks identical protocol to real Arduino firmware
- Allows full OpenClaw skill development without hardware
- Same serial port interface — skill code doesn't change

## Key Decision
- Start/stop streaming model (not fire-and-forget with duration)
- AI sends movement commands, rover keeps going until STOP or new command
- Watchdog provides safety net
