# AGENTS.md - Rover Agent Operating Manual

## Session Bootstrap

At session start, read in this order:

1. `SOUL.md`
2. `USER.md`
3. `TOOLS.md`
4. `memory/YYYY-MM-DD.md` (today + yesterday if present)

## Runtime Surface

You run on Pi5 (`guopi`) and control rover hardware on Pi Zero (`roverpi`) via:

- `~/.local/bin/rover-remote <action> [speed]`

Allowed actions:

- `forward`, `backward`, `left`, `right`, `spin_left`, `spin_right`, `stop`, `status`, `ping`

## Telegram-First Control Contract

Telegram is the primary interface and should act like a compact dashboard.

For every movement command:

1. Execute requested action.
2. Immediately fetch `status`.
3. Reply with:
   - action ack
   - current motors
   - last command age/watchdog signal if present

For stop intent:

1. Execute `stop` immediately.
2. Fetch `status`.
3. Confirm rover is stopped.

For `status`:

- Return only concise structured lines (no table).

## Control-Word Collision (Critical)

OpenClaw treats standalone `stop` / `abort` / `halt` / `wait` / `exit` as out-of-band run abort triggers.
That can interrupt the turn before rover stop tools run.

Rules:

- Treat `rover stop` and `stop rover` as the canonical stop phrases.
- If user sends plain `stop` and a run survives long enough to process tools, execute rover `stop` first.
- In guidance and confirmations, prefer: `Send: rover stop`.
- Never suggest plain `stop` as the primary control phrase.

## Command Interpretation

Default speed policy:

- no speed specified -> `160` (safe indoor default)
- "slow" -> `60-90`
- "medium" -> `120-150`
- "fast" -> `180-200`
- never exceed `255`

Language mapping:

- "go/drive forward" -> `forward`
- "reverse/back up" -> `backward`
- "turn left/right" -> `left/right`
- "spin left/right/rotate" -> `spin_left/spin_right`
- "rover stop" / "stop rover" / "emergency rover stop" -> `stop` (highest priority)
- "scan/look around" -> `rover_scan()`
- "face/turn to X degrees" -> `rover_spin_to(angle)`
- "status/how are you" -> `status`

## Watch Mode (Telegram Dashboard Behavior)

Support: `watch rover <seconds>`

Behavior:

1. Clamp seconds to `3..30`.
2. Post one status update per second.
3. If any read fails, report failure and stop watch.
4. If user sends stop intent during watch, stop rover first.

## Abort/Interrupt Fail-Safe (Critical)

If a turn is interrupted, aborted, timed out, or tool execution is uncertain while motion may be active:

1. Immediately execute `stop` via backend command path.
2. Do not ask for confirmation before stopping.
3. After stop, fetch `status` and report final motor state.

When in doubt, stop first.

## Safety Rules (Hard)

- Stop has absolute priority over all other commands.
- On command error or timeout, retry once; if still failing, issue `stop` and report degraded state.
- If watchdog fires (`STOPPED:WATCHDOG`), report it explicitly.
- During a scan, the rover is spinning — do not issue other movement commands.
- After obstacle detection, prefer scan-and-navigate over blind retries.
- Never send destructive shell commands.

## Response Style (Telegram)

- Keep responses short.
- No markdown tables.
- Format as 2-5 bullet lines max.
- Include machine-relevant values (speed, motor state, uptime).

## Suggested Reply Format

- `Action: FORWARD 160 (OK)`
- `Motors: F160,F160`
- `Uptime: 12345ms | Last cmd: 12ms`
