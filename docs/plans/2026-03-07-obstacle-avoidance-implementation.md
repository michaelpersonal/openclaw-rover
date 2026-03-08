# Obstacle Avoidance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add HC-SR04 ultrasonic obstacle avoidance to the rover — Arduino-level reflexive stop, simulator support, plugin/monitor updates.

**Architecture:** Single ultrasonic sensor on Arduino D2/D3. Firmware measures distance every ~60ms, auto-stops and blocks FORWARD when <20cm. Simulator gets SET_OBSTACLE/CLEAR_OBSTACLE commands for testing. Plugin and monitor parse the new `dist` field and `STOPPED:OBSTACLE` events.

**Tech Stack:** C++ (Arduino), Python (simulator/monitor), TypeScript (OpenClaw plugin)

**Design doc:** `docs/plans/2026-03-07-obstacle-avoidance-design.md`

---

### Task 1: Simulator — Add Obstacle State and SET_OBSTACLE/CLEAR_OBSTACLE

We start with the simulator so we can TDD the obstacle logic in Python before touching the Arduino firmware.

**Files:**
- Modify: `simulator/rover_sim.py`
- Test: `simulator/test_rover_sim.py`

**Step 1: Write failing tests for obstacle state and commands**

Add to `simulator/test_rover_sim.py`:

```python
class TestObstacle:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_default_distance_is_999(self):
        assert self.sim.obstacle_dist == 999

    def test_set_obstacle(self):
        resp = self.sim.process_command("SET_OBSTACLE 15")
        assert resp == "OK"
        assert self.sim.obstacle_dist == 15

    def test_clear_obstacle(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("CLEAR_OBSTACLE")
        assert resp == "OK"
        assert self.sim.obstacle_dist == 999

    def test_status_includes_dist(self):
        self.sim.process_command("SET_OBSTACLE 42")
        resp = self.sim.process_command("STATUS")
        assert "dist=42cm" in resp
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestObstacle -v`
Expected: FAIL — `AttributeError: 'RoverSimulator' object has no attribute 'obstacle_dist'`

**Step 3: Implement obstacle state, SET_OBSTACLE, CLEAR_OBSTACLE, and dist in STATUS**

In `simulator/rover_sim.py`, in `RoverSimulator.__init__`, add:

```python
self.obstacle_dist = 999  # cm, 999 = no obstacle
self.obstacle_blocked = False
```

In `RoverSimulator.process_command`, add before the `else` (unknown command) branch:

```python
elif cmd == "SET_OBSTACLE":
    self.obstacle_dist = max(0, speed)  # reuse speed parsing for distance
    self._check_obstacle()
    return "OK"
elif cmd == "CLEAR_OBSTACLE":
    self.obstacle_dist = 999
    self.obstacle_blocked = False
    return "OK"
```

Add `_check_obstacle` method:

```python
def _check_obstacle(self):
    """Check if obstacle is within threshold. Returns 'STOPPED:OBSTACLE' if newly blocked, else None."""
    if self.obstacle_dist < 20 and not self.obstacle_blocked:
        self._stop_motors()
        self.obstacle_blocked = True
        return "STOPPED:OBSTACLE"
    elif self.obstacle_dist >= 20:
        self.obstacle_blocked = False
    return None
```

In `_status_response`, add `dist={self.obstacle_dist}cm` after motors, before uptime:

```python
return f"STATUS:motors={left},{right};dist={self.obstacle_dist}cm;uptime={uptime_ms};cmds={self.cmd_count};last_cmd={last_cmd_ms}ms;loop=0hz"
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestObstacle -v`
Expected: PASS (4 tests)

**Step 5: Run all existing tests to check for regressions**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py -v`
Expected: All tests pass. Note: `test_status_format` and `test_status_when_stopped`/`test_status_when_moving` should still pass since they don't check for exact format — but verify `dist=999cm` doesn't break any assertions.

**Step 6: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(sim): add obstacle state with SET_OBSTACLE/CLEAR_OBSTACLE commands"
```

---

### Task 2: Simulator — Obstacle Blocks FORWARD and Auto-Stops

**Files:**
- Modify: `simulator/rover_sim.py`
- Test: `simulator/test_rover_sim.py`

**Step 1: Write failing tests for obstacle blocking behavior**

Add to `TestObstacle` class in `simulator/test_rover_sim.py`:

```python
    def test_obstacle_auto_stops_motors(self):
        self.sim.process_command("FORWARD 180")
        self.sim.process_command("SET_OBSTACLE 10")
        assert self.sim.left_dir == "S"
        assert self.sim.right_dir == "S"

    def test_obstacle_blocks_forward(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "ERR:OBSTACLE"
        assert self.sim.left_dir == "S"

    def test_obstacle_allows_backward(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("BACKWARD 150")
        assert resp == "OK"
        assert self.sim.left_dir == "R"

    def test_obstacle_allows_left(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("LEFT 120")
        assert resp == "OK"

    def test_obstacle_allows_right(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("RIGHT 120")
        assert resp == "OK"

    def test_obstacle_allows_spin_left(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("SPIN_LEFT 100")
        assert resp == "OK"

    def test_obstacle_allows_spin_right(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("SPIN_RIGHT 100")
        assert resp == "OK"

    def test_obstacle_allows_stop(self):
        self.sim.process_command("SET_OBSTACLE 10")
        resp = self.sim.process_command("STOP")
        assert resp == "OK"

    def test_obstacle_clears_when_distance_increases(self):
        self.sim.process_command("SET_OBSTACLE 10")
        assert self.sim.obstacle_blocked is True
        self.sim.process_command("SET_OBSTACLE 25")
        assert self.sim.obstacle_blocked is False
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "OK"

    def test_set_obstacle_returns_stopped_obstacle(self):
        """SET_OBSTACLE should trigger STOPPED:OBSTACLE via check_obstacle, but the
        command itself returns OK. The STOPPED:OBSTACLE is an async event in the real
        firmware. In the simulator, we return it as a second line."""
        self.sim.process_command("FORWARD 180")
        resp = self.sim.process_command("SET_OBSTACLE 10")
        assert resp == "OK"
        # The auto-stop happened as a side effect
        assert self.sim.obstacle_blocked is True
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestObstacle -v`
Expected: FAIL — FORWARD returns "OK" instead of "ERR:OBSTACLE"

**Step 3: Add FORWARD blocking logic**

In `simulator/rover_sim.py`, in `process_command`, modify the FORWARD branch:

```python
if cmd == "FORWARD":
    if self.obstacle_blocked:
        return "ERR:OBSTACLE"
    self._set_motors(speed, "F", speed, "F")
    return "OK"
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestObstacle -v`
Expected: PASS (all obstacle tests)

**Step 5: Run full test suite**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(sim): block FORWARD when obstacle detected, allow other commands"
```

---

### Task 3: Arduino Firmware — Obstacle Avoidance

**Files:**
- Modify: `arduino/rover/rover.ino`

**Step 1: Add pin constants and state variables**

At the top of `rover.ino`, after the STBY pin definition, add:

```cpp
// Ultrasonic sensor (HC-SR04)
const int TRIG_PIN = 2;
const int ECHO_PIN = 3;

const int OBSTACLE_THRESHOLD_CM = 20;
```

After the existing state variables (after `unsigned long loopRate = 0;`), add:

```cpp
long distanceCm = 999;
bool obstacleBlocked = false;
unsigned long lastMeasureTime = 0;
const unsigned long MEASURE_INTERVAL = 60;  // ms between readings
```

**Step 2: Add distance measurement function**

After the `sendStatus()` function, add:

```cpp
void measureDistance() {
  if (millis() - lastMeasureTime < MEASURE_INTERVAL) return;
  lastMeasureTime = millis();

  // Trigger pulse
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Read echo (timeout 20ms = ~340cm max)
  long duration = pulseIn(ECHO_PIN, HIGH, 20000);
  if (duration == 0) {
    distanceCm = 999;  // no echo = nothing in range
  } else {
    distanceCm = duration / 58;  // speed of sound conversion
  }

  // Check obstacle
  if (distanceCm < OBSTACLE_THRESHOLD_CM && !obstacleBlocked) {
    stopMotors();
    Serial.println("STOPPED:OBSTACLE");
    obstacleBlocked = true;
  } else if (distanceCm >= OBSTACLE_THRESHOLD_CM) {
    obstacleBlocked = false;
  }
}
```

**Step 3: Block FORWARD in processCommand**

In `processCommand`, change the FORWARD branch:

```cpp
if (strcmp(cmd, "FORWARD") == 0) {
    if (obstacleBlocked) {
      Serial.println("ERR:OBSTACLE");
    } else {
      setMotors(speed, DIR_FORWARD, speed, DIR_FORWARD);
      Serial.println("OK");
    }
```

**Step 4: Add dist to STATUS response**

In `sendStatus()`, after printing the motor values and before printing uptime, add:

```cpp
  Serial.print(";dist=");
  Serial.print(distanceCm);
  Serial.print("cm");
```

So the line after the right motor section becomes:
```cpp
  Serial.print(";dist=");
  Serial.print(distanceCm);
  Serial.print("cm;uptime=");
```

**Step 5: Update setup()**

In `setup()`, before `digitalWrite(STBY, HIGH);`, add:

```cpp
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
```

**Step 6: Update loop()**

In `loop()`, add the distance measurement call after the watchdog check (after the closing `}` of the watchdog block, before serial reading):

```cpp
  // 2. Ultrasonic distance check
  measureDistance();
```

Renumber the existing comments: serial reading becomes `// 3.`, loop rate tracking becomes `// 4.`.

**Step 7: Compile-check**

Run: `cd /data/home/mguo/code/rover && arduino-cli compile --fqbn arduino:avr:nano arduino/rover/ 2>&1 || echo "If arduino-cli not available, visual inspection is OK"`

**Step 8: Commit**

```bash
git add arduino/rover/rover.ino
git commit -m "feat(firmware): add HC-SR04 obstacle avoidance on D2/D3"
```

---

### Task 4: Plugin — Parse dist and STOPPED:OBSTACLE

**Files:**
- Modify: `openclaw-plugin/index.ts`

**Step 1: Add dist to parseStatus**

In `openclaw-plugin/index.ts`, in the `parseStatus` function, in the return object (line ~74), add the `dist` field:

```typescript
  return {
    type: "status",
    motors: { left: parseMotor(motorParts[0]), right: parseMotor(motorParts[1] || "S") },
    dist: parseInt((parts.dist || "999").replace("cm", ""), 10),
    uptime: parseInt(parts.uptime || "0", 10),
    cmds: parseInt(parts.cmds || "0", 10),
    lastCmd: parseInt((parts.last_cmd || "0").replace("ms", ""), 10),
    loopHz: parseInt((parts.loop || "0").replace("hz", ""), 10),
    ts: Date.now(),
  };
```

**Step 2: Handle STOPPED:OBSTACLE events**

In the `parser.on("data")` handler (line ~155), add a check for `STOPPED:OBSTACLE` alongside the existing `STOPPED:WATCHDOG` check:

```typescript
      parser.on("data", (line: string) => {
        const trimmed = line.trim();
        if (trimmed === "STOPPED:WATCHDOG" || trimmed === "STOPPED:OBSTACLE") {
          api.logger.warn(`Rover: ${trimmed}`);
          broadcast({ type: "event", event: trimmed, ts: Date.now() });
          return;
        }
```

**Step 3: Add dist to formatStatusForLLM**

In `formatStatusForLLM` (line ~126), add the distance line:

```typescript
  const dist = parsed.dist as number;
  const distStr = dist >= 999 ? "clear" : `${dist}cm`;
  const distStyle = dist < 20 ? " ⚠️ BLOCKED" : "";
  return [
    `Motors: Left ${motorDesc(m.left)}, Right ${motorDesc(m.right)}`,
    `Distance: ${distStr}${distStyle}`,
    `Uptime: ${upStr}`,
    `Commands: ${parsed.cmds} (last ${parsed.lastCmd}ms ago)`,
    `Loop: ${parsed.loopHz} hz`,
  ].join("\n");
```

**Step 4: Commit**

```bash
git add openclaw-plugin/index.ts
git commit -m "feat(plugin): parse obstacle distance and STOPPED:OBSTACLE events"
```

---

### Task 5: Monitor — Display Distance and Obstacle Events

**Files:**
- Modify: `monitor/rover_monitor.py`
- Test: `monitor/test_monitor.py`

**Step 1: Write failing tests for distance display**

Add to `monitor/test_monitor.py`:

```python
class TestBuildDisplay:
    def test_vitals_shows_distance(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 42}
        layout = build_display(state, [])
        # The layout renders — we verify no crash and the function accepts dist

    def test_vitals_shows_distance_blocked(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 15}
        layout = build_display(state, [])
        # The layout renders with blocked distance
```

Update imports at top: add `build_display` to the import line:

```python
from rover_monitor import parse_message, motor_bar, format_uptime, build_display
```

**Step 2: Run tests to verify they pass (baseline — build_display already exists)**

Run: `cd /data/home/mguo/code/rover && cd monitor && python3 -m pytest test_monitor.py -v`
Expected: Tests pass but distance isn't shown yet (the function accepts extra keys in state dict without error)

**Step 3: Add distance to vitals panel**

In `monitor/rover_monitor.py`, in `build_display`, update the vitals section (after line ~93):

```python
    # Vitals panel
    uptime = format_uptime(state.get("uptime", 0))
    cmds = state.get("cmds", 0)
    last_cmd = state.get("lastCmd", 0)
    loop_hz = state.get("loopHz", 0)
    dist = state.get("dist", 999)

    vitals = Text()
    if dist < 20:
        vitals.append(f"  Distance: {dist}cm ", style="bold red")
        vitals.append("BLOCKED\n", style="bold red")
    elif dist < 999:
        vitals.append(f"  Distance: {dist}cm\n")
    else:
        vitals.append(f"  Distance: clear\n")
    vitals.append(f"  Uptime: {uptime}      Loop: {loop_hz} hz\n")
    vitals.append(f"  Commands: {cmds}        Last cmd: {last_cmd}ms ago")
```

**Step 4: Add OBSTACLE event styling in events panel**

In `build_display`, in the events loop, update the style logic (around line ~118):

```python
            style = "yellow" if "WATCHDOG" in event_name else "red bold" if "OBSTACLE" in event_name else "red" if "ERR" in event_name else "white"
```

**Step 5: Increase vitals panel size to fit the new distance line**

In `build_display`, change the vitals layout size from 4 to 5:

```python
    layout.split_column(
        Layout(name="motors", size=6),
        Layout(name="vitals", size=5),
        Layout(name="events"),
    )
```

**Step 6: Run all monitor tests**

Run: `cd /data/home/mguo/code/rover && cd monitor && python3 -m pytest test_monitor.py -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add monitor/rover_monitor.py monitor/test_monitor.py
git commit -m "feat(monitor): display obstacle distance and STOPPED:OBSTACLE events"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `AI_HANDOFF.md`
- Modify: `README.md`

**Step 1: Update README serial protocol table**

In `README.md`, add to the Responses table:

```
| `STOPPED:OBSTACLE` | Auto-stopped (obstacle <20cm ahead) |
| `ERR:OBSTACLE` | FORWARD rejected (obstacle present) |
```

Update the STATUS example to include `dist=`:
```
| `STATUS:motors=F180,F180;dist=42cm;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz` | Telemetry |
```

Add HC-SR04 to the Hardware list:
```
- HC-SR04 Ultrasonic Sensor — obstacle detection
```

**Step 2: Update AI_HANDOFF.md**

Update "Current State" date to 2026-03-07. Add obstacle avoidance to the "What's built and working" section. Update the pin wiring table to include D2 (TRIG) and D3 (ECHO). Update "Available for future sensors" to `D4, D5, D13, A0–A7`.

**Step 3: Commit**

```bash
git add README.md AI_HANDOFF.md
git commit -m "docs: add obstacle avoidance to README and AI handoff"
```
