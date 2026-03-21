# Outdoor Autonomous Rover — Complete Wiring Guide

Date: 2026-03-21

## Components

| # | Device | Role |
|---|--------|------|
| 1 | Battery pack (4xAA or LiPo) | Power source |
| 2 | 5V voltage regulator (LM7805 or buck converter) | Converts battery to stable 5V |
| 3 | Breadboard (small) | Power distribution + I2C bus |
| 4 | Pi Zero | Brain (roverd daemon) |
| 5 | Arduino Nano | Motor/sensor controller |
| 6 | TB6612FNG motor driver | Drives 2 DC motors |
| 7 | HC-SR04 ultrasonic sensor | Front obstacle detection |
| 8 | MPU6050 gyroscope (GY-521) | Rotation sensing |
| 9 | HMC5883L compass/magnetometer | Absolute heading (NEW) |
| 10 | NEO-6M GPS module | GPS position (NEW) |
| 11 | 2x DC motors | Wheels |

## Power Wiring

```
Battery (+) ──→ Regulator IN
Battery (-) ──→ Regulator GND

Regulator 5V OUT ──→ Breadboard 5V rail (+)
Regulator GND    ──→ Breadboard GND rail (-)

From 5V rail:
  Breadboard 5V  ──→ Pi Zero 5V (GPIO pin 2 or 4)
  Breadboard 5V  ──→ Arduino Nano 5V pin
  Breadboard 5V  ──→ HC-SR04 VCC
  Breadboard 5V  ──→ MPU6050 VCC
  Breadboard 5V  ──→ HMC5883L VCC
  Breadboard 5V  ──→ TB6612FNG VCC

From GND rail:
  Breadboard GND ──→ Pi Zero GND (GPIO pin 6)
  Breadboard GND ──→ Arduino Nano GND
  Breadboard GND ──→ HC-SR04 GND
  Breadboard GND ──→ MPU6050 GND
  Breadboard GND ──→ HMC5883L GND
  Breadboard GND ──→ TB6612FNG GND
  Breadboard GND ──→ NEO-6M GND

GPS power (3.3V — do NOT use 5V):
  Pi Zero 3.3V (GPIO pin 1) ──→ NEO-6M VCC

Motor power (direct from battery, bypasses regulator):
  Battery (+) ──→ TB6612FNG VM
  Battery (-) ──→ TB6612FNG GND
```

### Why GPS gets 3.3V not 5V

The NEO-6M operates at 2.7-3.6V. Connecting to 5V will damage it. The Pi Zero 3.3V output pin provides the correct voltage directly.

### Arduino dual power note

With the breadboard power bus, Arduino receives power from BOTH the 5V pin and the USB cable from Pi Zero. This is safe — the Arduino Nano has an internal protection diode that prevents backfeed between the two power sources.

## Data Wiring

### Pi Zero to Arduino (USB cable — unchanged)

```
Pi Zero USB port ──USB cable──→ Arduino Nano USB
```

Carries serial data at 9600 baud. Also provides secondary power.

### Pi Zero to GPS (UART — 2 wires)

```
Pi Zero GPIO 14 (TX, pin 8)  ──→ NEO-6M RX
Pi Zero GPIO 15 (RX, pin 10) ←── NEO-6M TX
```

Cross-wired: TX connects to RX, RX connects to TX.

Pi Zero UART must be enabled and serial console disabled via `raspi-config`:
- Interface Options > Serial Port
- Login shell over serial: NO
- Serial port hardware enabled: YES

### Arduino to Ultrasonic Sensor (2 wires)

```
Arduino D2 ──→ HC-SR04 TRIG
Arduino D3 ──→ HC-SR04 ECHO
```

### Arduino to Motor Driver (7 wires)

```
Arduino D6  ──→ TB6612FNG PWMA
Arduino D7  ──→ TB6612FNG AIN2
Arduino D8  ──→ TB6612FNG AIN1
Arduino D9  ──→ TB6612FNG BIN1
Arduino D10 ──→ TB6612FNG BIN2
Arduino D11 ──→ TB6612FNG PWMB
Arduino D12 ──→ TB6612FNG STBY
```

### Shared I2C Bus — Gyro + Compass (via breadboard)

Both devices share the same two data lines. They have different I2C addresses so there is no conflict.

```
Arduino A4 (SDA) ──→ Breadboard row X
Arduino A5 (SCL) ──→ Breadboard row Y

MPU6050 SDA ──→ Breadboard row X (same row as A4)
MPU6050 SCL ──→ Breadboard row Y (same row as A5)

HMC5883L SDA ──→ Breadboard row X (same row as A4)
HMC5883L SCL ──→ Breadboard row Y (same row as A5)
```

I2C addresses:
- MPU6050 gyroscope: 0x68
- HMC5883L compass: 0x1E

### Motor Driver to Motors (4 wires)

```
TB6612FNG AO1 ──→ Left Motor (+)
TB6612FNG AO2 ──→ Left Motor (-)
TB6612FNG BO1 ──→ Right Motor (+)
TB6612FNG BO2 ──→ Right Motor (-)
```

## Wire Count Summary

| Connection | Wires | Type |
|------------|-------|------|
| Battery → Regulator | 2 | Power |
| Regulator → Breadboard rails | 2 | Power |
| Breadboard 5V → Pi Zero | 1 | Power |
| Breadboard GND → Pi Zero | 1 | Power |
| Breadboard 5V → Arduino | 1 | Power |
| Breadboard GND → Arduino | 1 | Power |
| Breadboard 5V+GND → HC-SR04 | 2 | Power |
| Breadboard 5V+GND → MPU6050 | 2 | Power |
| Breadboard 5V+GND → HMC5883L | 2 | Power |
| Breadboard 5V+GND → TB6612FNG | 2 | Power |
| Pi Zero 3.3V → NEO-6M | 1 | Power |
| Breadboard GND → NEO-6M | 1 | Power |
| Battery → TB6612FNG VM+GND | 2 | Motor power |
| Pi Zero → Arduino | 1 | USB cable |
| Pi Zero → GPS | 2 | UART (TX/RX) |
| Arduino → Ultrasonic | 2 | Data |
| Arduino → Motor driver | 7 | Data |
| Arduino A4 → I2C breadboard | 1 | Data (SDA) |
| Arduino A5 → I2C breadboard | 1 | Data (SCL) |
| MPU6050 → I2C breadboard | 2 | Data (SDA/SCL) |
| HMC5883L → I2C breadboard | 2 | Data (SDA/SCL) |
| Motor driver → Motors | 4 | Motor |
| **Total** | **42 wires** | + 1 USB cable |

## Breadboard Layout

```
    (+) 5V Rail ──────────────────────────────────────
    (-) GND Rail ─────────────────────────────────────

    Row A: [Arduino A4] [MPU6050 SDA] [HMC5883L SDA]    ← I2C SDA bus
    Row B: [Arduino A5] [MPU6050 SCL] [HMC5883L SCL]    ← I2C SCL bus

    Row C: [Regulator 5V OUT] ──jumper──→ (+) rail
    Row D: [Regulator GND]    ──jumper──→ (-) rail
```

All power taps come off the (+) and (-) rails. I2C devices plug into shared rows A and B.

## Pi Zero GPIO Header Pin Map

```
              Pi Zero GPIO Header (40 pins)
    ┌──────────────────────────────────────────────┐
    │ (1) 3.3V → GPS VCC      (2) 5V ← power bus │
    │ (3) GPIO 2 (free)       (4) 5V (spare)      │
    │ (5) GPIO 3 (free)       (6) GND ← power bus │
    │ (7) GPIO 4 (free)       (8) GPIO14 TX → GPS RX │
    │ (9) GND (spare)        (10) GPIO15 RX ← GPS TX │
    │ (11-40) ... all free for future use ...      │
    └──────────────────────────────────────────────┘

    USB port ──→ Arduino Nano (USB cable)
    Micro-USB power ──→ (not used, powered from bus)
```

## Arduino Nano Pin Map

```
    ┌─────────────────────┐
    │     Arduino Nano    │
    ├──────┬──────────────┤
    │ D0   │ USB serial RX (Pi Zero, via USB cable) │
    │ D1   │ USB serial TX (Pi Zero, via USB cable) │
    │ D2   │ HC-SR04 TRIG                           │
    │ D3   │ HC-SR04 ECHO                           │
    │ D4   │ FREE                                   │
    │ D5   │ FREE                                   │
    │ D6   │ TB6612FNG PWMA                         │
    │ D7   │ TB6612FNG AIN2                         │
    │ D8   │ TB6612FNG AIN1                         │
    │ D9   │ TB6612FNG BIN1                         │
    │ D10  │ TB6612FNG BIN2                         │
    │ D11  │ TB6612FNG PWMB                         │
    │ D12  │ TB6612FNG STBY                         │
    │ D13  │ FREE                                   │
    │ A0   │ FREE                                   │
    │ A1   │ FREE                                   │
    │ A2   │ FREE                                   │
    │ A3   │ FREE                                   │
    │ A4   │ I2C SDA → MPU6050 + HMC5883L           │
    │ A5   │ I2C SCL → MPU6050 + HMC5883L           │
    │ 5V   │ ← Power bus (breadboard 5V rail)       │
    │ GND  │ ← Power bus (breadboard GND rail)      │
    │ GND  │ ← (second GND, spare)                  │
    │ 3.3V │ (unused)                               │
    │ VIN  │ (unused)                               │
    └──────┴────────────────────────────────────────┘
```

## Verification Checklist

Before powering on, verify:

- [ ] Regulator output reads 5V with multimeter (no load)
- [ ] GPS VCC connected to 3.3V (NOT 5V)
- [ ] GPS TX→Pi Zero RX, GPS RX→Pi Zero TX (cross-wired)
- [ ] I2C bus: all SDA wires in same breadboard row, all SCL in same row
- [ ] Motor power (VM) comes from battery, not regulator
- [ ] All GND connections share common ground rail
- [ ] No bare wires touching each other
- [ ] Pi Zero serial console disabled via raspi-config

## Troubleshooting

**GPS not getting data**: Check TX/RX are crossed. Check `cat /dev/serial0` shows NMEA sentences. Check 3.3V at GPS VCC pin.

**Compass reads wrong heading**: HMC5883L is sensitive to nearby magnets and motors. Mount as far from motors as possible. Calibrate by rotating 360 degrees and recording min/max values.

**I2C device not detected**: Run `i2cdetect -y 1` on Pi Zero (if connected there) or check with Arduino sketch. Should see 0x68 (gyro) and 0x1E (compass). If missing, check SDA/SCL wiring and that both devices share the same breadboard rows.

**Arduino not responding over USB**: Check USB cable is data-capable (not charge-only). Try different cable. Check `ls /dev/ttyUSB*` on Pi Zero.
