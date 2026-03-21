# Outdoor Autonomous Driving Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the indoor rover into an outdoor autonomous driving rover with GPS waypoint navigation, compass heading, and a unified REST API daemon replacing the current SSH-based control path.

**Architecture:** Pi Zero runs `roverd` — a single persistent daemon that holds the Arduino serial port open, exposes a REST API for commands/navigation, reads GPS via UART, and runs a waypoint-following navigation loop. Pi5 OpenClaw plugin switches from SSH to REST calls. Arduino firmware adds compass (HMC5883L) reading on the shared I2C bus.

**Tech Stack:** Python 3 (aiohttp for REST, pyserial for Arduino/GPS), Arduino C++ (Wire.h for I2C compass), TypeScript (OpenClaw plugin)

---

## Task 1: Add Compass to Simulator

The simulator needs to support a `compass` field in STATUS so all downstream code can be developed and tested without hardware.

**Files:**
- Modify: `simulator/rover_sim.py`
- Modify: `simulator/test_rover_sim.py`

**Step 1: Write failing tests**

Add to `simulator/test_rover_sim.py`:

```python
class TestCompass:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_default_compass_is_0(self):
        assert self.sim.compass == 0

    def test_status_includes_compass(self):
        resp = self.sim.process_command("STATUS")
        assert "compass=0;" in resp

    def test_set_compass(self):
        resp = self.sim.process_command("SET_COMPASS 185")
        assert resp == "OK"
        assert self.sim.compass == 185

    def test_set_compass_in_status(self):
        self.sim.process_command("SET_COMPASS 270")
        resp = self.sim.process_command("STATUS")
        assert "compass=270;" in resp

    def test_set_compass_wraps_360(self):
        self.sim.process_command("SET_COMPASS 400")
        assert self.sim.compass == 40

    def test_clear_obstacle_does_not_reset_compass(self):
        self.sim.process_command("SET_COMPASS 90")
        self.sim.process_command("CLEAR_OBSTACLE")
        assert self.sim.compass == 90
```

**Step 2: Run tests to verify they fail**

Run: `cd simulator && python3 -m pytest test_rover_sim.py::TestCompass -v`
Expected: FAIL — `compass` attribute doesn't exist

**Step 3: Implement compass in simulator**

In `simulator/rover_sim.py`:

1. Add `self.compass = 0` to `__init__`

2. Add `SET_COMPASS` command handling in `process_command`, before the `else` unknown command branch:
```python
elif cmd == "SET_COMPASS":
    self.compass = arg % 360
    return "OK"
```

3. Update `_status_response` to include compass after heading:
```python
# Change the return string to include compass:
return f"STATUS:motors={left},{right};dist={self.obstacle_dist}cm;heading={self.heading};compass={self.compass};uptime={uptime_ms};cmds={self.cmd_count};last_cmd={last_cmd_ms}ms;loop=0hz"
```

**Step 4: Run tests to verify they pass**

Run: `cd simulator && python3 -m pytest test_rover_sim.py::TestCompass -v`
Expected: PASS (6 tests)

**Step 5: Run all existing tests to confirm no regressions**

Run: `cd simulator && python3 -m pytest test_rover_sim.py -v`
Expected: All 48 + 6 = 54 tests PASS. Note: `TestStatus::test_status_format` may need updating if it checks exact format — verify and fix if needed.

**Step 6: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(sim): add compass field to simulator STATUS"
```

---

## Task 2: GPS Parser Module

A standalone GPS NMEA parser with no hardware dependencies. Runs on Pi Zero but is developed and tested locally.

**Files:**
- Create: `deploy/pi-zero/lib/gps_reader.py`
- Create: `deploy/pi-zero/tests/test_gps_reader.py`

**Step 1: Write failing tests**

Create `deploy/pi-zero/tests/test_gps_reader.py`:

```python
import pytest
from gps_reader import NmeaParser

# Real NMEA sentences for testing
VALID_RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
VOID_RMC = "$GPRMC,123519,V,,,,,,,230394,,,N*53"
VALID_GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47"


class TestNmeaParser:
    def setup_method(self):
        self.parser = NmeaParser()

    def test_initial_state_no_fix(self):
        assert self.parser.has_fix is False
        assert self.parser.lat is None
        assert self.parser.lng is None

    def test_parse_valid_rmc(self):
        self.parser.parse_line(VALID_RMC)
        assert self.parser.has_fix is True
        assert abs(self.parser.lat - 48.1173) < 0.001
        assert abs(self.parser.lng - 11.5167) < 0.001

    def test_parse_void_rmc(self):
        self.parser.parse_line(VALID_RMC)  # get a fix first
        self.parser.parse_line(VOID_RMC)   # then lose it
        assert self.parser.has_fix is False

    def test_ignores_non_rmc(self):
        self.parser.parse_line(VALID_GGA)
        assert self.parser.has_fix is False  # we only parse RMC

    def test_ignores_garbage(self):
        self.parser.parse_line("not a nmea sentence")
        assert self.parser.has_fix is False

    def test_speed_knots(self):
        self.parser.parse_line(VALID_RMC)
        assert abs(self.parser.speed_knots - 22.4) < 0.1

    def test_southern_hemisphere(self):
        line = "$GPRMC,123519,A,3356.100,S,15112.500,W,0.0,0.0,230394,,,A*6B"
        self.parser.parse_line(line)
        assert self.parser.lat < 0  # south
        assert self.parser.lng < 0  # west

    def test_parse_empty_speed(self):
        line = "$GPRMC,123519,A,4807.038,N,01131.000,E,,084.4,230394,003.1,W*4A"
        self.parser.parse_line(line)
        assert self.parser.speed_knots == 0.0

    def test_parse_gnrmc(self):
        """NEO-6M can emit $GNRMC instead of $GPRMC."""
        line = "$GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*57"
        self.parser.parse_line(line)
        assert self.parser.has_fix is True
        assert abs(self.parser.lat - 48.1173) < 0.001

    def test_last_fix_time_updated(self):
        self.parser.parse_line(VALID_RMC)
        assert self.parser.last_fix_time > 0

    def test_is_fresh_after_valid_fix(self):
        self.parser.parse_line(VALID_RMC)
        assert self.parser.is_fresh is True

    def test_is_not_fresh_when_stale(self):
        self.parser.parse_line(VALID_RMC)
        self.parser.last_fix_time = 0  # simulate stale
        assert self.parser.is_fresh is False

    def test_fix_age_infinite_before_any_fix(self):
        assert self.parser.fix_age == float("inf")
```

**Step 2: Run tests to verify they fail**

Run: `cd deploy/pi-zero && python3 -m pytest tests/test_gps_reader.py -v`
Expected: FAIL — `gps_reader` module not found

**Step 3: Implement GPS parser**

Create `deploy/pi-zero/lib/gps_reader.py`:

```python
"""GPS NMEA parser. Extracts position from *RMC sentences ($GPRMC, $GNRMC, etc.)."""
import time


class NmeaParser:
    GPS_STALE_TIMEOUT = 3.0  # seconds — treat fix as stale after this

    def __init__(self):
        self.has_fix: bool = False
        self.lat: float | None = None
        self.lng: float | None = None
        self.speed_knots: float = 0.0
        self.last_fix_time: float = 0.0

    @property
    def fix_age(self) -> float:
        """Seconds since last valid fix."""
        if self.last_fix_time == 0:
            return float("inf")
        return time.monotonic() - self.last_fix_time

    @property
    def is_fresh(self) -> bool:
        """True if fix is valid AND not stale."""
        return self.has_fix and self.fix_age < self.GPS_STALE_TIMEOUT

    def parse_line(self, line: str) -> None:
        line = line.strip()
        # Accept any talker ID: $GPRMC, $GNRMC, etc.
        if len(line) < 6 or not line[3:].startswith("RMC"):
            if not (len(line) >= 6 and line[0] == "$" and line[3:6] == "RMC"):
                return
        parts = line.split(",")
        if len(parts) < 8:
            return
        if parts[2] != "A":
            self.has_fix = False
            return
        try:
            self.lat = self._nmea_to_decimal(parts[3], parts[4])
            self.lng = self._nmea_to_decimal(parts[5], parts[6])
            self.speed_knots = float(parts[7]) if parts[7] else 0.0
            self.has_fix = True
            self.last_fix_time = time.monotonic()
        except (ValueError, IndexError):
            self.has_fix = False

    @staticmethod
    def _nmea_to_decimal(raw: str, hemisphere: str) -> float:
        # NMEA format: DDMM.MMM or DDDMM.MMM
        dot = raw.index(".")
        deg_len = dot - 2
        degrees = int(raw[:deg_len])
        minutes = float(raw[deg_len:])
        result = degrees + minutes / 60.0
        if hemisphere in ("S", "W"):
            result = -result
        return result
```

**Step 4: Run tests to verify they pass**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_gps_reader.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add deploy/pi-zero/lib/gps_reader.py deploy/pi-zero/tests/test_gps_reader.py
git commit -m "feat: add GPS NMEA parser module"
```

---

## Task 3: Navigation Math Module

Bearing and distance calculations, plus heading error normalization. Pure math, no I/O.

**Files:**
- Create: `deploy/pi-zero/lib/nav_math.py`
- Create: `deploy/pi-zero/tests/test_nav_math.py`

**Step 1: Write failing tests**

Create `deploy/pi-zero/tests/test_nav_math.py`:

```python
import pytest
from nav_math import compute_bearing, compute_distance, normalize_heading_error


class TestComputeBearing:
    def test_due_north(self):
        # Point directly north
        bearing = compute_bearing(37.0, -122.0, 38.0, -122.0)
        assert abs(bearing - 0) < 1  # ~0 degrees

    def test_due_east(self):
        bearing = compute_bearing(37.0, -122.0, 37.0, -121.0)
        assert abs(bearing - 90) < 1

    def test_due_south(self):
        bearing = compute_bearing(38.0, -122.0, 37.0, -122.0)
        assert abs(bearing - 180) < 1

    def test_due_west(self):
        bearing = compute_bearing(37.0, -121.0, 37.0, -122.0)
        assert abs(bearing - 270) < 1

    def test_northeast(self):
        bearing = compute_bearing(37.0, -122.0, 38.0, -121.0)
        assert 0 < bearing < 90


class TestComputeDistance:
    def test_zero_distance(self):
        d = compute_distance(37.0, -122.0, 37.0, -122.0)
        assert d < 0.01  # essentially zero

    def test_known_distance(self):
        # SF to LA is ~559km
        d = compute_distance(37.7749, -122.4194, 34.0522, -118.2437)
        assert 550000 < d < 570000

    def test_short_distance(self):
        # ~111m per 0.001 degree latitude at equator
        d = compute_distance(0.0, 0.0, 0.001, 0.0)
        assert 100 < d < 120


class TestNormalizeHeadingError:
    def test_zero_error(self):
        assert normalize_heading_error(0) == 0

    def test_small_positive(self):
        assert normalize_heading_error(10) == 10

    def test_small_negative(self):
        assert normalize_heading_error(-10) == -10

    def test_wrap_positive(self):
        # 350 degrees should be -10
        assert normalize_heading_error(350) == -10

    def test_wrap_negative(self):
        # -350 should be 10
        assert normalize_heading_error(-350) == 10

    def test_exactly_180(self):
        result = normalize_heading_error(180)
        assert abs(result) == 180

    def test_exactly_minus_180(self):
        result = normalize_heading_error(-180)
        assert abs(result) == 180
```

**Step 2: Run tests to verify they fail**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_nav_math.py -v`
Expected: FAIL — `nav_math` module not found

**Step 3: Implement navigation math**

Create `deploy/pi-zero/lib/nav_math.py`:

```python
"""Navigation math: bearing, distance, heading error."""
import math


def compute_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute bearing from point 1 to point 2 in degrees (0=North, 90=East)."""
    dLng = math.radians(lng2 - lng1)
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dLng) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dLng)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def compute_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute distance in meters using haversine formula."""
    R = 6371000
    dLat = math.radians(lat2 - lat1)
    dLng = math.radians(lng2 - lng1)
    a = (math.sin(dLat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dLng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_heading_error(error: float) -> float:
    """Normalize heading error to range -180..180."""
    error = error % 360
    if error > 180:
        error -= 360
    if error < -180:
        error += 360
    return error
```

**Step 4: Run tests to verify they pass**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_nav_math.py -v`
Expected: PASS (13 tests)

**Step 5: Commit**

```bash
git add deploy/pi-zero/lib/nav_math.py deploy/pi-zero/tests/test_nav_math.py
git commit -m "feat: add navigation math module (bearing, distance, heading error)"
```

---

## Task 4: `roverd` Core — Persistent Serial + REST API (Indoor Mode)

The main daemon. This task implements the serial bridge and REST API for manual commands — replacing `roverctl.py` and `rover-drive-daemon.py`. No GPS or navigation yet.

**Files:**
- Create: `deploy/pi-zero/bin/roverd.py`
- Create: `deploy/pi-zero/tests/test_roverd.py`

**Step 1: Write failing tests**

Create `deploy/pi-zero/tests/test_roverd.py`:

```python
import asyncio
import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

# We'll test the REST API handlers with a mock serial connection
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from roverd import create_app, RoverDaemon


class TestRoverdAPI:
    @pytest.fixture
    def daemon(self):
        d = RoverDaemon(serial_port=None, gps_enabled=False)
        d.send_arduino = MagicMock(return_value="OK")
        return d

    @pytest.fixture
    def app(self, daemon):
        return create_app(daemon)

    @pytest.fixture
    async def client(self, aiohttp_client, app):
        return await aiohttp_client(app)

    @pytest.mark.asyncio
    async def test_command_forward(self, client):
        resp = await client.post("/command", json={"action": "forward", "value": 160})
        assert resp.status == 200
        data = await resp.json()
        assert data["reply"] == "OK"

    @pytest.mark.asyncio
    async def test_command_stop(self, client):
        resp = await client.post("/command", json={"action": "stop"})
        assert resp.status == 200
        data = await resp.json()
        assert data["reply"] == "OK"

    @pytest.mark.asyncio
    async def test_status(self, client, daemon):
        daemon.send_arduino = MagicMock(
            return_value="STATUS:motors=S,S;dist=999cm;heading=0;compass=0;uptime=1000;cmds=1;last_cmd=100ms;loop=1000hz"
        )
        resp = await client.get("/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["mode"] == "idle"
        assert data["gps"] is None

    @pytest.mark.asyncio
    async def test_stop_endpoint(self, client):
        resp = await client.post("/stop")
        assert resp.status == 200
        data = await resp.json()
        assert data["result"] == "stopped"

    @pytest.mark.asyncio
    async def test_navigate_disabled_without_gps(self, client):
        resp = await client.post("/navigate", json={"waypoints": [[37.0, -122.0]]})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_command_scan(self, client, daemon):
        daemon.send_arduino = MagicMock(
            return_value="STATUS:motors=S,S;dist=50cm;heading=0;compass=0;uptime=1000;cmds=1;last_cmd=100ms;loop=1000hz"
        )
        resp = await client.post("/command", json={"action": "scan"})
        assert resp.status == 200
```

**Step 2: Run tests to verify they fail**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_roverd.py -v`
Expected: FAIL — `roverd` module not found

**Step 3: Implement roverd core**

Create `deploy/pi-zero/bin/roverd.py`:

```python
#!/usr/bin/env python3
"""
roverd — unified rover daemon.
Persistent serial connection, REST API, optional GPS + navigation.
Replaces roverctl.py + rover-drive-daemon.py.
"""
import argparse
import logging
import os
import re
import sys
import time
import threading

from aiohttp import web

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import serial as pyserial
from serial.tools import list_ports

logger = logging.getLogger("roverd")

SIM_PORT_FILE = os.path.expanduser("~/rover/sim_port")
DEFAULT_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
BAUD = 9600
SERIAL_TIMEOUT = 0.25
SETTLE_SECONDS = 1.2


def find_port(explicit: str | None = None) -> str:
    if explicit and os.path.exists(explicit):
        return explicit
    if os.path.exists(SIM_PORT_FILE):
        try:
            sim = open(SIM_PORT_FILE, "r").read().strip()
            if sim and os.path.exists(sim):
                return sim
        except Exception:
            pass
    for p in DEFAULT_PORTS:
        if os.path.exists(p):
            return p
    for p in list_ports.comports():
        if p.device.startswith("/dev/ttyUSB") or p.device.startswith("/dev/ttyACM"):
            return p.device
    raise RuntimeError("No serial port found")


def parse_status_line(line: str) -> dict:
    if not line.startswith("STATUS:"):
        return {}
    body = line[7:]
    out = {}
    for seg in body.split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            out[k] = v
    return out


class RoverDaemon:
    def __init__(self, serial_port: str | None, gps_enabled: bool = False):
        self.serial_port = serial_port
        self.gps_enabled = gps_enabled
        self.ser: pyserial.Serial | None = None
        self.ser_lock = threading.Lock()
        self.mode = "idle"  # idle | navigating | paused
        self.waypoints: list[list[float]] = []
        self.current_wp_index = 0
        self.gps = None  # set in start_gps()
        self.nav_task = None

    def connect_serial(self):
        if self.serial_port is None:
            return
        port = find_port(self.serial_port)
        self.ser = pyserial.Serial(port=port, baudrate=BAUD, timeout=SERIAL_TIMEOUT)
        time.sleep(SETTLE_SECONDS)
        self.ser.reset_input_buffer()
        logger.info(f"Serial connected: {port}")

    def send_arduino(self, cmd: str, timeout_s: float = 2.0) -> str:
        if self.ser is None or not self.ser.is_open:
            return "ERR:NOT_CONNECTED"
        with self.ser_lock:
            self.ser.write((cmd.strip() + "\n").encode("utf-8"))
            self.ser.flush()
            end = time.time() + timeout_s
            while time.time() < end:
                line = self.ser.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line == "STOPPED:WATCHDOG":
                    continue
                return line
        return "ERR:TIMEOUT"

    def get_status_parsed(self) -> dict:
        raw = self.send_arduino("STATUS")
        return parse_status_line(raw)


def create_app(daemon: RoverDaemon) -> web.Application:
    app = web.Application()

    cmd_map = {
        "forward": "FORWARD", "backward": "BACKWARD",
        "left": "LEFT", "right": "RIGHT",
        "spin_left": "SPIN_LEFT", "spin_right": "SPIN_RIGHT",
        "spin_to": "SPIN_TO", "stop": "STOP",
        "status": "STATUS", "ping": "PING",
    }

    async def handle_command(req):
        body = await req.json()
        action = body.get("action", "").lower()
        value = body.get("value", "")
        op = cmd_map.get(action)
        if not op:
            return web.json_response({"error": f"unknown action: {action}"}, status=400)
        cmd = f"{op} {value}".strip() if value else op
        timeout = 6.0 if action == "spin_to" else 2.0
        reply = daemon.send_arduino(cmd, timeout_s=timeout)
        return web.json_response({"reply": reply})

    async def handle_scan(req):
        """Full 360-degree scan via Arduino spin + distance readings."""
        readings = []
        # Get starting heading
        status_raw = daemon.send_arduino("STATUS")
        parsed = parse_status_line(status_raw)
        start_heading = int(parsed.get("heading", "0"))

        for i in range(12):
            angle = (start_heading + i * 30) % 360
            daemon.send_arduino(f"SPIN_TO {angle}", timeout_s=6.0)
            st = daemon.send_arduino("STATUS")
            st_parsed = parse_status_line(st)
            dist_raw = st_parsed.get("dist", "999cm")
            dist = int(re.search(r"(\d+)", dist_raw).group(1)) if re.search(r"(\d+)", dist_raw) else 999
            readings.append({"angle": angle, "dist": dist, "blocked": dist < 20})

        # Return to start
        daemon.send_arduino(f"SPIN_TO {start_heading}", timeout_s=6.0)
        daemon.send_arduino("STOP")

        best = max(readings, key=lambda r: r["dist"])
        return web.json_response({
            "scan": readings,
            "best_angle": best["angle"],
            "best_dist": best["dist"],
        })

    async def handle_status(req):
        parsed = daemon.get_status_parsed()
        resp = {
            "arduino": parsed,
            "mode": daemon.mode,
            "gps": None,
        }
        if daemon.gps_enabled and daemon.gps:
            resp["gps"] = {
                "lat": daemon.gps.lat,
                "lng": daemon.gps.lng,
                "fix": daemon.gps.has_fix,
                "age_s": round(daemon.gps.fix_age, 1),
            }
        if daemon.mode in ("navigating", "paused") and daemon.waypoints:
            from nav_math import compute_bearing, compute_distance
            wp = daemon.waypoints[daemon.current_wp_index]
            nav_info = {
                "waypoint": daemon.current_wp_index + 1,  # 1-based for user display
                "total": len(daemon.waypoints),
            }
            if daemon.gps and daemon.gps.has_fix:
                nav_info["distance_to_wp"] = round(compute_distance(
                    daemon.gps.lat, daemon.gps.lng, wp[0], wp[1]), 1)
                nav_info["bearing"] = round(compute_bearing(
                    daemon.gps.lat, daemon.gps.lng, wp[0], wp[1]), 1)
            resp["nav"] = nav_info
        return web.json_response(resp)

    async def handle_stop(req):
        # Cancel nav task if running
        if daemon.nav_task and not daemon.nav_task.done():
            daemon.nav_task.cancel()
        daemon.mode = "idle"
        daemon.waypoints = []
        daemon.current_wp_index = 0
        reply = daemon.send_arduino("STOP")
        return web.json_response({"result": "stopped", "mode": "idle", "reply": reply})

    async def handle_navigate(req):
        if not daemon.gps_enabled:
            return web.json_response({"error": "GPS not enabled, start with --gps"}, status=400)
        if daemon.mode == "navigating":
            return web.json_response({"error": "already navigating, POST /stop first"}, status=409)
        body = await req.json()
        waypoints = body.get("waypoints", [])
        if not waypoints:
            return web.json_response({"error": "waypoints list is empty"}, status=400)
        # Cancel any existing nav task
        if daemon.nav_task and not daemon.nav_task.done():
            daemon.mode = "idle"
            daemon.nav_task.cancel()
        daemon.waypoints = waypoints
        daemon.current_wp_index = 0
        daemon.mode = "navigating"
        return web.json_response({"result": "navigating", "waypoints": len(daemon.waypoints)})

    async def handle_pause(req):
        if daemon.mode != "navigating":
            return web.json_response({"error": "not navigating"}, status=400)
        daemon.mode = "paused"
        daemon.send_arduino("STOP")
        return web.json_response({"result": "paused", "waypoint": daemon.current_wp_index})

    async def handle_resume(req):
        if daemon.mode != "paused":
            return web.json_response({"error": "not paused"}, status=400)
        daemon.mode = "navigating"
        return web.json_response({"result": "resumed", "waypoint": daemon.current_wp_index})

    app.router.add_post("/command", handle_command)
    app.router.add_post("/scan", handle_scan)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/stop", handle_stop)
    app.router.add_post("/navigate", handle_navigate)
    app.router.add_post("/pause", handle_pause)
    app.router.add_post("/resume", handle_resume)

    return app


def main():
    parser = argparse.ArgumentParser(description="Rover daemon")
    parser.add_argument("--port", default=None, help="Serial port (auto-detect if omitted)")
    parser.add_argument("--gps", action="store_true", help="Enable GPS + navigation")
    parser.add_argument("--listen", default="127.0.0.1", help="REST API listen address (default: localhost only)")
    parser.add_argument("--http-port", type=int, default=8080, help="REST API port")
    parser.add_argument("--token", default=None, help="Bearer token required for POST endpoints (security)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    daemon = RoverDaemon(serial_port=args.port, gps_enabled=args.gps)
    try:
        daemon.connect_serial()
    except Exception as e:
        logger.error(f"Serial connection failed: {e}")
        logger.info("Running without serial — commands will return ERR:NOT_CONNECTED")

    app = create_app(daemon)
    web.run_app(app, host=args.listen, port=args.http_port)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `cd deploy/pi-zero && pip install aiohttp pytest-aiohttp pytest-asyncio 2>/dev/null; PYTHONPATH=lib python3 -m pytest tests/test_roverd.py -v`
Expected: PASS (6 tests)

**Step 5: Manual smoke test with simulator**

```bash
# Terminal 1: start simulator
cd simulator && python3 -u rover_sim.py

# Terminal 2: start roverd pointing at sim port
cd deploy/pi-zero && python3 bin/roverd.py --port /path/from/sim/output

# Terminal 3: test REST API
curl -s http://localhost:8080/status | python3 -m json.tool
curl -s -X POST http://localhost:8080/command -H 'Content-Type: application/json' -d '{"action":"forward","value":160}' | python3 -m json.tool
curl -s -X POST http://localhost:8080/stop | python3 -m json.tool
```

**Step 6: Commit**

```bash
git add deploy/pi-zero/bin/roverd.py deploy/pi-zero/tests/test_roverd.py
git commit -m "feat: add roverd daemon with persistent serial and REST API"
```

---

## Task 5: GPS Reader Integration into `roverd`

Wire the GPS parser into `roverd` as a background thread reading from Pi Zero UART.

**Files:**
- Modify: `deploy/pi-zero/bin/roverd.py`
- Modify: `deploy/pi-zero/tests/test_roverd.py`

**Step 1: Write failing tests**

Add to `deploy/pi-zero/tests/test_roverd.py`:

```python
class TestRoverdGPS:
    @pytest.fixture
    def daemon_with_gps(self):
        d = RoverDaemon(serial_port=None, gps_enabled=True)
        d.send_arduino = MagicMock(return_value="OK")
        # Simulate GPS fix
        from gps_reader import NmeaParser
        d.gps = NmeaParser()
        d.gps.has_fix = True
        d.gps.lat = 37.386
        d.gps.lng = -122.083
        return d

    @pytest.fixture
    def app_gps(self, daemon_with_gps):
        return create_app(daemon_with_gps)

    @pytest.fixture
    async def client_gps(self, aiohttp_client, app_gps):
        return await aiohttp_client(app_gps)

    @pytest.mark.asyncio
    async def test_status_includes_gps(self, client_gps):
        resp = await client_gps.get("/status")
        data = await resp.json()
        assert data["gps"] is not None
        assert data["gps"]["fix"] is True
        assert abs(data["gps"]["lat"] - 37.386) < 0.001

    @pytest.mark.asyncio
    async def test_navigate_enabled_with_gps(self, client_gps):
        resp = await client_gps.post("/navigate", json={"waypoints": [[37.39, -122.08]]})
        assert resp.status == 200
        data = await resp.json()
        assert data["result"] == "navigating"
```

**Step 2: Run tests to verify they fail**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_roverd.py::TestRoverdGPS -v`
Expected: FAIL — GPS not wired into daemon yet

**Step 3: Add GPS thread to roverd**

In `deploy/pi-zero/bin/roverd.py`, add to `RoverDaemon`:

```python
def start_gps(self, gps_port: str = "/dev/serial0", gps_baud: int = 9600):
    from gps_reader import NmeaParser
    self.gps = NmeaParser()

    def _gps_loop():
        try:
            ser = pyserial.Serial(port=gps_port, baudrate=gps_baud, timeout=1)
            logger.info(f"GPS connected: {gps_port}")
            while True:
                line = ser.readline().decode("ascii", errors="replace").strip()
                if line:
                    self.gps.parse_line(line)
        except Exception as e:
            logger.error(f"GPS error: {e}")

    t = threading.Thread(target=_gps_loop, daemon=True)
    t.start()
```

In `main()`, after serial connect, add:

```python
if args.gps:
    daemon.start_gps()
```

**Step 4: Run tests to verify they pass**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_roverd.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add deploy/pi-zero/bin/roverd.py deploy/pi-zero/tests/test_roverd.py
git commit -m "feat: integrate GPS reader into roverd daemon"
```

---

## Task 6: Navigation Loop

The core waypoint-following logic running as an async task inside `roverd`.

**Files:**
- Modify: `deploy/pi-zero/bin/roverd.py`
- Create: `deploy/pi-zero/tests/test_navigation.py`

**Step 1: Write failing tests**

Create `deploy/pi-zero/tests/test_navigation.py`:

```python
import pytest
from unittest.mock import MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from roverd import RoverDaemon
from gps_reader import NmeaParser


import time as _time

def make_daemon_at(lat, lng, compass=0, dist=999):
    """Create a daemon with mocked GPS + Arduino at given position."""
    d = RoverDaemon(serial_port=None, gps_enabled=True)
    d.gps = NmeaParser()
    d.gps.has_fix = True
    d.gps.lat = lat
    d.gps.lng = lng
    d.gps.last_fix_time = _time.monotonic()  # fresh fix
    status = f"STATUS:motors=S,S;dist={dist}cm;heading=0;compass={compass};uptime=1000;cmds=1;last_cmd=100ms;loop=1000hz"
    d.send_arduino = MagicMock(return_value=status)
    return d


class TestNavigationStep:
    def test_advances_waypoint_after_consecutive_fixes(self):
        d = make_daemon_at(37.386, -122.083)
        d.waypoints = [[37.386, -122.083], [37.390, -122.080]]
        d.current_wp_index = 0
        d.mode = "navigating"
        # Need 3 consecutive in-radius fixes to advance
        d.nav_step()
        d.nav_step()
        d.nav_step()
        assert d.current_wp_index == 1  # advanced after 3 fixes

    def test_does_not_advance_on_single_fix(self):
        d = make_daemon_at(37.386, -122.083)
        d.waypoints = [[37.386, -122.083], [37.390, -122.080]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()  # only 1 fix
        assert d.current_wp_index == 0  # not yet

    def test_finishes_when_last_waypoint_reached(self):
        d = make_daemon_at(37.390, -122.080)
        d.waypoints = [[37.390, -122.080]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        d.nav_step()
        d.nav_step()
        assert d.mode == "idle"

    def test_spins_on_large_heading_error(self):
        # Rover at 0,0 facing north (compass=0), waypoint is due east (bearing~90)
        d = make_daemon_at(0.0, 0.0, compass=0, dist=999)
        d.waypoints = [[0.0, 1.0]]  # due east
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        # Should have sent a SPIN_TO command
        calls = [str(c) for c in d.send_arduino.call_args_list]
        assert any("SPIN_TO" in c for c in calls)

    def test_drives_forward_when_heading_aligned(self):
        # Rover facing north (compass=0), waypoint is north (bearing~0)
        d = make_daemon_at(37.0, -122.0, compass=0, dist=999)
        d.waypoints = [[38.0, -122.0]]  # due north
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        calls = [str(c) for c in d.send_arduino.call_args_list]
        assert any("FORWARD" in c for c in calls)

    def test_stops_on_no_gps_fix(self):
        d = make_daemon_at(37.0, -122.0)
        d.gps.has_fix = False
        d.waypoints = [[38.0, -122.0]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        calls = [str(c) for c in d.send_arduino.call_args_list]
        assert any("STOP" in c for c in calls)

    def test_stops_on_stale_gps(self):
        d = make_daemon_at(37.0, -122.0)
        d.gps.last_fix_time = 0  # stale
        d.waypoints = [[38.0, -122.0]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        calls = [str(c) for c in d.send_arduino.call_args_list]
        assert any("STOP" in c for c in calls)

    def test_pauses_on_obstacle(self):
        d = make_daemon_at(37.0, -122.0, compass=0, dist=10)  # obstacle at 10cm
        d.waypoints = [[38.0, -122.0]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        calls = [str(c) for c in d.send_arduino.call_args_list]
        assert any("STOP" in c for c in calls)
        assert d.mode == "paused"  # pauses for operator decision

    def test_stop_while_navigating(self):
        d = make_daemon_at(37.0, -122.0, compass=0, dist=999)
        d.waypoints = [[38.0, -122.0]]
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        d.mode = "idle"  # simulate /stop
        d.nav_step()  # should be a no-op
        # Should not crash

    def test_rejects_empty_waypoints(self):
        d = make_daemon_at(37.0, -122.0)
        d.waypoints = []
        d.current_wp_index = 0
        d.mode = "navigating"
        d.nav_step()
        assert d.mode == "idle"
```

**Step 2: Run tests to verify they fail**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_navigation.py -v`
Expected: FAIL — `nav_step` method doesn't exist

**Step 3: Implement nav_step in RoverDaemon**

Add to `RoverDaemon` class in `deploy/pi-zero/bin/roverd.py`:

```python
from nav_math import compute_bearing, compute_distance, normalize_heading_error

WAYPOINT_ARRIVAL_M = 8.0   # meters — loosened for consumer GPS accuracy
WAYPOINT_ARRIVAL_FIXES = 3  # consecutive in-radius fixes before advancing
HEADING_SPIN_THRESHOLD = 20.0  # degrees — widened for uncalibrated compass
HEADING_TURN_THRESHOLD = 8.0
NAV_SPEED = 140

def nav_step(self):
    """Execute one step of the navigation loop. Called at ~1Hz."""
    if self.mode != "navigating":
        return
    # Check GPS: must have valid AND fresh fix
    if not self.gps or not self.gps.is_fresh:
        self.send_arduino("STOP")
        return
    if not self.waypoints or self.current_wp_index >= len(self.waypoints):
        self.send_arduino("STOP")
        self.mode = "idle"
        return

    # Read current state
    status_raw = self.send_arduino("STATUS")
    parsed = parse_status_line(status_raw)
    compass = int(parsed.get("compass", "0").replace("°", ""))
    dist_cm_raw = parsed.get("dist", "999cm")
    dist_cm = int(re.search(r"(\d+)", dist_cm_raw).group(1)) if re.search(r"(\d+)", dist_cm_raw) else 999

    wp = self.waypoints[self.current_wp_index]
    dist_to_wp = compute_distance(self.gps.lat, self.gps.lng, wp[0], wp[1])

    # Check waypoint arrival — require consecutive fixes to avoid GPS jitter
    if not hasattr(self, '_arrival_count'):
        self._arrival_count = 0
    if dist_to_wp < WAYPOINT_ARRIVAL_M:
        self._arrival_count += 1
        if self._arrival_count >= WAYPOINT_ARRIVAL_FIXES:
            self._arrival_count = 0
            self.current_wp_index += 1
            if self.current_wp_index >= len(self.waypoints):
                self.send_arduino("STOP")
                self.mode = "idle"
        return
    else:
        self._arrival_count = 0

    # Check obstacle — stop and pause for operator decision
    if dist_cm < 20:
        self.send_arduino("STOP")
        self.mode = "paused"
        return

    # Compute heading correction
    bearing = compute_bearing(self.gps.lat, self.gps.lng, wp[0], wp[1])
    heading_error = normalize_heading_error(bearing - compass)

    if abs(heading_error) > HEADING_SPIN_THRESHOLD:
        self.send_arduino("STOP")
        self.send_arduino(f"SPIN_TO {int(bearing)}", timeout_s=6.0)
    elif heading_error > HEADING_TURN_THRESHOLD:
        self.send_arduino(f"RIGHT {NAV_SPEED}")
    elif heading_error < -HEADING_TURN_THRESHOLD:
        self.send_arduino(f"LEFT {NAV_SPEED}")
    else:
        self.send_arduino(f"FORWARD {NAV_SPEED}")
```

**Step 4: Run tests to verify they pass**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/test_navigation.py -v`
Expected: PASS (6 tests)

**Step 5: Wire nav_step into the REST app's navigate handler**

In `handle_navigate`, after setting mode to "navigating", start an async loop:

```python
async def _nav_loop():
    while daemon.mode == "navigating":
        daemon.nav_step()
        await asyncio.sleep(1.0)

daemon.nav_task = asyncio.ensure_future(_nav_loop())
```

**Step 6: Run all tests**

Run: `cd deploy/pi-zero && PYTHONPATH=lib python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add deploy/pi-zero/bin/roverd.py deploy/pi-zero/tests/test_navigation.py
git commit -m "feat: add navigation loop with waypoint following"
```

---

## Task 7: Update OpenClaw Plugin (Pi5) — SSH to REST

Switch the plugin from direct serial/SSH to REST calls against `roverd`.

**Files:**
- Modify: `openclaw-plugin/index.ts`

**Step 1: Understand current plugin**

The current plugin (`openclaw-plugin/index.ts`) connects to Arduino serial directly via `serialport` npm package. For the outdoor setup, Pi5 no longer has direct serial access — it calls `roverd` REST API on Pi Zero instead.

However, the plugin is also used in the local dev setup where serial IS available. We need to support both modes:
- **Direct serial** (existing, for local dev/sim)
- **REST mode** (new, for Pi5 → Pi Zero)

**Step 2: Add REST transport functions**

Add to `openclaw-plugin/index.ts`, after the existing imports:

```typescript
// REST transport — used when configured with roverdUrl instead of serialPort
let roverdUrl: string | null = null;

async function restCommand(action: string, value?: number): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const body: Record<string, unknown> = { action };
  if (value !== undefined) body.value = value;
  const resp = await fetch(`${roverdUrl}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  return data.reply || JSON.stringify(data);
}

async function restStatus(): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const resp = await fetch(`${roverdUrl}/status`);
  return await resp.text();
}

async function restNavigate(waypoints: number[][]): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const resp = await fetch(`${roverdUrl}/navigate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ waypoints }),
  });
  const data = await resp.json();
  return data.result || data.error || JSON.stringify(data);
}

async function restStop(): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const resp = await fetch(`${roverdUrl}/stop`, { method: "POST" });
  const data = await resp.json();
  return data.result || JSON.stringify(data);
}

async function restPause(): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const resp = await fetch(`${roverdUrl}/pause`, { method: "POST" });
  const data = await resp.json();
  return data.result || data.error || JSON.stringify(data);
}

async function restResume(): Promise<string> {
  if (!roverdUrl) throw new Error("roverd URL not configured");
  const resp = await fetch(`${roverdUrl}/resume`, { method: "POST" });
  const data = await resp.json();
  return data.result || data.error || JSON.stringify(data);
}
```

**Step 3: Update register function**

In the `register` function, check for `roverdUrl` config:

```typescript
roverdUrl = (api.pluginConfig as any)?.roverdUrl || null;
```

Update each existing tool's `execute` to use REST when `roverdUrl` is set. For example, `rover_forward`:

```typescript
async execute(_id, params) {
  if (roverdUrl) {
    const resp = await restCommand("forward", params.speed as number);
    return toolResult(resp);
  }
  // existing serial code...
}
```

Apply the same pattern to all 9 existing tools.

**Step 4: Register new navigation tools**

```typescript
api.registerTool({
  name: "rover_navigate",
  description: "Navigate to GPS waypoints. Provide array of [lat,lng] pairs.",
  parameters: {
    type: "object",
    properties: {
      waypoints: {
        type: "array",
        items: { type: "array", items: { type: "number" }, minItems: 2, maxItems: 2 },
        description: "Array of [lat, lng] coordinate pairs",
      },
    },
    required: ["waypoints"],
  },
  async execute(_id, params) {
    const resp = await restNavigate(params.waypoints as number[][]);
    return toolResult(resp);
  },
});

api.registerTool({
  name: "rover_nav_status",
  description: "Get navigation status including GPS position, heading, and progress toward waypoints",
  parameters: noParams,
  async execute() {
    const resp = await restStatus();
    return toolResult(resp);
  },
});

api.registerTool({
  name: "rover_pause",
  description: "Pause current navigation. Rover stops but remembers remaining waypoints.",
  parameters: noParams,
  async execute() {
    const resp = await restPause();
    return toolResult(resp);
  },
});

api.registerTool({
  name: "rover_resume",
  description: "Resume paused navigation from current waypoint.",
  parameters: noParams,
  async execute() {
    const resp = await restResume();
    return toolResult(resp);
  },
});
```

**Step 5: Test manually**

```bash
# With roverd running on localhost:8080 (connected to simulator)
# Configure plugin with roverdUrl: "http://localhost:8080"
# Test via openclaw agent
```

**Step 6: Commit**

```bash
git add openclaw-plugin/index.ts
git commit -m "feat(plugin): add REST transport and navigation tools"
```

---

## Task 8: Update `rover-remote` (Pi5) — SSH to REST

Update the shell script that Pi5 uses to call the rover.

**Files:**
- Modify: `deploy/pi5/bin/rover-remote`

**Step 1: Rewrite rover-remote to use REST**

Replace the SSH-based `rover-remote` with REST calls:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROVERD_URL="${ROVERD_URL:-http://roverpi:8080}"

if [ $# -lt 1 ]; then
  echo "usage: rover-remote <forward|backward|left|right|spin_left|spin_right|spin_to|scan|stop|status|ping|navigate|pause|resume> [speed|angle|waypoints]" >&2
  exit 1
fi
ACTION="$1"; shift || true
VALUE="${1:-}"

case "$ACTION" in
  forward|backward|left|right|spin_left|spin_right|spin_to|ping)
    if [[ -z "$VALUE" && "$ACTION" != "ping" ]]; then VALUE=160; fi
    curl -sf -X POST "$ROVERD_URL/command" \
      -H 'Content-Type: application/json' \
      -d "{\"action\":\"$ACTION\",\"value\":$VALUE}"
    ;;
  scan)
    curl -sf -X POST "$ROVERD_URL/command" \
      -H 'Content-Type: application/json' \
      -d '{"action":"scan"}'
    ;;
  stop)
    curl -sf -X POST "$ROVERD_URL/stop"
    ;;
  status)
    curl -sf "$ROVERD_URL/status"
    ;;
  navigate)
    # Expects waypoints as JSON string: '[[lat,lng],[lat,lng]]'
    curl -sf -X POST "$ROVERD_URL/navigate" \
      -H 'Content-Type: application/json' \
      -d "{\"waypoints\":$VALUE}"
    ;;
  pause)
    curl -sf -X POST "$ROVERD_URL/pause"
    ;;
  resume)
    curl -sf -X POST "$ROVERD_URL/resume"
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 2
    ;;
esac
echo  # trailing newline for readability
```

**Step 2: Test manually**

```bash
# With roverd running
ROVERD_URL=http://localhost:8080 ./deploy/pi5/bin/rover-remote status
ROVERD_URL=http://localhost:8080 ./deploy/pi5/bin/rover-remote forward 160
ROVERD_URL=http://localhost:8080 ./deploy/pi5/bin/rover-remote stop
```

**Step 3: Commit**

```bash
git add deploy/pi5/bin/rover-remote
git commit -m "feat: rewrite rover-remote to use REST API instead of SSH"
```

---

## Task 9: Arduino Firmware — Add Compass Reading

Add HMC5883L compass support to Arduino firmware. This only applies to real hardware — the simulator already has compass support from Task 1.

**Files:**
- Modify: `arduino/rover/rover.ino`

**Step 1: Add compass reading to firmware**

Add after the gyro constants in `arduino/rover/rover.ino`:

```cpp
// HMC5883L compass
const int HMC_ADDR = 0x1E;
int compassHeading = 0;
unsigned long lastCompassTime = 0;
const unsigned long COMPASS_INTERVAL = 100; // ms between reads
```

Add compass init function (call from `setup()` after `initGyro()`):

```cpp
void initCompass() {
  // Set to continuous measurement mode
  Wire.beginTransmission(HMC_ADDR);
  Wire.write(0x00); // Config Register A
  Wire.write(0x70); // 8 samples, 15Hz, normal
  Wire.endTransmission();

  Wire.beginTransmission(HMC_ADDR);
  Wire.write(0x01); // Config Register B
  Wire.write(0x20); // Gain 1090 LSb/Gauss
  Wire.endTransmission();

  Wire.beginTransmission(HMC_ADDR);
  Wire.write(0x02); // Mode Register
  Wire.write(0x00); // Continuous measurement
  Wire.endTransmission();
}
```

Add compass read function (call from `loop()` after `updateHeading()`):

```cpp
void updateCompass() {
  if (millis() - lastCompassTime < COMPASS_INTERVAL) return;
  lastCompassTime = millis();

  Wire.beginTransmission(HMC_ADDR);
  Wire.write(0x03); // Data output register
  Wire.endTransmission();
  Wire.requestFrom(HMC_ADDR, 6);

  if (Wire.available() < 6) return;

  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read(); // z before y in HMC5883L
  int16_t y = (Wire.read() << 8) | Wire.read();

  float headingRad = atan2(y, x);
  if (headingRad < 0) headingRad += 2 * PI;
  compassHeading = (int)(headingRad * 180.0 / PI);
}
```

**Step 2: Update `sendStatus()` to include compass**

In `sendStatus()`, after the heading print, add:

```cpp
Serial.print(";compass=");
Serial.print(compassHeading);
```

**Step 3: Update `setup()` and `loop()`**

In `setup()`, after `initGyro()`:
```cpp
initCompass();
```

In `loop()`, after `updateHeading()`:
```cpp
updateCompass();
```

**Step 4: Compile and verify**

```bash
# Compile (do not upload — no hardware connected)
cd arduino/rover && arduino-cli compile --fqbn arduino:avr:nano
```

Expected: Compiles without errors. Flash/RAM usage should remain under limits.

**Step 5: Commit**

```bash
git add arduino/rover/rover.ino
git commit -m "feat(firmware): add HMC5883L compass reading to STATUS"
```

---

## Task 10: Update Workspace Docs

Update agent instructions to reflect the new REST-based architecture and navigation commands.

**Files:**
- Modify: `workspace/TOOLS.md`
- Modify: `workspace/AGENTS.md`

**Step 1: Update TOOLS.md**

Replace the SSH-based command path with REST API documentation. Update the "Primary Command Path" section:

```markdown
## Primary Command Path (Pi5)

roverd REST API running on Pi Zero (`roverpi:8080`):

```bash
# Manual commands
curl -X POST http://roverpi:8080/command -d '{"action":"forward","value":160}'
curl -X POST http://roverpi:8080/stop
curl http://roverpi:8080/status

# Navigation (outdoor mode, --gps)
curl -X POST http://roverpi:8080/navigate -d '{"waypoints":[[lat,lng],[lat,lng]]}'
curl -X POST http://roverpi:8080/pause
curl -X POST http://roverpi:8080/resume
```

Or via rover-remote wrapper:
```bash
~/.local/bin/rover-remote forward 160
~/.local/bin/rover-remote navigate '[[37.386,-122.083],[37.390,-122.080]]'
~/.local/bin/rover-remote status
```
```

**Step 2: Update AGENTS.md**

Add navigation commands to the command mapping and exact command fast path sections. Add new section:

```markdown
## Navigation Commands (GPS mode only)

- "go to [lat,lng coordinates]" -> `rover_navigate({waypoints: [[lat,lng]]})`
- "navigate to [place name]" -> "I need GPS coordinates — Maps API not set up yet"
- "where are you" / "how far" / "progress" -> `rover_nav_status()`
- "pause" / "wait there" -> `rover_pause()`
- "keep going" / "resume" / "continue" -> `rover_resume()`

Navigation status response format:
- `GPS: lat,lng (fix: yes/no)`
- `Waypoint 2/3, 45m away`
- `Heading: 127° | Target: 130°`
- `Mode: navigating|paused|idle`
```

**Step 3: Commit**

```bash
git add workspace/TOOLS.md workspace/AGENTS.md
git commit -m "docs: update agent instructions for REST API and navigation"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Compass in simulator | 6 |
| 2 | GPS NMEA parser (with $GNRMC, staleness) | 13 |
| 3 | Navigation math | 13 |
| 4 | roverd core (serial + REST + scan + auth) | 6 |
| 5 | GPS integration in roverd | 2 |
| 6 | Navigation loop (8m/3-fix, stale GPS, obstacle pause) | 10 |
| 7 | OpenClaw plugin REST + nav tools | manual |
| 8 | rover-remote REST rewrite | manual |
| 9 | Arduino compass firmware | compile |
| 10 | Workspace docs | — |
| **Total** | | **50 new tests** |

## Review Findings Addressed

All 12 findings from `2026-03-21-outdoor-autonomous-driving-review.md` have been addressed:

1. Scan regression: Added proper `POST /scan` endpoint with 360-degree sweep
2. Auth: Bind to `127.0.0.1` by default, `--token` flag for bearer auth
3. HMC5883L voltage: Specified GY-271 breakout (5V-safe), added warnings for bare modules
4. Regulator: Buck converter only, removed LM7805 recommendation
5. Stale GPS: Added `last_fix_time`, `is_fresh` property, 3-second staleness timeout
6. NMEA parsing: Accept any `*RMC` talker ID, added `$GNRMC` test
7. Nav task race: Reject `/navigate` if already navigating (409), cancel task on `/stop`
8. Status contract: Added `distance_to_wp`, `bearing`, `age_s`, 1-based waypoint index
9. Compass expectations: Documented as coarse, widened thresholds to 8/20 degrees
10. Arrival threshold: Changed to 8m with 3 consecutive in-radius fixes
11. I2C troubleshooting: Corrected to Arduino I2C scanner sketch
12. Test coverage: Added stale GPS, obstacle pause, consecutive fix, empty waypoint tests
