# Obstacle Avoidance Design

**Date:** 2026-03-07
**Status:** Approved

## Problem

The rover drives forward blindly and crashes into obstacles. It needs a reflexive, Arduino-level safety mechanism to detect and stop before hitting things.

## Approach

Single ultrasonic sensor on the Arduino. The firmware handles obstacle detection autonomously — no AI involvement required to stop. The AI agent is notified so it can decide how to navigate around.

## Hardware

**Sensor:** HC-SR04 ultrasonic, mounted front-center on the chassis.

**Wiring (Arduino Nano):**

| Pin | Function |
|-----|----------|
| D2  | TRIG (output) |
| D3  | ECHO (input) |
| 5V  | VCC |
| GND | GND |

D2 and D3 are the first two free GPIO pins. The HC-SR04 runs at 5V natively — no level shifting needed.

**Mounting:** Zip-tie or hot-glue to front of chassis, facing forward, at bumper height.

## Firmware Changes (`arduino/rover/rover.ino`)

### Distance Measurement

- Trigger a measurement every ~60ms (HC-SR04 needs ~50ms between readings)
- Use `pulseIn()` with a short timeout to keep the loop non-blocking
- No `delay()` calls — consistent with existing design

### Obstacle Threshold

- **20cm** — when measured distance is below this, the rover is "blocked"

### Behavior When Blocked

1. Auto-stop motors (same pattern as the watchdog)
2. Send `STOPPED:OBSTACLE` once over serial
3. Set an `obstacleBlocked` flag
4. While flag is set:
   - `FORWARD` → rejected with `ERR:OBSTACLE`
   - `BACKWARD`, `LEFT`, `RIGHT`, `SPIN_LEFT`, `SPIN_RIGHT`, `STOP` → allowed normally
5. Flag clears automatically when next reading shows distance >= 20cm

### STATUS Telemetry Update

Add `dist=<cm>` to the STATUS response:

```
STATUS:motors=F180,F180;dist=15cm;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz
```

## Simulator Changes (`simulator/rover_sim.py`)

### Simulated Obstacle Commands

Two new simulator-only commands for testing (not part of the real firmware):

| Command | Effect |
|---------|--------|
| `SET_OBSTACLE <distance>` | Set simulated distance in cm |
| `CLEAR_OBSTACLE` | Reset to no obstacle (distance = 999) |

### Behavior

- Applies the same logic as firmware: distance < 20cm triggers auto-stop, rejects FORWARD with `ERR:OBSTACLE`, sends `STOPPED:OBSTACLE`
- Includes `dist=` in STATUS responses
- Default state: no obstacle (distance = 999), so existing tests pass unchanged

## Protocol Changes

### New Messages (Arduino to Pi)

| Message | When |
|---------|------|
| `STOPPED:OBSTACLE` | Distance dropped below 20cm, motors auto-stopped |
| `ERR:OBSTACLE` | FORWARD command rejected while obstacle is present |

### Modified Messages

| Message | Change |
|---------|--------|
| `STATUS:...` | Added `dist=<cm>` field |

No new Pi-to-Arduino commands needed. The sensor is autonomous on the Arduino side.

## OpenClaw Plugin Changes (`openclaw-plugin/index.ts`)

- **Telemetry parsing:** Extract `dist` field from STATUS and include in telemetry stream
- **Event handling:** Listen for `STOPPED:OBSTACLE` (same pattern as `STOPPED:WATCHDOG`) and surface to the agent
- **No new tools needed:** Existing movement tools pass through `ERR:OBSTACLE` responses so the agent knows to try a different direction

## Monitor Changes (`monitor/rover_monitor.py`)

- **Distance display:** Add distance reading to the vitals panel. Highlight red when below threshold
- **Event log:** Show `STOPPED:OBSTACLE` events in command history, same as watchdog events

## Implementation Order

1. Firmware — add sensor reading and obstacle logic
2. Simulator — add `SET_OBSTACLE`/`CLEAR_OBSTACLE` and matching logic
3. Simulator tests — cover obstacle scenarios
4. Plugin — parse new telemetry fields and obstacle events
5. Monitor — display distance and obstacle events
6. Hardware — wire up sensor, mount, and test on the real rover
