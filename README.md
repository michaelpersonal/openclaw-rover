# OpenClaw Rover

An AI-powered 2WD rover controlled by natural language. An OpenClaw agent on a Raspberry Pi interprets commands like "go forward slowly" and translates them into motor actions via an Arduino Nano.

## Architecture

```
User (natural language)
  → OpenClaw agent (Raspberry Pi Zero 2W)
    → Serial protocol (USB, 9600 baud)
      → Arduino Nano firmware
        → TB6612FNG motor driver
          → DC motors + wheels
```

**Split brain design**: the Pi handles AI reasoning, the Arduino handles real-time motor control. They communicate over a simple ASCII serial protocol.

## Hardware

- 2WD Robot Car Chassis with TT Motors
- Raspberry Pi Zero 2 W — runs OpenClaw
- Arduino Nano (ATmega328P) — motor control
- WWZMDiB TB6612FNG — dual motor driver
- Battery / power bank
- HC-SR04 Ultrasonic Sensor — obstacle detection

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
  TOOLS.md                   # Environment-specific notes (serial port, etc.)
  AGENTS.md                  # Agent operating manual
  IDENTITY.md                # Agent name, emoji, vibe
  HEARTBEAT.md               # Periodic task checklist

docs/
  plans/                     # Design and implementation docs
  project-knowledge/         # Compound knowledge base
```

## Serial Protocol

ASCII text, newline-terminated. One command per line, one response per line.

### Commands (Pi → Arduino)

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
| `STATUS` | `STATUS` | Request telemetry |

Speed: 0–255 (PWM). ~80=slow, ~150=medium, ~200=fast.

### Responses (Arduino → Pi)

| Response | When |
|----------|------|
| `OK` | Command accepted |
| `ERR:<message>` | Parse error |
| `PONG` | Reply to PING |
| `STATUS:motors=F180,F180;dist=42cm;uptime=12340;cmds=47;last_cmd=230ms;loop=8200hz` | Telemetry |
| `STOPPED:WATCHDOG` | Auto-stopped (no command for 500ms) |
| `STOPPED:OBSTACLE` | Auto-stopped (obstacle <20cm ahead) |
| `ERR:OBSTACLE` | FORWARD rejected (obstacle present) |

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

### Install the OpenClaw plugin

```bash
cd openclaw-plugin
npm install
openclaw plugins install --link .
```

### Configure the workspace

Copy the workspace files to OpenClaw's workspace directory:

```bash
cp workspace/*.md ~/.openclaw/workspace/
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

Full steps to get the rover running on the Pi with real hardware.

### 1. Flash the Arduino

Connect the Arduino Nano via USB and upload the firmware:

```bash
arduino-cli compile --fqbn arduino:avr:nano arduino/rover/
arduino-cli upload --fqbn arduino:avr:nano --port /dev/ttyUSB0 arduino/rover/
```

### 2. Install OpenClaw on the Pi

```bash
# Install Node.js (v22+)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs

# Install OpenClaw
npm install -g openclaw
openclaw setup
```

### 3. Install the rover plugin

```bash
git clone https://github.com/michaelpersonal/openclaw-rover.git
cd openclaw-rover/openclaw-plugin
npm install
openclaw plugins install --link .
```

### 4. Deploy workspace files

```bash
cp ../workspace/*.md ~/.openclaw/workspace/
```

### 5. Configure the model and API key

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

### 6. Configure the serial port

Find the Arduino's serial port and set it:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

Edit `~/.openclaw/openclaw.json` — set `plugins.entries.rover-control.config.serialPort` to the port (e.g., `/dev/ttyUSB0`).

### 7. Verify

```bash
# Check model and auth
openclaw models status

# Test the rover
openclaw agent --local --agent main --message "ping the rover" --json
```

## Development

The simulator emulates the Arduino firmware over a virtual serial port. The OpenClaw plugin code is identical whether talking to the simulator or real hardware — only the serial port path changes.

```
Development:  OpenClaw → /dev/pts/X → Simulator
Production:   OpenClaw → /dev/ttyUSB0 → Arduino Nano → Motors
```
