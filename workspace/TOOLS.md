# TOOLS.md - Local Notes

## Deployment Topology (Phase 1)

- OpenClaw Gateway + Telegram + LLM run on **Pi5 (`guopi`)**
- Rover hardware/simulator bridge runs on **Pi Zero (`roverpi`)**
- Pi5 controls Pi Zero via SSH wrapper: `~/.local/bin/rover-remote`

## Primary Command Path (Pi5)

```bash
~/.local/bin/rover-remote <forward|backward|left|right|spin_left|spin_right|spin_to|scan|stop|status|ping> [speed|angle]
```

Examples:

```bash
~/.local/bin/rover-remote forward 160
~/.local/bin/rover-remote scan
~/.local/bin/rover-remote spin_to 90
~/.local/bin/rover-remote status
~/.local/bin/rover-remote stop
```

## Obstacle Event Behavior

- If movement returns `event=STOPPED:OBSTACLE` or `error=ERR:OBSTACLE`, treat rover as blocked and stopped.
- `rover-remote` monitors movement for ~15s and auto-runs scan when obstacle is detected.
- Telegram replies should include obstacle note + scan result summary.

## Simulator Controls (Pi Zero)

```bash
~/rover/bin/rover-sim-start
~/rover/bin/rover-sim-status
~/rover/bin/rover-sim-stop
```

When simulator is running, `~/rover/bin/roverctl.py` auto-uses `~/rover/sim_port`.

## Hardware Controls (Pi Zero)

- Expected serial: `/dev/ttyUSB0` or `/dev/ttyACM0`
- Control script:

```bash
~/rover/bin/roverctl.py <forward|backward|left|right|spin_left|spin_right|spin_to|scan|stop|status|ping> [speed|angle]
```

## Telegram Dashboard Expectations

- Every move command returns: action ack + immediate status snapshot.
- On obstacle, Telegram gets explicit blocked note + scan summary.
- `status` returns concise operational lines.
- `watch rover <seconds>` streams status at 1Hz for short windows (3-30s).

## Safety Rules

- Speed bound: `0..255`
- Default speed: `160`
- Retry once on error, then issue `stop`
- Always honor explicit stop immediately
