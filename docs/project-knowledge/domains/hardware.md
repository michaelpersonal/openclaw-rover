# Hardware Domain

## Core Parts
1. **2WD Robot Car Chassis Kit with TT Motor** — base platform, 2 DC motors + wheels
2. **Raspberry Pi Zero 2 W** (Wireless/Bluetooth, 2021) — AI compute layer, runs OpenClaw
3. **Arduino Nano** (ATmega328P) — real-time motor control, see [arduino.md](arduino.md)
4. **WWZMDiB TB6612FNG** Dual Motor Driver — H-bridge, drives both DC motors
5. **Battery / Power Bank** — powers the system (exact specs TBD)

## Architecture: Split Brain

```
┌─────────────────────────────────┐
│  AI Compute — Raspberry Pi      │
│  (OpenClaw agent)               │
└──────────────┬──────────────────┘
               │ USB Serial
               │ (commands down / telemetry up)
┌──────────────┴──────────────────┐
│  Control — Arduino Nano         │
│  (real-time motor control)      │
└──────────────┬──────────────────┘
               │ GPIO (direction + PWM)
┌──────────────┴──────────────────┐
│  Actuation — TB6612FNG          │◄── Battery / Power Bank
│  (dual H-bridge motor driver)   │
└──────────────┬──────────────────┘
               │ High-current motor power
┌──────────────┴──────────────────┐
│  DC Motors + Wheels (2WD)       │
└─────────────────────────────────┘

Future:
┌─────────────────────────────────┐
│  Perception — Sensors           │──→ Analog/Digital to Arduino
│  (ultrasonic, IR, camera, etc.) │
└─────────────────────────────────┘
```

## Communication Path
- **Pi → Arduino**: USB Serial (high-level commands like "go forward at 70%")
- **Arduino → Pi**: USB Serial (telemetry, sensor readings, status)
- **Arduino → TB6612FNG**: GPIO pins for direction, PWM for speed

## Key Design Decisions
- Split brain: Pi handles AI/planning, Arduino handles real-time motor control
- TB6612FNG chosen over L298N (less heat, no voltage drop, logic-level compatible with 5V Nano)
- USB Serial for Pi↔Arduino (simple, reliable, no extra hardware)
- 2WD differential steering (turn by varying left/right motor speeds)
