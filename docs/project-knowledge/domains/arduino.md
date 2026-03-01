# Arduino Domain

## Board
- **Arduino Nano** — ATmega328P, 5V logic, 16MHz
- Connected to Raspberry Pi via **USB Serial**

## Motor Driver: TB6612FNG

### Pin Wiring (Arduino Nano → TB6612FNG)

| Arduino Pin | TB6612FNG Pin | Function |
|-------------|---------------|----------|
| 6 | PWMA | Motor A speed (PWM) |
| 7 | AIN2 | Motor A direction 2 |
| 8 | AIN1 | Motor A direction 1 |
| 9 | BIN1 | Motor B direction 1 |
| 10 | BIN2 | Motor B direction 2 |
| 11 | PWMB | Motor B speed (PWM) |
| 12 | STBY | Standby (HIGH = enabled) |

### Motor Mapping
- **Motor A** (PWMA/AIN1/AIN2) = **Left motor** (based on typical 2WD chassis wiring)
- **Motor B** (PWMB/BIN1/BIN2) = **Right motor**

> Note: Left/right assignment depends on physical wiring. Verify on actual rover.

### Direction Truth Table

| AIN1/BIN1 | AIN2/BIN2 | Result |
|-----------|-----------|--------|
| HIGH | LOW | Forward |
| LOW | HIGH | Reverse |
| LOW | LOW | Coast (free spin) |
| HIGH | HIGH | Brake (short brake) |

### Speed Control
- PWM range: **0–255**
- Test code uses **180** (~70% power) as default speed
- 0 = stopped

### STBY (Standby)
- Must be set **HIGH** in `setup()` to enable the driver
- LOW = all outputs disabled (low-power standby)

## Current Firmware: Integration Test

Minimal forward/reverse loop — no serial communication yet.

```
setup:
  - Configure all 7 pins as OUTPUT
  - STBY → HIGH (enable driver)
  - Both PWMs → 0 (motors off)

loop:
  - Forward at speed 180 for 1.5s
  - Stop for 0.5s
  - Reverse at speed 180 for 1.5s
  - Stop for 1.0s
  - Repeat
```

## What's Missing (Next Steps)
1. **Serial protocol** — No serial communication with Pi yet. Need a command format for the Pi (OpenClaw) to send motor commands and receive telemetry.
2. **Differential steering** — Current code drives both motors at same speed/direction. Need independent L/R control for turning.
3. **Sensor inputs** — No sensors wired yet (ultrasonic, IR, camera are future).
4. **Safety** — No watchdog/timeout. If Pi stops sending commands, motors should auto-stop.

## Available Arduino Nano Pins (unused)
- **Digital**: D0(RX), D1(TX) reserved for USB Serial; D2–D5, D13 free
- **Analog**: A0–A7 all free (for future sensors)
- **PWM-capable**: D3, D5 still available (D6, D9, D10, D11 used by motors)
