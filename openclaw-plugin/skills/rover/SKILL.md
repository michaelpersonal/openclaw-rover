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

## Navigation Tools

- `rover_spin_to(angle)` — Spin to an exact heading (0-359 degrees) using gyroscope. 0=front at startup, 90=right, 180=rear, 270=left.
- `rover_scan()` — Perform a full 360-degree obstacle scan. Returns distance readings at 12 angles (every 30 degrees). Use this when you hit an obstacle and need to find the clearest path.

## Obstacle Navigation

When you encounter an obstacle (STOPPED:OBSTACLE or ERR:OBSTACLE):

1. Call `rover_scan()` to look around — the rover will spin 360 degrees and report distances at each angle
2. Review the distance map — pick the direction with the most clearance
3. Call `rover_spin_to(angle)` to face that direction
4. Call `rover_forward(speed)` to drive ahead
5. Tell the user what you see and why you chose that direction

Example: "I see a wall ahead (12cm) and to the right (18cm). Left side is clear at 120cm — heading that way!"

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
7. If you hit an obstacle, use `rover_scan()` to find a way around it.
8. After scanning, explain your reasoning before moving.
