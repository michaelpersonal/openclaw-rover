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
~/.local/bin/rover-remote forward 60
~/.local/bin/rover-remote scan
~/.local/bin/rover-remote spin_to 90
~/.local/bin/rover-remote status
~/.local/bin/rover-remote stop
```

## Obstacle Event Behavior

- If movement returns `event=STOPPED:OBSTACLE` or `error=ERR:OBSTACLE`, inspect the follow-up `auto_recover=*` lines before declaring recovery failed.
- Immediate movement replies return the first status snapshot without a long monitor wait.
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
- On obstacle, Pi Zero attempts local recovery first; Telegram should report the resulting `auto_recover=*` state plus scan summary.
- `status` returns concise operational lines.
- `watch rover <seconds>` streams status at 1Hz for short windows (3-30s).

## Safety Rules

- Speed bound: `0..255`
- Default speed: `60`
- Retry once on error, then issue `stop`
- Always honor explicit stop immediately
