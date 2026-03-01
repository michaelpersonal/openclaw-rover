# Rover Brain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the full movement command pipeline: Arduino firmware, Python simulator, and OpenClaw skill.

**Architecture:** Split-brain design. Arduino handles real-time motor control via serial protocol. Python simulator emulates the Arduino for local development. OpenClaw skill bridges AI agent to serial port.

**Tech Stack:** Arduino C++ (.ino), Python 3.10 (simulator + tests), TypeScript (OpenClaw skill)

---

### Task 1: Arduino Firmware — Motor Control and Serial Parser

**Files:**
- Create: `arduino/rover/rover.ino`

This is the production firmware that replaces `rover_test.ino`. We have `arduino-cli` installed with `arduino:avr` core, so we can compile-check against the Nano board.

**Step 1: Write the complete firmware**

```cpp
// Rover firmware — serial command parser with motor control
// Protocol: ASCII, newline-terminated, 9600 baud
// See docs/plans/2026-03-01-rover-brain-design.md

// === Pin mapping (Arduino Nano → TB6612FNG) ===
// Motor A = Left motor
const int PWMA = 6;
const int AIN2 = 7;
const int AIN1 = 8;
// Motor B = Right motor
const int BIN1 = 9;
const int BIN2 = 10;
const int PWMB = 11;
// Standby
const int STBY = 12;

// === Motor direction constants ===
const int DIR_STOP = 0;
const int DIR_FORWARD = 1;
const int DIR_REVERSE = 2;

// === State ===
char cmdBuffer[64];
int cmdLen = 0;

int leftSpeed = 0;
int leftDir = DIR_STOP;
int rightSpeed = 0;
int rightDir = DIR_STOP;

unsigned long lastCmdTime = 0;
bool watchdogFired = false;
unsigned long cmdCount = 0;
unsigned long loopCount = 0;
unsigned long loopRateTime = 0;
unsigned long loopRate = 0;

const unsigned long WATCHDOG_TIMEOUT = 500;

// === Motor control ===
void setMotors(int lSpeed, int lDir, int rSpeed, int rDir) {
  leftSpeed = lSpeed;
  leftDir = lDir;
  rightSpeed = rSpeed;
  rightDir = rDir;

  // Clamp speed
  lSpeed = constrain(lSpeed, 0, 255);
  rSpeed = constrain(rSpeed, 0, 255);

  // Left motor (Motor A)
  if (lDir == DIR_FORWARD) {
    digitalWrite(AIN1, HIGH);
    digitalWrite(AIN2, LOW);
  } else if (lDir == DIR_REVERSE) {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, HIGH);
  } else {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, LOW);
  }
  analogWrite(PWMA, lDir == DIR_STOP ? 0 : lSpeed);

  // Right motor (Motor B)
  if (rDir == DIR_FORWARD) {
    digitalWrite(BIN1, HIGH);
    digitalWrite(BIN2, LOW);
  } else if (rDir == DIR_REVERSE) {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, HIGH);
  } else {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, LOW);
  }
  analogWrite(PWMB, rDir == DIR_STOP ? 0 : rSpeed);
}

void stopMotors() {
  setMotors(0, DIR_STOP, 0, DIR_STOP);
}

// === STATUS response helper ===
char motorChar(int dir) {
  if (dir == DIR_FORWARD) return 'F';
  if (dir == DIR_REVERSE) return 'R';
  return 'S';
}

void sendStatus() {
  unsigned long now = millis();
  unsigned long timeSinceCmd = (cmdCount == 0) ? now : (now - lastCmdTime);

  Serial.print("STATUS:motors=");
  if (leftDir == DIR_STOP) {
    Serial.print("S");
  } else {
    Serial.print(motorChar(leftDir));
    Serial.print(leftSpeed);
  }
  Serial.print(",");
  if (rightDir == DIR_STOP) {
    Serial.print("S");
  } else {
    Serial.print(motorChar(rightDir));
    Serial.print(rightSpeed);
  }
  Serial.print(";uptime=");
  Serial.print(now);
  Serial.print(";cmds=");
  Serial.print(cmdCount);
  Serial.print(";last_cmd=");
  Serial.print(timeSinceCmd);
  Serial.print("ms;loop=");
  Serial.print(loopRate);
  Serial.println("hz");
}

// === Command processing ===
void processCommand(char* cmd) {
  cmdCount++;
  lastCmdTime = millis();
  watchdogFired = false;

  // Trim trailing \r if present
  int len = strlen(cmd);
  if (len > 0 && cmd[len - 1] == '\r') {
    cmd[len - 1] = '\0';
    len--;
  }

  if (len == 0) {
    Serial.println("ERR:EMPTY");
    return;
  }

  // Split command and argument
  char* space = strchr(cmd, ' ');
  int speed = 0;
  if (space != NULL) {
    *space = '\0';
    speed = constrain(atoi(space + 1), 0, 255);
  }

  // Dispatch
  if (strcmp(cmd, "FORWARD") == 0) {
    setMotors(speed, DIR_FORWARD, speed, DIR_FORWARD);
    Serial.println("OK");
  } else if (strcmp(cmd, "BACKWARD") == 0) {
    setMotors(speed, DIR_REVERSE, speed, DIR_REVERSE);
    Serial.println("OK");
  } else if (strcmp(cmd, "LEFT") == 0) {
    setMotors(0, DIR_STOP, speed, DIR_FORWARD);
    Serial.println("OK");
  } else if (strcmp(cmd, "RIGHT") == 0) {
    setMotors(speed, DIR_FORWARD, 0, DIR_STOP);
    Serial.println("OK");
  } else if (strcmp(cmd, "SPIN_LEFT") == 0) {
    setMotors(speed, DIR_REVERSE, speed, DIR_FORWARD);
    Serial.println("OK");
  } else if (strcmp(cmd, "SPIN_RIGHT") == 0) {
    setMotors(speed, DIR_FORWARD, speed, DIR_REVERSE);
    Serial.println("OK");
  } else if (strcmp(cmd, "STOP") == 0) {
    stopMotors();
    Serial.println("OK");
  } else if (strcmp(cmd, "PING") == 0) {
    Serial.println("PONG");
  } else if (strcmp(cmd, "STATUS") == 0) {
    sendStatus();
  } else {
    Serial.print("ERR:UNKNOWN_CMD:");
    Serial.println(cmd);
  }
}

// === Setup ===
void setup() {
  pinMode(PWMA, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(PWMB, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(STBY, OUTPUT);

  digitalWrite(STBY, HIGH);
  stopMotors();

  Serial.begin(9600);
  lastCmdTime = millis();
  loopRateTime = millis();
}

// === Main loop (non-blocking) ===
void loop() {
  // 1. Watchdog check
  if (cmdCount > 0 && !watchdogFired) {
    if (millis() - lastCmdTime > WATCHDOG_TIMEOUT) {
      stopMotors();
      Serial.println("STOPPED:WATCHDOG");
      watchdogFired = true;
    }
  }

  // 2. Read serial byte-by-byte
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      cmdBuffer[cmdLen] = '\0';
      processCommand(cmdBuffer);
      cmdLen = 0;
    } else if (cmdLen < 63) {
      cmdBuffer[cmdLen++] = c;
    } else {
      // Buffer overflow — discard
      cmdLen = 0;
      Serial.println("ERR:OVERFLOW");
    }
  }

  // 3. Loop rate tracking (update every second)
  loopCount++;
  if (millis() - loopRateTime >= 1000) {
    loopRate = loopCount;
    loopCount = 0;
    loopRateTime = millis();
  }
}
```

**Step 2: Compile-check against Arduino Nano**

Run: `arduino-cli compile --fqbn arduino:avr:nano arduino/rover/`
Expected: Compilation successful, no errors. Note flash/RAM usage.

**Step 3: Commit**

```bash
git add arduino/rover/rover.ino
git commit -m "feat(arduino): add production firmware with serial command parser

Implements: FORWARD, BACKWARD, LEFT, RIGHT, SPIN_LEFT, SPIN_RIGHT,
STOP, PING, STATUS. Includes 500ms watchdog and telemetry.
Compile-verified against arduino:avr:nano."
```

---

### Task 2: Python Simulator — Core Protocol

**Files:**
- Create: `simulator/rover_sim.py`
- Create: `simulator/test_rover_sim.py`

The simulator emulates the Arduino firmware over a virtual serial port. We build and test it incrementally.

**Step 1: Write the failing test — command parsing**

```python
# simulator/test_rover_sim.py
import pytest
from rover_sim import RoverSimulator


class TestCommandParsing:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_forward(self):
        resp = self.sim.process_command("FORWARD 180")
        assert resp == "OK"
        assert self.sim.left_speed == 180
        assert self.sim.left_dir == "F"
        assert self.sim.right_speed == 180
        assert self.sim.right_dir == "F"

    def test_backward(self):
        resp = self.sim.process_command("BACKWARD 150")
        assert resp == "OK"
        assert self.sim.left_dir == "R"
        assert self.sim.right_dir == "R"

    def test_left(self):
        resp = self.sim.process_command("LEFT 120")
        assert resp == "OK"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"
        assert self.sim.right_speed == 120
        assert self.sim.right_dir == "F"

    def test_right(self):
        resp = self.sim.process_command("RIGHT 120")
        assert resp == "OK"
        assert self.sim.left_speed == 120
        assert self.sim.left_dir == "F"
        assert self.sim.right_speed == 0
        assert self.sim.right_dir == "S"

    def test_spin_left(self):
        resp = self.sim.process_command("SPIN_LEFT 100")
        assert resp == "OK"
        assert self.sim.left_dir == "R"
        assert self.sim.right_dir == "F"

    def test_spin_right(self):
        resp = self.sim.process_command("SPIN_RIGHT 100")
        assert resp == "OK"
        assert self.sim.left_dir == "F"
        assert self.sim.right_dir == "R"

    def test_stop(self):
        self.sim.process_command("FORWARD 200")
        resp = self.sim.process_command("STOP")
        assert resp == "OK"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"
        assert self.sim.right_speed == 0
        assert self.sim.right_dir == "S"

    def test_ping(self):
        resp = self.sim.process_command("PING")
        assert resp == "PONG"

    def test_unknown_command(self):
        resp = self.sim.process_command("DANCE 100")
        assert resp.startswith("ERR:")

    def test_empty_command(self):
        resp = self.sim.process_command("")
        assert resp.startswith("ERR:")

    def test_speed_clamped_high(self):
        self.sim.process_command("FORWARD 300")
        assert self.sim.left_speed == 255

    def test_speed_clamped_low(self):
        self.sim.process_command("FORWARD -10")
        assert self.sim.left_speed == 0

    def test_command_count(self):
        assert self.sim.cmd_count == 0
        self.sim.process_command("PING")
        self.sim.process_command("PING")
        assert self.sim.cmd_count == 2
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/home/mguo/code/rover && python -m pytest simulator/test_rover_sim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rover_sim'`

**Step 3: Write the RoverSimulator class**

```python
# simulator/rover_sim.py
"""
Rover simulator — emulates Arduino firmware serial protocol.
Speaks the same command/response format over a virtual serial port.
"""
import os
import pty
import select
import time


class RoverSimulator:
    """Core protocol logic. No I/O — just state machine."""

    def __init__(self):
        self.left_speed = 0
        self.left_dir = "S"  # S=stopped, F=forward, R=reverse
        self.right_speed = 0
        self.right_dir = "S"
        self.cmd_count = 0
        self.start_time = time.time()
        self.last_cmd_time = None
        self.watchdog_fired = False

    def _set_motors(self, left_speed, left_dir, right_speed, right_dir):
        self.left_speed = max(0, min(255, left_speed))
        self.left_dir = left_dir
        self.right_speed = max(0, min(255, right_speed))
        self.right_dir = right_dir

    def _stop_motors(self):
        self._set_motors(0, "S", 0, "S")

    def _motor_str(self, speed, direction):
        if direction == "S":
            return "S"
        return f"{direction}{speed}"

    def process_command(self, line):
        """Process a single command line. Returns response string."""
        self.cmd_count += 1
        self.last_cmd_time = time.time()
        self.watchdog_fired = False

        line = line.strip()
        if not line:
            return "ERR:EMPTY"

        parts = line.split(" ", 1)
        cmd = parts[0]
        speed = max(0, min(255, int(parts[1]))) if len(parts) > 1 else 0

        if cmd == "FORWARD":
            self._set_motors(speed, "F", speed, "F")
            return "OK"
        elif cmd == "BACKWARD":
            self._set_motors(speed, "R", speed, "R")
            return "OK"
        elif cmd == "LEFT":
            self._set_motors(0, "S", speed, "F")
            return "OK"
        elif cmd == "RIGHT":
            self._set_motors(speed, "F", 0, "S")
            return "OK"
        elif cmd == "SPIN_LEFT":
            self._set_motors(speed, "R", speed, "F")
            return "OK"
        elif cmd == "SPIN_RIGHT":
            self._set_motors(speed, "F", speed, "R")
            return "OK"
        elif cmd == "STOP":
            self._stop_motors()
            return "OK"
        elif cmd == "PING":
            return "PONG"
        elif cmd == "STATUS":
            return self._status_response()
        else:
            return f"ERR:UNKNOWN_CMD:{cmd}"

    def _status_response(self):
        now = time.time()
        uptime_ms = int((now - self.start_time) * 1000)
        last_cmd_ms = int((now - self.last_cmd_time) * 1000) if self.last_cmd_time else uptime_ms
        left = self._motor_str(self.left_speed, self.left_dir)
        right = self._motor_str(self.right_speed, self.right_dir)
        return f"STATUS:motors={left},{right};uptime={uptime_ms};cmds={self.cmd_count};last_cmd={last_cmd_ms}ms;loop=0hz"

    def check_watchdog(self, timeout_ms=500):
        """Check watchdog. Returns 'STOPPED:WATCHDOG' if triggered, else None."""
        if self.last_cmd_time is None or self.watchdog_fired:
            return None
        elapsed = (time.time() - self.last_cmd_time) * 1000
        if elapsed > timeout_ms:
            self._stop_motors()
            self.watchdog_fired = True
            return "STOPPED:WATCHDOG"
        return None


def run_simulator():
    """Run simulator with virtual serial port pair."""
    master_fd, slave_fd = pty.openpty()
    slave_path = os.ttyname(slave_fd)
    print(f"Rover simulator started")
    print(f"Connect to: {slave_path}")
    print(f"Waiting for commands...\n")

    sim = RoverSimulator()
    buf = b""

    try:
        while True:
            # Check watchdog
            wd = sim.check_watchdog()
            if wd:
                os.write(master_fd, (wd + "\n").encode())
                elapsed = time.time() - sim.start_time
                print(f"[{elapsed:.1f}s] WATCHDOG → motors stopped")

            # Poll for incoming data (100ms timeout)
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if not ready:
                continue

            data = os.read(master_fd, 1024)
            if not data:
                break
            buf += data

            # Process complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                if not cmd:
                    continue

                response = sim.process_command(cmd)
                os.write(master_fd, (response + "\n").encode())

                elapsed = time.time() - sim.start_time
                left = sim._motor_str(sim.left_speed, sim.left_dir)
                right = sim._motor_str(sim.right_speed, sim.right_dir)
                print(f"[{elapsed:.1f}s] {cmd} → {response}  |  motors: L={left} R={right}")

    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        os.close(master_fd)
        os.close(slave_fd)


if __name__ == "__main__":
    run_simulator()
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python -m pytest simulator/test_rover_sim.py -v`
Expected: All 14 tests PASS

**Step 5: Commit**

```bash
git add simulator/rover_sim.py simulator/test_rover_sim.py
git commit -m "feat(simulator): add rover simulator with virtual serial port

Emulates Arduino firmware protocol. Includes test suite for all 9
commands, speed clamping, error handling, and telemetry."
```

---

### Task 3: Simulator Tests — STATUS and Watchdog

**Files:**
- Modify: `simulator/test_rover_sim.py`

**Step 1: Write failing tests for STATUS and watchdog**

Add to `simulator/test_rover_sim.py`:

```python
class TestStatus:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_status_when_stopped(self):
        resp = self.sim.process_command("STATUS")
        assert resp.startswith("STATUS:motors=S,S;")
        assert "cmds=1;" in resp

    def test_status_when_moving(self):
        self.sim.process_command("FORWARD 180")
        resp = self.sim.process_command("STATUS")
        assert "motors=F180,F180;" in resp
        assert "cmds=2;" in resp

    def test_status_format(self):
        resp = self.sim.process_command("STATUS")
        # Verify all fields present
        assert "motors=" in resp
        assert "uptime=" in resp
        assert "cmds=" in resp
        assert "last_cmd=" in resp
        assert "loop=" in resp


class TestWatchdog:
    def setup_method(self):
        self.sim = RoverSimulator()

    def test_no_watchdog_before_first_command(self):
        result = self.sim.check_watchdog()
        assert result is None

    def test_no_watchdog_right_after_command(self):
        self.sim.process_command("FORWARD 180")
        result = self.sim.check_watchdog()
        assert result is None

    def test_watchdog_fires_after_timeout(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0  # fake 1s ago
        result = self.sim.check_watchdog()
        assert result == "STOPPED:WATCHDOG"
        assert self.sim.left_speed == 0
        assert self.sim.left_dir == "S"

    def test_watchdog_fires_only_once(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0
        self.sim.check_watchdog()  # fires
        result = self.sim.check_watchdog()  # should not fire again
        assert result is None

    def test_watchdog_resets_on_new_command(self):
        self.sim.process_command("FORWARD 180")
        self.sim.last_cmd_time = time.time() - 1.0
        self.sim.check_watchdog()  # fires
        self.sim.process_command("FORWARD 100")  # reset
        assert self.sim.watchdog_fired is False
        assert self.sim.left_speed == 100
```

Also add `import time` to the top of the test file if not present.

**Step 2: Run tests to verify they pass**

Run: `cd /data/home/mguo/code/rover && python -m pytest simulator/test_rover_sim.py -v`
Expected: All 22 tests PASS (the implementation from Task 2 already handles these)

**Step 3: Commit**

```bash
git add simulator/test_rover_sim.py
git commit -m "test(simulator): add STATUS and watchdog tests"
```

---

### Task 4: Simulator — Integration Test via Virtual Serial Port

**Files:**
- Create: `simulator/test_serial_integration.py`

This tests the full loop: write to virtual serial port → simulator reads → processes → writes response.

**Step 1: Write the integration test**

```python
# simulator/test_serial_integration.py
"""Integration test: talk to simulator over virtual serial port pair."""
import os
import pty
import time
import threading
import pytest
from rover_sim import RoverSimulator


class TestSerialIntegration:
    """Test the simulator via a real pty serial port pair."""

    def setup_method(self):
        self.master_fd, self.slave_fd = pty.openpty()
        self.sim = RoverSimulator()
        self.running = True
        self.sim_thread = threading.Thread(target=self._run_sim, daemon=True)
        self.sim_thread.start()
        time.sleep(0.05)  # let thread start

    def teardown_method(self):
        self.running = False
        os.close(self.master_fd)
        os.close(self.slave_fd)

    def _run_sim(self):
        """Simulator loop running in a thread."""
        import select
        buf = b""
        while self.running:
            ready, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not ready:
                continue
            try:
                data = os.read(self.master_fd, 1024)
            except OSError:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("ascii", errors="replace").strip()
                if cmd:
                    response = self.sim.process_command(cmd)
                    os.write(self.master_fd, (response + "\n").encode())

    def _send_recv(self, command, timeout=1.0):
        """Send command via slave fd, read response."""
        os.write(self.slave_fd, (command + "\n").encode())
        # Read response
        import select
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([self.slave_fd], [], [], 0.1)
            if ready:
                buf += os.read(self.slave_fd, 1024)
                if b"\n" in buf:
                    return buf.decode("ascii").strip().split("\n")[0]
        return None

    def test_ping_pong(self):
        resp = self._send_recv("PING")
        assert resp == "PONG"

    def test_forward_ok(self):
        resp = self._send_recv("FORWARD 180")
        assert resp == "OK"

    def test_stop_ok(self):
        self._send_recv("FORWARD 180")
        resp = self._send_recv("STOP")
        assert resp == "OK"

    def test_status_response(self):
        self._send_recv("FORWARD 150")
        resp = self._send_recv("STATUS")
        assert resp.startswith("STATUS:motors=F150,F150;")

    def test_unknown_command(self):
        resp = self._send_recv("DANCE 100")
        assert resp.startswith("ERR:")

    def test_multiple_commands(self):
        assert self._send_recv("FORWARD 100") == "OK"
        assert self._send_recv("LEFT 80") == "OK"
        assert self._send_recv("STOP") == "OK"
        resp = self._send_recv("STATUS")
        assert "motors=S,S;" in resp
```

**Step 2: Run tests**

Run: `cd /data/home/mguo/code/rover && python -m pytest simulator/test_serial_integration.py -v`
Expected: All 6 tests PASS

**Step 3: Commit**

```bash
git add simulator/test_serial_integration.py
git commit -m "test(simulator): add serial port integration tests

Tests full pty round-trip: command → simulator → response."
```

---

### Task 5: OpenClaw Skill — Rover Control

**Files:**
- Create: `openclaw-skill/rover.ts`
- Create: `openclaw-skill/openclaw.plugin.json`

**Note:** We need to research the exact OpenClaw skill API. The code below is based on the documented plugin structure. We may need to adjust after checking OpenClaw docs.

**Step 1: Research OpenClaw skill/plugin API**

Run: `curl -s https://raw.githubusercontent.com/openclaw/openclaw/main/docs/tools/skills.md 2>/dev/null | head -200`

Also check: `curl -s "https://api.github.com/repos/openclaw/openclaw/contents/docs" | python3 -c "import sys,json;[print(i['name']) for i in json.load(sys.stdin)]"`

Use the findings to adjust the skill code in Step 2.

**Step 2: Write the OpenClaw plugin manifest**

```json
{
  "name": "rover-control",
  "version": "0.1.0",
  "description": "Control a 2WD rover via serial commands",
  "entry": "rover.ts",
  "config": {
    "serialPort": {
      "type": "string",
      "description": "Serial port path (e.g., /dev/ttyUSB0 or /dev/pts/X for simulator)",
      "default": "/dev/ttyUSB0"
    }
  }
}
```

**Step 3: Write the rover skill**

```typescript
// openclaw-skill/rover.ts
// OpenClaw skill for rover motor control via serial port.
// Sends ASCII commands to Arduino (or simulator) and returns responses.

import { SerialPort } from "serialport";
import { ReadlineParser } from "@serialport/parser-readline";

// This will be adapted based on the actual OpenClaw plugin API
// discovered in Step 1. The serial communication logic stays the same.

const SPEED_HINT = `Speed 0-255: 0=stopped, ~80=slow, ~150=medium, ~200=fast, 255=max`;

interface RoverState {
  port: SerialPort | null;
  parser: ReadlineParser | null;
  pending: ((value: string) => void) | null;
}

const state: RoverState = {
  port: null,
  parser: null,
  pending: null,
};

function sendCommand(cmd: string): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!state.port || !state.port.isOpen) {
      reject(new Error("Serial port not connected"));
      return;
    }
    state.pending = resolve;
    state.port.write(cmd + "\n", (err) => {
      if (err) {
        state.pending = null;
        reject(err);
      }
    });
    // Timeout after 2s
    setTimeout(() => {
      if (state.pending === resolve) {
        state.pending = null;
        reject(new Error("Response timeout"));
      }
    }, 2000);
  });
}

// Tool definitions — will be registered with OpenClaw plugin API
// Exact registration mechanism depends on Step 1 research.

const tools = {
  rover_forward: {
    description: `Move rover forward. ${SPEED_HINT}`,
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`FORWARD ${args.speed}`),
  },
  rover_backward: {
    description: `Move rover backward. ${SPEED_HINT}`,
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`BACKWARD ${args.speed}`),
  },
  rover_left: {
    description: "Turn rover left (stops left motor, right motor forward)",
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`LEFT ${args.speed}`),
  },
  rover_right: {
    description: "Turn rover right (left motor forward, stops right motor)",
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`RIGHT ${args.speed}`),
  },
  rover_spin_left: {
    description: "Spin rover left in place (pivot)",
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`SPIN_LEFT ${args.speed}`),
  },
  rover_spin_right: {
    description: "Spin rover right in place (pivot)",
    params: { speed: "number (0-255)" },
    run: (args: { speed: number }) => sendCommand(`SPIN_RIGHT ${args.speed}`),
  },
  rover_stop: {
    description: "Stop all motors immediately",
    params: {},
    run: () => sendCommand("STOP"),
  },
  rover_status: {
    description: "Get current rover state (motor speeds, uptime, command count)",
    params: {},
    run: () => sendCommand("STATUS"),
  },
};

// System prompt snippet for the LLM
const systemPrompt = `You control a 2WD rover via movement tools.
Speed range 0-255: 0=stopped, ~80=slow, ~150=medium, ~200=fast, 255=max.
LEFT/RIGHT = turn by stopping one motor. SPIN_LEFT/SPIN_RIGHT = pivot in place.
Call rover_status to check current state. Always call rover_stop when done moving.`;

export { tools, systemPrompt, sendCommand };
```

**Step 4: Commit**

```bash
git add openclaw-skill/rover.ts openclaw-skill/openclaw.plugin.json
git commit -m "feat(skill): add OpenClaw rover control skill

Registers 8 tools for rover movement. Serial port configurable.
Skill code works identically with simulator or real hardware."
```

---

### Task 6: End-to-End Manual Test

**Files:** None — this is a manual verification step.

**Step 1: Start the simulator**

Run: `cd /data/home/mguo/code/rover && python simulator/rover_sim.py`
Note the `/dev/pts/X` path it prints.

**Step 2: Test with a simple Python serial client**

In a second terminal:
```python
import serial
port = serial.Serial('/dev/pts/X', 9600, timeout=1)  # use path from step 1
port.write(b"PING\n")
print(port.readline())  # should print b'PONG\n'
port.write(b"FORWARD 150\n")
print(port.readline())  # should print b'OK\n'
port.write(b"STATUS\n")
print(port.readline())  # should print STATUS with F150,F150
port.write(b"STOP\n")
print(port.readline())  # should print b'OK\n'
port.close()
```

**Step 3: Verify simulator terminal output**

The simulator should show:
```
[0.1s] PING → PONG  |  motors: L=S R=S
[0.2s] FORWARD 150 → OK  |  motors: L=F150 R=F150
[0.3s] STATUS → STATUS:...  |  motors: L=F150 R=F150
[0.4s] STOP → OK  |  motors: L=S R=S
```

**Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: project structure complete — firmware, simulator, skill"
```
