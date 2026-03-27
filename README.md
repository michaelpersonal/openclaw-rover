# OpenClaw Rover

An AI-powered 2WD rover controlled by natural language. OpenClaw on a Raspberry Pi 5 interprets commands like "go forward slowly" and relays them to a Raspberry Pi Zero bridge, which drives an Arduino Nano over USB serial.

## Architecture

```
User (natural language)
  → Telegram / OpenClaw agent (Raspberry Pi 5, "guopi")
    → SSH wrapper (`rover-remote`)
      → Rover drive daemon (Raspberry Pi Zero, "roverpi")
        → Serial protocol (USB, 9600 baud)
          → Arduino Nano firmware
            → TB6612FNG motor driver
              → DC motors + wheels
```

The system is split across three control layers:

- Pi 5: OpenClaw gateway, Telegram integration, command interpretation
- Pi Zero: persistent drive daemon, obstacle recovery, serial bridge
- Arduino: real-time motor control, obstacle stop, heading telemetry

## Current Runtime Topology

- Pi 5 host: `guopi`
- Pi Zero host: `roverpi`
- Pi 5 control entrypoint: `~/.local/bin/rover-remote`
- Pi Zero control scripts:
  - `~/rover/bin/rover-drive`
  - `~/rover/bin/rover-drive-daemon.py`
  - `~/rover/bin/roverctl.py`

The live Telegram path is:

```text
Telegram → OpenClaw on Pi5 → rover-remote over SSH → rover-drive on Pi Zero → Arduino
```

## Live Rover Behavior

- Default speed when no speed is provided: `60`
- Canonical stop phrase in Telegram: `rover stop`
- `go forward` means continuous forward motion until explicit stop or hardware obstacle stop
- On `STOPPED:OBSTACLE`, Pi Zero attempts local auto-recovery:
  - stop immediately
  - run a 360 scan
  - rotate toward the clearest sector
  - resume motion if the post-turn status confirms the rover is moving
- If recovery cannot produce a valid scan/turn/resume result, the rover remains stopped and reports the failure state

## Hardware

- 2WD Robot Car Chassis with TT Motors
- Raspberry Pi Zero 2 W — runs OpenClaw
- Arduino Nano (ATmega328P) — motor control
- WWZMDiB TB6612FNG — dual motor driver
- Battery / power bank
- HC-SR04 Ultrasonic Sensor — obstacle detection
- GY-521 (MPU6050) — gyroscope for heading control

## Project Structure

```
arduino/
  rover/rover.ino           # Production firmware (serial parser + motor control)
  rover_test/rover_test.ino  # Original hardware test sketch

simulator/
  rover_sim.py               # Python simulator (virtual serial port)
  e2e_test.py                # End-to-end test script
  test_rover_sim.py          # Unit tests (21 tests)
  test_serial_integration.py # Integration tests (6 tests)

openclaw-plugin/
  index.ts                   # Plugin entry — registers 8 tools + telemetry server
  openclaw.plugin.json       # Plugin manifest
  package.json               # Dependencies
  skills/rover/SKILL.md      # LLM instructions

monitor/
  rover_monitor.py           # Live TUI telemetry dashboard
  test_monitor.py            # Unit tests (14 tests)
  requirements.txt           # Python dependencies (rich)

workspace/
  SOUL.md                    # Agent personality and values
  USER.md                    # Human user profile
  TOOLS.md                   # Runtime topology + tool notes
  AGENTS.md                  # Rover agent operating manual
  IDENTITY.md                # Agent name, emoji, vibe
  HEARTBEAT.md               # Periodic task checklist

docs/
  plans/                     # Design and implementation docs
  project-knowledge/         # Compound knowledge base

deploy/
  pi5/bin/rover-remote       # Pi5 SSH wrapper to Pi Zero
  pi5/bin/rover-obstacle-notifier.py
  pi-zero/bin/rover-drive    # Pi Zero drive control entrypoint
  pi-zero/bin/rover-drive-daemon.py
  pi-zero/bin/roverctl.py    # Direct serial bridge and scan helpers
```

## Serial Protocol

ASCII text, newline-terminated. One command per line, one response per line.

### Commands (Pi Zero → Arduino)

| Command | Example | Behavior |
|---------|---------|----------|
| `FORWARD <speed>` | `FORWARD 180` | Both motors forward |
| `BACKWARD <speed>` | `BACKWARD 150` | Both motors reverse |
| `LEFT <speed>` | `LEFT 120` | Left stop, right forward |
| `RIGHT <speed>` | `RIGHT 120` | Left forward, right stop |
| `SPIN_LEFT <speed>` | `SPIN_LEFT 100` | Left reverse, right forward |
| `SPIN_RIGHT <speed>` | `SPIN_RIGHT 100` | Left forward, right reverse |
| `STOP` | `STOP` | All motors off |
| `PING` | `PING` | Heartbeat |
| `SPIN_TO <angle>` | `SPIN_TO 90` | Spin to heading (0-359) using gyroscope |
| `STATUS` | `STATUS` | Request telemetry |

Speed: 0–255 (PWM). ~80=slow, ~150=medium, ~200=fast.

### Responses (Arduino → Pi)

| Response | When |
|----------|------|
| `OK` | Command accepted |
| `ERR:<message>` | Parse error |
| `PONG` | Reply to PING |
| `STATUS:motors=F180,F180;dist=42cm;heading=270;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz` | Telemetry |
| `STOPPED:WATCHDOG` | Auto-stopped (no command for 500ms) |
| `STOPPED:OBSTACLE` | Auto-stopped (obstacle <20cm ahead) |
| `ERR:OBSTACLE` | FORWARD rejected (obstacle present) |
| `ERR:SPIN_TIMEOUT` | SPIN_TO took >5 seconds |

## Quick Start

### Run the simulator (no hardware needed)

```bash
# Run all tests
python3 -m pytest simulator/ -v

# Run end-to-end demo
python3 simulator/e2e_test.py
```

### Flash the Arduino

```bash
# Compile-check
arduino-cli compile --fqbn arduino:avr:nano arduino/rover/

# Upload (when connected via USB)
arduino-cli upload --fqbn arduino:avr:nano --port /dev/ttyUSB0 arduino/rover/
```

### Pi5 command examples

```bash
~/.local/bin/rover-remote forward 60
~/.local/bin/rover-remote status
~/.local/bin/rover-remote stop
~/.local/bin/rover-remote scan
```

### Pi Zero command examples

```bash
~/rover/bin/rover-drive start forward 60
~/rover/bin/rover-drive status
~/rover/bin/rover-drive stop
~/rover/bin/roverctl.py scan
```

### Install the OpenClaw plugin

```bash
cd openclaw-plugin
npm install
openclaw plugins install --link .
```

### Configure the workspace

Copy the rover workspace files to OpenClaw's workspace directory:

```bash
mkdir -p ~/.openclaw/workspaces/rover
cp workspace/*.md ~/.openclaw/workspaces/rover/
```

### Configure the serial port

Find your serial port:

```bash
# Real hardware (Arduino via USB)
ls /dev/ttyUSB* /dev/ttyACM*

# Simulator
python3 simulator/rover_sim.py   # prints the pty path
```

Set it in `~/.openclaw/openclaw.json`:

```json
"plugins": {
  "entries": {
    "rover-control": {
      "enabled": true,
      "config": {
        "serialPort": "/dev/ttyUSB0",
        "baudRate": 9600
      }
    }
  }
}
```

### Run the telemetry monitor

```bash
pip install rich
python3 monitor/rover_monitor.py
```

The monitor connects to the OpenClaw plugin's telemetry socket and shows live motor state, vitals, and command history. Start it alongside the simulator and OpenClaw to watch the rover in real-time.

## Deploy to Raspberry Pi

Full steps for the current split Pi5/Pi Zero deployment.

### 1. Flash the Arduino

Connect the Arduino Nano via USB and upload the firmware:

```bash
arduino-cli compile --fqbn arduino:avr:nano arduino/rover/
arduino-cli upload --fqbn arduino:avr:nano --port /dev/ttyUSB0 arduino/rover/
```

### 2. Install OpenClaw on Pi5

```bash
# Install Node.js (v22+)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs

# Install OpenClaw
npm install -g openclaw
openclaw setup
```

### 3. Install the rover repo on Pi5

```bash
git clone https://github.com/michaelpersonal/openclaw-rover.git
cd openclaw-rover/openclaw-plugin
npm install
openclaw plugins install --link .
```

### 4. Deploy the rover workspace on Pi5

```bash
mkdir -p ~/.openclaw/workspaces/rover
cp ../workspace/*.md ~/.openclaw/workspaces/rover/
```

### 5. Install the Pi5 rover wrapper

```bash
mkdir -p ~/.local/bin
cp ../deploy/pi5/bin/rover-remote ~/.local/bin/rover-remote
cp ../deploy/pi5/bin/rover-obstacle-notifier.py ~/.openclaw/workspaces/rover/bin/rover-obstacle-notifier.py
chmod +x ~/.local/bin/rover-remote ~/.openclaw/workspaces/rover/bin/rover-obstacle-notifier.py
```

### 6. Configure the model and API key

Set your preferred model, then add the API key:

```bash
# Set model (pick one)
openclaw config set agents.defaults.model.primary google/gemini-2.5-flash
openclaw config set agents.defaults.model.primary kimi/moonshot-v1
openclaw config set agents.defaults.model.primary openai/codex

# Add API key
mkdir -p ~/.openclaw/agents/main/agent
cat > ~/.openclaw/agents/main/agent/auth-profiles.json << 'EOF'
{
  "version": 1,
  "profiles": {
    "PROVIDER:manual": {
      "provider": "PROVIDER",
      "apiKey": "YOUR_API_KEY",
      "type": "api_key"
    }
  }
}
EOF
```

Replace `PROVIDER` with `google`, `kimi`, `openai`, etc. to match your model.

### 7. Install the Pi Zero rover bridge

Copy the Pi Zero scripts to `roverpi`:

```bash
scp deploy/pi-zero/bin/rover-drive roverpi:~/rover/bin/rover-drive
scp deploy/pi-zero/bin/rover-drive-daemon.py roverpi:~/rover/bin/rover-drive-daemon.py
scp deploy/pi-zero/bin/roverctl.py roverpi:~/rover/bin/roverctl.py
ssh roverpi 'chmod +x ~/rover/bin/rover-drive ~/rover/bin/rover-drive-daemon.py ~/rover/bin/roverctl.py'
```

### 8. Configure SSH from Pi5 to Pi Zero

Add an SSH host entry on Pi5:

```sshconfig
Host roverpi
  HostName 100.x.x.x
  User mguo
```

### 9. Configure the serial port on Pi Zero

Find the Arduino's serial port and set it:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

The Pi Zero scripts auto-discover `/dev/ttyUSB0` and `/dev/ttyACM0`. Simulator mode uses `~/rover/sim_port`.

### 10. Verify

On Pi5:

```bash
~/.local/bin/rover-remote ping
~/.local/bin/rover-remote status
```

On Pi Zero:

```bash
~/rover/bin/rover-drive status
~/rover/bin/roverctl.py scan
```

## Development

The simulator emulates the Arduino firmware over a virtual serial port. The OpenClaw plugin code is identical whether talking to the simulator or real hardware — only the serial port path changes.

```
Development:  OpenClaw → /dev/pts/X → Simulator
Production:   OpenClaw → /dev/ttyUSB0 → Arduino Nano → Motors
```
