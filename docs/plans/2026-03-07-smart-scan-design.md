# Smart Scan with Gyroscope Design

**Date:** 2026-03-07
**Status:** Approved

## Problem

The rover stops when it detects an obstacle but can't navigate around it. We want it to do a curious 360° scan, find the clearest direction, and go that way — with the LLM brain deciding the strategy.

## Approach

Add an MPU6050 gyroscope for precise heading control. Build a `rover_scan` tool that spins the rover 360° in 30° increments, reading distance at each angle. The LLM receives a distance map and decides where to go. A `rover_spin_to` tool lets it spin to a precise heading.

## Hardware

**Module:** GY-521 (MPU6050 breakout), I2C interface.

**Wiring (Arduino Nano):**

| Pin | Function |
|-----|----------|
| A4  | SDA (I2C data) |
| A5  | SCL (I2C clock) |
| 5V  | VCC |
| GND | GND |

No pull-up resistors needed (onboard on GY-521). No level shifting needed (5V tolerant).

**Available pins after this:** D4, D5, D13, A0–A3.

## Firmware Changes (`arduino/rover/rover.ino`)

### Gyroscope Integration

- Use `Wire.h` for I2C (built-in, no external library)
- Initialize MPU6050 in `setup()`: wake from sleep, set gyro sensitivity
- In main loop: read Z-axis gyro rate every cycle, integrate to track heading
- Store heading as `float` in degrees (0–359, wrapping)
- Reset heading to 0 on startup

### New Command: SPIN_TO

| Command | Example | Behavior |
|---------|---------|----------|
| `SPIN_TO <angle>` | `SPIN_TO 90` | Spin to absolute heading (0–359) |

- Firmware picks shortest rotation direction
- Spins at fixed speed, stops when gyro reports target reached
- Responds `OK` when target angle reached
- Timeout after 5 seconds: responds `ERR:SPIN_TIMEOUT`
- Watchdog timeout is paused during SPIN_TO (so it doesn't fire mid-spin)
- Internally non-blocking (main loop keeps running)

### STATUS Telemetry Update

Add `heading=<degrees>` to the STATUS response:

```
STATUS:motors=S,S;dist=42cm;heading=270;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz
```

## Simulator Changes (`simulator/rover_sim.py`)

### Heading Simulation

- Add `heading` state (default 0)
- `SPIN_TO <angle>`: instantly sets heading to target, returns `OK`
- Include `heading=<degrees>` in STATUS responses

### Angle-Based Obstacles

New simulator-only command for testing:

| Command | Effect |
|---------|--------|
| `SET_OBSTACLE_AT <angle> <distance>` | Set distance reading at a specific angle (+-15 degree window) |

When the rover checks distance at a heading matching a set obstacle angle, returns that distance. Otherwise returns 999. This enables test scenarios like "wall at 0 degrees, clear at 90 degrees."

Existing `SET_OBSTACLE` and `CLEAR_OBSTACLE` still work for simple straight-ahead testing.

## Plugin Changes (`openclaw-plugin/index.ts`)

### New Tool: rover_scan

Executes a full 360° scan:

1. Record current heading from STATUS
2. Loop 12 times (0° through 330° in 30° increments):
   - Send `SPIN_TO <angle>`
   - Wait for `OK`
   - Send `STATUS`
   - Record `dist` at this angle
3. Send `SPIN_TO <original_heading>` to return to starting orientation
4. Return formatted scan results

**Response format for LLM:**

```
Scan complete (12 positions, 30 degrees apart):
   0 degrees (front):       12cm  BLOCKED
  30 degrees:               15cm  BLOCKED
  60 degrees:               85cm  clear
  90 degrees (right):      120cm  clear
 120 degrees:              200cm  clear
 150 degrees:              150cm  clear
 180 degrees (rear):        90cm  clear
 210 degrees:               95cm  clear
 240 degrees:               45cm  clear
 270 degrees (left):        30cm  clear
 300 degrees:               18cm  BLOCKED
 330 degrees:               14cm  BLOCKED

Best clearance: 120 degrees at 200cm
Recommendation: spin to 120 degrees then drive forward
```

Broadcasts a `scan` event to the telemetry socket for the monitor.

### New Tool: rover_spin_to

Sends `SPIN_TO <angle>` command. Lets the LLM spin to a precise heading after reviewing scan results.

**Parameters:** `angle` (0–359)

### Telemetry Parsing

- Extract `heading` field from STATUS and include in telemetry stream

## Monitor Changes (`monitor/rover_monitor.py`)

- **Heading display:** Add heading to vitals panel (e.g., `Heading: 270 degrees`)
- **Scan events:** Show scan results in the event log

## Agent Instructions

Update `workspace/AGENTS.md` and `openclaw-plugin/skills/rover/SKILL.md`:

**When you hit an obstacle:**

1. Call `rover_scan` to look around
2. Review the distance map — pick the direction with the most clearance
3. Call `rover_spin_to` to face that direction
4. Call `rover_forward` to drive ahead
5. Report your reasoning to the user ("I see a wall ahead and to the right. Left side is clear at 120cm — heading that way!")

The LLM decides the strategy. The tools give it fast, reliable data and precise movement.

## Implementation Order

1. Firmware — MPU6050 initialization, yaw tracking, SPIN_TO command, heading in STATUS
2. Simulator — heading state, SPIN_TO, SET_OBSTACLE_AT, angle-based distance
3. Simulator tests — gyro and scan scenarios
4. Plugin — rover_scan tool, rover_spin_to tool, heading in telemetry
5. Monitor — heading display, scan events
6. Agent instructions — navigation strategy in skill/workspace docs
7. Docs — update README, AI_HANDOFF
