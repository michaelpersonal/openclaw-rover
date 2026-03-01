---
name: rover-control
description: Control a 2WD rover with movement commands
---

You control a physical 2WD rover via movement tools. The rover has two DC motors (left and right) driven by a TB6612FNG motor driver, controlled by an Arduino Nano.

## Movement Tools

- `rover_forward(speed)` — Move forward (both motors)
- `rover_backward(speed)` — Move backward (both motors)
- `rover_left(speed)` — Turn left (stop left motor, right motor forward)
- `rover_right(speed)` — Turn right (left motor forward, stop right motor)
- `rover_spin_left(speed)` — Pivot left in place (left reverse, right forward)
- `rover_spin_right(speed)` — Pivot right in place (left forward, right reverse)
- `rover_stop()` — Stop all motors immediately
- `rover_status()` — Get current motor state, uptime, and command count

## Speed Guide

Speed is 0–255 (PWM value):
- ~80 = slow / careful
- ~150 = medium / normal
- ~200 = fast
- 255 = maximum

## Rules

1. The rover keeps moving until you send a new command or `rover_stop()`.
2. A watchdog auto-stops the rover if no command is received for 500ms.
3. Always call `rover_stop()` when done moving.
4. Use `SPIN_LEFT`/`SPIN_RIGHT` for tight turns in place.
5. Use `LEFT`/`RIGHT` for gradual turns while moving forward.
6. Call `rover_status()` to check what the rover is currently doing.
