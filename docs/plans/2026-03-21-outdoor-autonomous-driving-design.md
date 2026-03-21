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
| GY-271 breakout (HMC5883L or QMC5883L compass) | Absolute heading (no drift) | Arduino I2C (A4/A5, shared with gyro). Must be a 5V-tolerant breakout with onboard regulator (GY-271 has this). If using a bare 3.3V-only module, power from 3.3V instead. |
| 5V buck converter (e.g., MP1584 or LM2596 module) | Power bus | Battery input, 5V output. Do NOT use a linear regulator (LM7805) — insufficient dropout margin with 4xAA and wastes power as heat with LiPo. |
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
|-- REST API (127.0.0.1:8080 by default, --token for bearer auth on mutating endpoints)
|   |-- POST /command    -> manual motor commands (always available)
|   |-- POST /scan       -> 360-degree obstacle scan (always available)
|   |-- GET  /status     -> position, heading, trip state (always available)
|   |-- POST /stop       -> stop motors, cancel trip (always available)
|   |-- POST /navigate   -> start waypoint navigation (--gps only, rejects if already navigating)
|   |-- POST /pause      -> pause navigation (--gps only)
|   +-- POST /resume     -> resume navigation (--gps only)
+-- Navigation loop (single owned task, when mode == "navigating")
```

Security: `roverd` binds to `127.0.0.1` by default. Use `--listen 0.0.0.0 --token <secret>` to expose externally — all mutating endpoints (POST) require `Authorization: Bearer <token>` header.

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
- Parses any `*RMC` sentence (`$GPRMC`, `$GNRMC`, etc.) for lat, lng, speed, fix status
- Tracks `last_fix_time` — navigation loop treats fixes older than 3 seconds as stale (equivalent to no fix)
- `has_fix` flag gates navigation loop (no fix or stale fix = stop and wait)

### Compass + Gyro Strategy

- **Compass (HMC5883L)**: Absolute heading (0=North). Used for navigation bearing — no drift over time. Known limitation: raw `atan2` heading without hard-iron/soft-iron calibration or tilt compensation. Mount as far from motors as possible. Expect coarse accuracy (~15-30 degrees error near motors). v1 uses wider steering thresholds to compensate.
- **Gyro (MPU6050, existing)**: Relative rotation. Used for precise short turns (scan, spin_to).
- Arduino firmware reports both: `STATUS:...heading=127;compass=185;...`
- Future: add compass calibration routine (rotate 360, record min/max, compute offsets).

### Navigation Loop (1Hz)

```
while navigating:
  1. Check GPS fix — no fix -> stop, wait
  2. Read Arduino STATUS (compass heading, obstacle distance)
  3. Check GPS staleness — if last fix > 3s old, treat as no fix -> stop, wait
  4. Compute distance to current waypoint
  5. If distance < 8m for 3 consecutive fixes -> advance to next waypoint or finish
  6. Compute bearing to waypoint
  7. Compute heading error (bearing - compass)
  8. If |error| > 20 deg -> stop, SPIN_TO correct heading
  9. If |error| 8-20 deg -> gentle turn (LEFT/RIGHT 140)
  10. If |error| < 8 deg -> FORWARD 140
  11. If obstacle detected -> stop and pause, notify user for decision
  12. Sleep 1 second
```

### Bearing and Distance Math

- **Bearing**: `atan2` formula from current GPS position to waypoint (degrees, 0=North)
- **Distance**: Haversine formula (meters)
- **Waypoint arrival**: < 8 meters from target, confirmed by 3 consecutive in-radius fixes (avoids false arrival from GPS jitter)

### REST API Detail

```
POST /navigate
  Body: {"waypoints": [[lat, lng], [lat, lng], ...]}
  Response: {"result": "navigating", "waypoints": 3}

GET /status
  Response: {
    "arduino": {motors, dist, heading, compass, uptime},
    "mode": "navigating|paused|idle",
    "gps": {"lat": 37.38, "lng": -122.08, "fix": true, "age_s": 0.8} | null,
    "nav": {"waypoint": 1, "total": 3, "distance_to_wp": 45.2, "bearing": 127}
  }
  Note: "waypoint" is 1-based for user-facing display.
  "gps.age_s" is seconds since last valid fix (> 3.0 = stale).

POST /command
  Body: {"action": "forward", "value": 160}
  Response: {"reply": "OK"}

POST /scan
  Response: {"scan": [...angles/distances...], "best_angle": 270, "best_dist": 150}

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

Existing tools (`rover_forward`, `rover_stop`, `rover_scan`, etc.) switch from SSH to `POST /command` and `POST /scan`.

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
- **Obstacle = stop and wait for operator** — no autonomous obstacle avoidance in v1 (scan available for operator use but nav loop does not auto-reroute)
- **Compass is coarse** — no hard-iron/soft-iron calibration, no tilt compensation, wider steering thresholds (8/20 deg) to compensate
- **GPS arrival threshold is 8m** — consumer GPS accuracy limits precision, 3 consecutive fixes required to advance waypoint

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
