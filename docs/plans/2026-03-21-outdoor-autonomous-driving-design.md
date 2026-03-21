# Outdoor Autonomous Driving — Design

Date: 2026-03-21

## Overview

Turn the indoor rover into an outdoor autonomous driving rover using GPS navigation, compass heading, and Google Maps API (deferred). The rover navigates between GPS waypoints using a simple bearing-chase algorithm.

## Architecture

```
User -> Telegram -> Pi5 (OpenClaw agent) -> REST/WiFi -> Pi Zero (roverd) -> USB serial -> Arduino Nano
                                                              |
                                                         GPS (UART)
```

- **Pi5 (stationary, at home)**: OpenClaw agent, Telegram interface, route planning (Maps API in future)
- **Pi Zero (on rover)**: `roverd` daemon — REST API, GPS reader, navigation loop, serial bridge to Arduino
- **Arduino Nano (on rover)**: Motors, ultrasonic, gyro, compass — real-time sensor/motor control
- **Connectivity**: Phone hotspot (WiFi) for outdoor; home WiFi for indoor

## Hardware Changes

### New Devices (Phase 1, ~$20-30)

| Device | Purpose | Connection |
|--------|---------|------------|
| NEO-6M GPS module | Lat/lng positioning | Pi Zero UART (GPIO 14/15) |
| HMC5883L compass/magnetometer | Absolute heading (no drift) | Arduino I2C (A4/A5, shared with gyro) |
| 5V voltage regulator (LM7805 or buck converter) | Power bus | Battery input, 5V output |
| Small breadboard or terminal strip | Power distribution | 5V + GND bus for all devices |

### Pin Allocation — Arduino Nano

| Pin | Use | Device |
|-----|-----|--------|
| D0/D1 | USB serial | Pi Zero (unchanged) |
| D2/D3 | TRIG/ECHO | HC-SR04 ultrasonic (unchanged) |
| D4/D5 | free | reserved for future use |
| D6-D12 | Motor driver | TB6612FNG (unchanged) |
| D13 | free | — |
| A0-A3 | free | — |
| A4/A5 | I2C shared bus | MPU6050 gyro + HMC5883L compass |

### Pin Allocation — Pi Zero GPIO

| GPIO | Use | Device |
|------|-----|--------|
| GPIO 14 (TX) | GPS serial | NEO-6M RX |
| GPIO 15 (RX) | GPS serial | NEO-6M TX |
| USB port | Arduino serial + power | Arduino Nano (unchanged) |

### I2C Shared Bus (Arduino A4/A5)

Compass and gyro share the same two wires via breadboard:
- MPU6050 address: 0x68
- HMC5883L address: 0x1E
- No conflict, no extra pins needed

### Power Distribution

```
Battery -> 5V Regulator -> Power Bus (breadboard rail)
                             +-- Pi Zero (5V)
                             +-- Arduino Nano (5V)
                             +-- HC-SR04 ultrasonic (5V)
                             +-- MPU6050 gyro (5V)
                             +-- HMC5883L compass (5V)
                             +-- NEO-6M GPS (3.3V from Pi Zero or regulator)
                           GND Bus (common ground for all devices)
```

### Future Rewiring (Phase 2, deferred)

When adding cellular modem, move Arduino from USB to GPIO UART to free Pi Zero's USB port:
- Arduino D0/D1 <-> Pi Zero GPIO 14/15 (TX/RX)
- Power from bus instead of USB
- GPS moves to USB dongle or Arduino SoftwareSerial (D4/D5)
- Pi Zero USB freed for cellular dongle
- Requires USB hub or rewiring; details in TODO.md

## Software Design

### `roverd` — Unified Daemon on Pi Zero

Replaces `roverctl.py` and `rover-drive-daemon.py` with a single persistent service.

```
roverd (single Python process)
|-- Serial connection (held open to Arduino, no settle delay)
|-- GPS reader (optional, enabled with --gps flag)
|-- REST API (:8080)
|   |-- POST /command    -> manual motor commands (always available)
|   |-- GET  /status     -> position, heading, trip state (always available)
|   |-- POST /stop       -> stop motors, cancel trip (always available)
|   |-- POST /navigate   -> start waypoint navigation (--gps only)
|   |-- POST /pause      -> pause navigation (--gps only)
|   +-- POST /resume     -> resume navigation (--gps only)
+-- Navigation loop (when mode == "navigating")
```

### Indoor/Outdoor Mode

Determined at startup, not runtime:

| Scenario | Start command | Nav endpoints | Manual endpoints |
|----------|--------------|---------------|-----------------|
| Indoor | `roverd` | disabled (400) | enabled |
| Outdoor | `roverd --gps` | enabled | enabled |

Agent auto-detects mode via `GET /status` response (`gps` field is null or present).

### GPS Reader

- Reads NMEA sentences from `/dev/serial0` at 9600 baud
- Background thread, updates position at ~1Hz
- Parses `$GPRMC` for lat, lng, speed, fix status
- `has_fix` flag gates navigation loop (no fix = stop and wait)

### Compass + Gyro Strategy

- **Compass (HMC5883L)**: Absolute heading (0=North). Used for navigation bearing — no drift over time.
- **Gyro (MPU6050, existing)**: Relative rotation. Used for precise short turns (scan, spin_to).
- Arduino firmware reports both: `STATUS:...heading=127;compass=185;...`

### Navigation Loop (1Hz)

```
while navigating:
  1. Check GPS fix — no fix -> stop, wait
  2. Read Arduino STATUS (compass heading, obstacle distance)
  3. Compute distance to current waypoint
  4. If distance < 5m -> advance to next waypoint or finish
  5. Compute bearing to waypoint
  6. Compute heading error (bearing - compass)
  7. If |error| > 15 deg -> stop, SPIN_TO correct heading
  8. If |error| 5-15 deg -> gentle turn (LEFT/RIGHT 140)
  9. If |error| < 5 deg -> FORWARD 140
  10. If obstacle detected -> stop, scan, pick clearest, drive past, resume
  11. If all directions blocked -> pause, notify user
  12. Sleep 1 second
```

### Bearing and Distance Math

- **Bearing**: `atan2` formula from current GPS position to waypoint (degrees, 0=North)
- **Distance**: Haversine formula (meters)
- **Waypoint arrival**: < 5 meters from target

### REST API Detail

```
POST /navigate
  Body: {"waypoints": [[lat, lng], [lat, lng], ...]}
  Response: {"result": "navigating", "waypoints": 3}

GET /status
  Response: {
    "arduino": {motors, dist, heading, compass, uptime},
    "mode": "navigating|paused|idle",
    "gps": {"lat": 37.38, "lng": -122.08, "fix": true} | null,
    "nav": {"waypoint": 1, "total": 3, "distance_to_wp": 45.2, "bearing": 127}
  }

POST /command
  Body: {"action": "forward", "value": 160}
  Response: {"reply": "OK"}

POST /stop    -> {"result": "stopped", "mode": "idle"}
POST /pause   -> {"result": "paused", "waypoint": 1}
POST /resume  -> {"result": "resumed", "waypoint": 1}
```

### OpenClaw Plugin Changes (Pi5)

Transport change: SSH -> REST for all commands.

New tools:
- `rover_navigate({waypoints})` — POST /navigate
- `rover_nav_status()` — GET /status with nav info
- `rover_pause()` — POST /pause
- `rover_resume()` — POST /resume

Existing tools (`rover_forward`, `rover_stop`, etc.) switch from SSH to `POST /command`.

Agent auto-detects mode: if `/status` returns `gps: null`, nav tools respond with "GPS not enabled."

### AGENTS.md Updates

New command mappings:
- "go to [coordinates]" -> `rover_navigate()`
- "where are you" / "how far" -> `rover_nav_status()`
- "pause" -> `rover_pause()`
- "keep going" / "resume" -> `rover_resume()`
- "navigate to [place]" -> "I need GPS coordinates — Maps API not set up yet"

## v1 Limitations

- **Hardcoded waypoints only** — no Maps API (requires billing setup)
- **Phone hotspot for connectivity** — no dedicated cellular module
- **Simple bearing chase** — no road/polyline following
- **Fixed speed 140** — no terrain-adaptive speed
- **Single front-facing ultrasonic** — limited obstacle detection angle

## Future Enhancements (not in v1)

- Google Maps API integration (Routes + Geocoding) for address-to-waypoint
- Cellular modem for dedicated outdoor connectivity
- Polyline following (stay on roads)
- Wheel encoders for odometry
- Multiple ultrasonic sensors for wider coverage
- Adaptive speed based on terrain/obstacle distance

## Implementation Order

1. Arduino firmware — add HMC5883L compass reading, `compass=` field in STATUS
2. `roverd` — persistent serial + REST API (indoor mode, replaces roverctl.py)
3. Switch Pi5 OpenClaw plugin from SSH to REST
4. GPS reader integration on Pi Zero
5. Navigation loop implementation
6. Plugin navigation tools
7. Outdoor field testing
