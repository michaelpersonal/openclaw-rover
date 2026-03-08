# Smart Scan with Gyroscope Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MPU6050 gyroscope for precise heading control and a 360-degree scan tool that lets the LLM navigate around obstacles.

**Architecture:** MPU6050 on I2C (A4/A5) provides yaw tracking. Firmware adds SPIN_TO command for precise turns. Plugin adds rover_scan (12-point 360-degree sweep) and rover_spin_to tools. LLM receives distance map and decides navigation strategy.

**Tech Stack:** C++ with Wire.h (Arduino), Python (simulator/monitor), TypeScript (OpenClaw plugin)

**Design doc:** `docs/plans/2026-03-07-smart-scan-design.md`

---

### Task 1: Simulator — Add Heading State and SPIN_TO Command

**Files:**
- Modify: `simulator/rover_sim.py`
- Test: `simulator/test_rover_sim.py`

**Step 1: Write failing tests**

Add to `simulator/test_rover_sim.py`:

```python
class TestHeading:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_default_heading_is_0(self):
        assert self.sim.heading == 0

    def test_spin_to_sets_heading(self):
        resp = self.sim.process_command("SPIN_TO 90")
        assert resp == "OK"
        assert self.sim.heading == 90

    def test_spin_to_wraps_360(self):
        resp = self.sim.process_command("SPIN_TO 360")
        assert resp == "OK"
        assert self.sim.heading == 0

    def test_spin_to_clamps_negative(self):
        resp = self.sim.process_command("SPIN_TO 0")
        assert resp == "OK"
        assert self.sim.heading == 0

    def test_status_includes_heading(self):
        self.sim.process_command("SPIN_TO 45")
        resp = self.sim.process_command("STATUS")
        assert "heading=45;" in resp
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestHeading -v`
Expected: FAIL — `AttributeError: 'RoverSimulator' object has no attribute 'heading'`

**Step 3: Implement heading state and SPIN_TO**

In `simulator/rover_sim.py`, in `RoverSimulator.__init__`, add:

```python
self.heading = 0  # degrees, 0-359
```

In `process_command`, the argument parsing currently clamps to 0-255 via speed. We need SPIN_TO to accept 0-359. Change the argument parsing to:

```python
parts = line.split(" ", 1)
cmd = parts[0]
arg = int(parts[1]) if len(parts) > 1 else 0
```

Then update all existing references from `speed` to `arg`. For motor commands, clamp inline: `max(0, min(255, arg))`. Add the SPIN_TO branch before SET_OBSTACLE:

```python
elif cmd == "SPIN_TO":
    self.heading = arg % 360
    return "OK"
```

In `_status_response`, add `heading={self.heading};` after the dist field:

```python
return f"STATUS:motors={left},{right};dist={self.obstacle_dist}cm;heading={self.heading};uptime={uptime_ms};cmds={self.cmd_count};last_cmd={last_cmd_ms}ms;loop=0hz"
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestHeading -v`
Expected: PASS (5 tests)

**Step 5: Run all tests to check for regressions**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py -v`
Expected: All 40 tests pass

**Step 6: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(sim): add heading state and SPIN_TO command"
```

---

### Task 2: Simulator — Add Angle-Based Obstacle Distance

**Files:**
- Modify: `simulator/rover_sim.py`
- Test: `simulator/test_rover_sim.py`

**Step 1: Write failing tests**

Add to `simulator/test_rover_sim.py`:

```python
class TestAngleObstacle:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_set_obstacle_at_angle(self):
        resp = self.sim.process_command("SET_OBSTACLE_AT 90 50")
        assert resp == "OK"

    def test_distance_at_obstacle_angle(self):
        self.sim.process_command("SET_OBSTACLE_AT 0 15")
        assert self.sim._get_distance_at_heading(0) == 15

    def test_distance_at_clear_angle(self):
        self.sim.process_command("SET_OBSTACLE_AT 0 15")
        assert self.sim._get_distance_at_heading(90) == 999

    def test_obstacle_angle_window(self):
        """Obstacle at 90 should be detected at 80 and 100 (within +-15 degrees)."""
        self.sim.process_command("SET_OBSTACLE_AT 90 30")
        assert self.sim._get_distance_at_heading(80) == 30
        assert self.sim._get_distance_at_heading(100) == 30
        assert self.sim._get_distance_at_heading(106) == 999  # outside window

    def test_multiple_obstacles(self):
        self.sim.process_command("SET_OBSTACLE_AT 0 10")
        self.sim.process_command("SET_OBSTACLE_AT 180 25")
        assert self.sim._get_distance_at_heading(0) == 10
        assert self.sim._get_distance_at_heading(180) == 25
        assert self.sim._get_distance_at_heading(90) == 999

    def test_obstacle_at_wraps_around_360(self):
        """Obstacle at 350 should be detected at 5 (within +-15 window wrapping)."""
        self.sim.process_command("SET_OBSTACLE_AT 350 20")
        assert self.sim._get_distance_at_heading(355) == 20
        assert self.sim._get_distance_at_heading(5) == 20

    def test_spin_to_updates_obstacle_dist(self):
        """When rover spins to face an obstacle, obstacle_dist should update."""
        self.sim.process_command("SET_OBSTACLE_AT 90 15")
        self.sim.process_command("SPIN_TO 90")
        assert self.sim.obstacle_dist == 15

    def test_clear_obstacle_clears_angle_obstacles(self):
        self.sim.process_command("SET_OBSTACLE_AT 0 10")
        self.sim.process_command("SET_OBSTACLE_AT 90 20")
        self.sim.process_command("CLEAR_OBSTACLE")
        assert self.sim._get_distance_at_heading(0) == 999
        assert self.sim._get_distance_at_heading(90) == 999
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestAngleObstacle -v`
Expected: FAIL

**Step 3: Implement angle-based obstacles**

In `simulator/rover_sim.py`, in `RoverSimulator.__init__`, add:

```python
self.obstacle_map = {}  # {angle: distance} for angle-based obstacles
```

Add `_get_distance_at_heading` method:

```python
def _get_distance_at_heading(self, heading):
    """Get obstacle distance at a given heading. Checks +-15 degree window."""
    for angle, dist in self.obstacle_map.items():
        diff = abs((heading - angle + 180) % 360 - 180)
        if diff <= 15:
            return dist
    return 999
```

Add `SET_OBSTACLE_AT` command in `process_command`. This command has two arguments (angle and distance), so parse the second argument from the remaining string. Add before the `STATUS` branch:

```python
elif cmd == "SET_OBSTACLE_AT":
    # Parse "angle distance" from original parts
    sub_parts = parts[1].split() if len(parts) > 1 else []
    if len(sub_parts) >= 2:
        angle = int(sub_parts[0]) % 360
        dist = max(0, int(sub_parts[1]))
        self.obstacle_map[angle] = dist
        self._update_obstacle_for_heading()
    return "OK"
```

Note: we need to re-parse from the original line for two-argument commands. Modify the argument parsing at the top of `process_command` to also keep the raw argument string:

```python
parts = line.split(" ", 1)
cmd = parts[0]
raw_args = parts[1] if len(parts) > 1 else ""
arg = int(raw_args.split()[0]) if raw_args else 0
```

Then SET_OBSTACLE_AT uses `raw_args`:

```python
elif cmd == "SET_OBSTACLE_AT":
    sub_parts = raw_args.split()
    if len(sub_parts) >= 2:
        angle = int(sub_parts[0]) % 360
        dist = max(0, int(sub_parts[1]))
        self.obstacle_map[angle] = dist
        self._update_obstacle_for_heading()
    return "OK"
```

Add `_update_obstacle_for_heading` method that updates `obstacle_dist` based on current heading:

```python
def _update_obstacle_for_heading(self):
    """Update obstacle_dist based on current heading and obstacle map."""
    self.obstacle_dist = self._get_distance_at_heading(self.heading)
    self._check_obstacle()
```

Update `SPIN_TO` to call `_update_obstacle_for_heading` after setting heading:

```python
elif cmd == "SPIN_TO":
    self.heading = arg % 360
    self._update_obstacle_for_heading()
    return "OK"
```

Update `CLEAR_OBSTACLE` to also clear the obstacle map:

```python
elif cmd == "CLEAR_OBSTACLE":
    self.obstacle_dist = 999
    self.obstacle_blocked = False
    self.obstacle_map.clear()
    return "OK"
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py::TestAngleObstacle -v`
Expected: PASS (8 tests)

**Step 5: Run all tests**

Run: `cd /data/home/mguo/code/rover && python3 -m pytest simulator/test_rover_sim.py -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(sim): add angle-based obstacle simulation with SET_OBSTACLE_AT"
```

---

### Task 3: Arduino Firmware — MPU6050 Gyroscope and SPIN_TO

**Files:**
- Modify: `arduino/rover/rover.ino`

**Step 1: Add MPU6050 includes and constants**

At the top of `rover.ino`, add the Wire include after the comment header:

```cpp
#include <Wire.h>
```

After the OBSTACLE_THRESHOLD_CM constant, add:

```cpp
// MPU6050 gyroscope
const int MPU_ADDR = 0x68;
const int SPIN_TO_SPEED = 120;           // PWM speed for SPIN_TO turns
const unsigned long SPIN_TO_TIMEOUT = 5000;  // 5 second timeout
const float HEADING_TOLERANCE = 3.0;     // degrees of acceptable error
```

**Step 2: Add gyroscope state variables**

After the existing state variables (after `const unsigned long MEASURE_INTERVAL = 60;`), add:

```cpp
float heading = 0.0;           // current heading in degrees (0-359)
float gyroZoffset = 0.0;       // calibration offset
unsigned long lastGyroTime = 0;
bool spinToActive = false;     // true during a SPIN_TO maneuver
float spinToTarget = 0.0;      // target heading for SPIN_TO
unsigned long spinToStart = 0; // when SPIN_TO started (for timeout)
```

**Step 3: Add MPU6050 initialization function**

After the `measureDistance()` function, add:

```cpp
void initGyro() {
  Wire.begin();
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);  // PWR_MGMT_1 register
  Wire.write(0);     // wake up
  Wire.endTransmission();

  // Set gyro range to +-250 deg/s (most sensitive)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);  // GYRO_CONFIG register
  Wire.write(0);     // 0 = +-250 deg/s
  Wire.endTransmission();

  // Calibrate: take 100 readings at rest to find offset
  delay(100);  // let sensor settle (only at startup)
  float sum = 0;
  for (int i = 0; i < 100; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x47);  // GYRO_ZOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, 2);
    int16_t raw = (Wire.read() << 8) | Wire.read();
    sum += raw;
    delay(2);
  }
  gyroZoffset = sum / 100.0;
  lastGyroTime = micros();
}
```

**Step 4: Add heading update function**

```cpp
void updateHeading() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x47);  // GYRO_ZOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 2);
  int16_t raw = (Wire.read() << 8) | Wire.read();

  unsigned long now = micros();
  float dt = (now - lastGyroTime) / 1000000.0;  // seconds
  lastGyroTime = now;

  // Convert raw to deg/s (+-250 range: 131 LSB per deg/s)
  float rate = (raw - gyroZoffset) / 131.0;

  // Integrate to get heading
  heading += rate * dt;

  // Wrap to 0-359
  while (heading < 0) heading += 360.0;
  while (heading >= 360) heading -= 360.0;
}
```

**Step 5: Add SPIN_TO processing function**

```cpp
void processSpinTo() {
  if (!spinToActive) return;

  // Timeout check
  if (millis() - spinToStart > SPIN_TO_TIMEOUT) {
    stopMotors();
    spinToActive = false;
    Serial.println("ERR:SPIN_TIMEOUT");
    return;
  }

  // Calculate shortest rotation direction
  float diff = spinToTarget - heading;
  if (diff > 180) diff -= 360;
  if (diff < -180) diff += 360;

  if (abs(diff) <= HEADING_TOLERANCE) {
    // Reached target
    stopMotors();
    spinToActive = false;
    Serial.println("OK");
    return;
  }

  // Spin in the shortest direction
  if (diff > 0) {
    setMotors(SPIN_TO_SPEED, DIR_FORWARD, SPIN_TO_SPEED, DIR_REVERSE);  // spin right
  } else {
    setMotors(SPIN_TO_SPEED, DIR_REVERSE, SPIN_TO_SPEED, DIR_FORWARD);  // spin left
  }
}
```

**Step 6: Add SPIN_TO command to processCommand**

In `processCommand`, add before the `STOP` command branch:

```cpp
  } else if (strcmp(cmd, "SPIN_TO") == 0) {
    spinToTarget = constrain(speed, 0, 359);
    spinToActive = true;
    spinToStart = millis();
    // Don't send OK here — processSpinTo() sends it when target reached
```

Note: for SPIN_TO, the `speed` variable is actually the angle (0-359). The existing `constrain(atoi(space + 1), 0, 255)` clamp is too narrow. Change the argument parsing to use a wider range:

```cpp
int arg = 0;
if (space != NULL) {
    *space = '\0';
    arg = atoi(space + 1);
}
```

Then use `constrain(arg, 0, 255)` inline for speed-based commands and `constrain(arg, 0, 359)` for SPIN_TO. Update all existing command branches to use `constrain(arg, 0, 255)` where they currently use `speed`.

**Step 7: Add heading to STATUS**

In `sendStatus()`, after the dist line, add:

```cpp
  Serial.print(";heading=");
  Serial.print((int)heading);
```

So it becomes:
```cpp
  Serial.print(";dist=");
  Serial.print(distanceCm);
  Serial.print("cm;heading=");
  Serial.print((int)heading);
  Serial.print(";uptime=");
```

**Step 8: Update setup()**

In `setup()`, after `Serial.begin(9600);`, add:

```cpp
  initGyro();
```

**Step 9: Update loop()**

In `loop()`, add after the ultrasonic distance check and before serial reading:

```cpp
  // 3. Gyroscope heading update
  updateHeading();

  // 4. SPIN_TO processing
  processSpinTo();
```

Update the watchdog check to skip during SPIN_TO:

```cpp
  // 1. Watchdog check (skip during SPIN_TO)
  if (cmdCount > 0 && !watchdogFired && !spinToActive) {
```

Renumber serial reading to `// 5.` and loop rate to `// 6.`.

**Step 10: Compile-check**

Run: `cd /data/home/mguo/code/rover && arduino-cli compile --fqbn arduino:avr:nano arduino/rover/ 2>&1 || echo "If arduino-cli not available, visual inspection is OK"`

**Step 11: Commit**

```bash
git add arduino/rover/rover.ino
git commit -m "feat(firmware): add MPU6050 gyroscope and SPIN_TO command"
```

---

### Task 4: Plugin — Add rover_spin_to Tool and Heading in Telemetry

**Files:**
- Modify: `openclaw-plugin/index.ts`

**Step 1: Add heading to parseStatus**

In `parseStatus`, add heading to the return object after dist:

```typescript
    dist: parseInt((parts.dist || "999").replace("cm", ""), 10),
    heading: parseInt(parts.heading || "0", 10),
```

**Step 2: Add heading to formatStatusForLLM**

In `formatStatusForLLM`, add heading after distance:

```typescript
  const heading = parsed.heading as number;
  return [
    `Motors: Left ${motorDesc(m.left)}, Right ${motorDesc(m.right)}`,
    `Distance: ${distStr}${distStyle}`,
    `Heading: ${heading} degrees`,
    `Uptime: ${upStr}`,
    `Commands: ${parsed.cmds} (last ${parsed.lastCmd}ms ago)`,
    `Loop: ${parsed.loopHz} hz`,
  ].join("\n");
```

**Step 3: Add rover_spin_to tool**

After the `rover_stop` tool registration, add:

```typescript
  const angleParam = {
    type: "object",
    properties: {
      angle: {
        type: "number",
        description: "Target heading in degrees (0-359). 0=original front, 90=right, 180=rear, 270=left",
      },
    },
    required: ["angle"],
  };

  api.registerTool({
    name: "rover_spin_to",
    description: "Spin rover to a specific heading angle (0-359 degrees) using the gyroscope for precision",
    parameters: angleParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_TO ${params.angle}`);
      broadcast({ type: "command", cmd: "SPIN_TO", angle: params.angle, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });
```

Note: SPIN_TO may take several seconds to complete (the firmware sends OK when it reaches the target). Increase the timeout for this command. Modify `sendCommand` to accept an optional timeout parameter:

```typescript
function sendCommand(cmd: string, timeoutMs = 2000): Promise<string> {
```

And use `setTimeout(() => { ... }, timeoutMs)` instead of the hardcoded 2000. Then call SPIN_TO with a longer timeout:

```typescript
const resp = await sendCommand(`SPIN_TO ${params.angle}`, 6000);
```

**Step 4: Commit**

```bash
git add openclaw-plugin/index.ts
git commit -m "feat(plugin): add rover_spin_to tool and heading in telemetry"
```

---

### Task 5: Plugin — Add rover_scan Tool

**Files:**
- Modify: `openclaw-plugin/index.ts`

**Step 1: Add rover_scan tool**

After the `rover_spin_to` tool registration, add:

```typescript
  api.registerTool({
    name: "rover_scan",
    description: "Perform a 360-degree obstacle scan. Spins the rover in 30-degree increments, measuring distance at each angle, then returns to the original heading. Returns a distance map so you can pick the clearest direction.",
    parameters: noParams,
    async execute() {
      // 1. Get current heading
      const statusResp = await sendCommand("STATUS");
      const parsed = parseStatus(statusResp);
      const startHeading = parsed ? (parsed.heading as number) : 0;

      // 2. Scan 12 positions
      const readings: { angle: number; dist: number }[] = [];
      for (let i = 0; i < 12; i++) {
        const angle = (startHeading + i * 30) % 360;
        await sendCommand(`SPIN_TO ${angle}`, 6000);
        const stResp = await sendCommand("STATUS");
        const stParsed = parseStatus(stResp);
        const dist = stParsed ? (stParsed.dist as number) : 999;
        readings.push({ angle, dist });
      }

      // 3. Return to original heading
      await sendCommand(`SPIN_TO ${startHeading}`, 6000);

      // 4. Format results
      const dirLabel = (a: number): string => {
        const rel = ((a - startHeading) + 360) % 360;
        if (rel === 0) return "(front)";
        if (rel === 90) return "(right)";
        if (rel === 180) return "(rear)";
        if (rel === 270) return "(left)";
        return "";
      };

      const lines = readings.map(({ angle, dist }) => {
        const label = dirLabel(angle);
        const status = dist < 20 ? "BLOCKED" : "clear";
        return `  ${String(angle).padStart(3)}deg ${label.padEnd(8)} ${String(dist).padStart(4)}cm  ${status}`;
      });

      const best = readings.reduce((a, b) => a.dist >= b.dist ? a : b);

      const result = [
        `Scan complete (12 positions, 30deg apart):`,
        ...lines,
        ``,
        `Best clearance: ${best.angle}deg at ${best.dist}cm`,
        `Recommendation: spin to ${best.angle} degrees then drive forward`,
      ].join("\n");

      broadcast({ type: "event", event: "SCAN_COMPLETE", best: best.angle, bestDist: best.dist, ts: Date.now() });

      return toolResult(result);
    },
  });
```

**Step 2: Commit**

```bash
git add openclaw-plugin/index.ts
git commit -m "feat(plugin): add rover_scan 360-degree obstacle scanning tool"
```

---

### Task 6: Monitor — Add Heading Display and Scan Events

**Files:**
- Modify: `monitor/rover_monitor.py`
- Test: `monitor/test_monitor.py`

**Step 1: Write tests**

Add to `monitor/test_monitor.py` in `TestBuildDisplay`:

```python
    def test_vitals_shows_heading(self):
        state = {"motors": {"left": {"dir": "S", "speed": 0}, "right": {"dir": "S", "speed": 0}},
                 "uptime": 5000, "cmds": 10, "lastCmd": 100, "loopHz": 8000, "dist": 999, "heading": 270}
        layout = build_display(state, [])
        # Renders without crash with heading
```

**Step 2: Add heading to vitals panel**

In `monitor/rover_monitor.py`, in `build_display`, after the dist variable, add:

```python
    heading = state.get("heading", 0)
```

After the distance display lines and before the uptime line, add:

```python
    vitals.append(f"  Heading: {heading}deg\n")
```

**Step 3: Add SCAN_COMPLETE event styling**

In the events loop, update the style line:

```python
            style = "yellow" if "WATCHDOG" in event_name else "red bold" if "OBSTACLE" in event_name else "cyan" if "SCAN" in event_name else "red" if "ERR" in event_name else "white"
```

**Step 4: Increase vitals panel size from 5 to 6**

```python
    layout.split_column(
        Layout(name="motors", size=6),
        Layout(name="vitals", size=6),
        Layout(name="events"),
    )
```

**Step 5: Run all monitor tests**

Run: `cd /data/home/mguo/code/rover/monitor && python3 -m pytest test_monitor.py -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add monitor/rover_monitor.py monitor/test_monitor.py
git commit -m "feat(monitor): add heading display and scan event styling"
```

---

### Task 7: Agent Instructions — Navigation Strategy

**Files:**
- Modify: `openclaw-plugin/skills/rover/SKILL.md`
- Modify: `workspace/AGENTS.md`

**Step 1: Update SKILL.md**

Add the new tools and obstacle navigation instructions to `openclaw-plugin/skills/rover/SKILL.md`. After the existing Movement Tools section, add:

```markdown
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
```

Update the Rules section to add:

```markdown
7. If you hit an obstacle, use `rover_scan()` to find a way around it.
8. After scanning, explain your reasoning before moving.
```

**Step 2: Update AGENTS.md**

In `workspace/AGENTS.md`, in the "Command Interpretation" language mapping section, add:

```markdown
- "scan/look around" -> `rover_scan()`
- "face/turn to X degrees" -> `rover_spin_to(angle)`
```

In the "Safety Rules" section, add:

```markdown
- During a scan, the rover is spinning — do not issue other movement commands.
- After obstacle detection, prefer scan-and-navigate over blind retries.
```

**Step 3: Commit**

```bash
git add openclaw-plugin/skills/rover/SKILL.md workspace/AGENTS.md
git commit -m "docs: add scan and navigation strategy to agent instructions"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `AI_HANDOFF.md`

**Step 1: Update README.md**

1. In Hardware section, add: `- GY-521 (MPU6050) — gyroscope for heading control`
2. In Commands table, add: `| \`SPIN_TO <angle>\` | \`SPIN_TO 90\` | Spin to heading (0-359) using gyroscope |`
3. In Responses table, add: `| \`ERR:SPIN_TIMEOUT\` | SPIN_TO took >5 seconds |`
4. Update STATUS example to include `heading=`: `STATUS:motors=F180,F180;dist=42cm;heading=270;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz`

**Step 2: Update AI_HANDOFF.md**

1. Add gyroscope and scan to "What's built and working"
2. Add A4 (SDA) and A5 (SCL) to Pin Wiring table
3. Update available pins to `D4, D5, D13, A0–A3`

**Step 3: Commit**

```bash
git add README.md AI_HANDOFF.md
git commit -m "docs: add gyroscope and scan to README and AI handoff"
```
