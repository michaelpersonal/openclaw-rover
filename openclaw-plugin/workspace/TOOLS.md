# TOOLS.md - Local Notes

## Rover Serial Port

The rover-control plugin connects to the Arduino (or simulator) via serial port.

### Finding the port

- **Real hardware** (Arduino Nano via USB): Usually `/dev/ttyUSB0` or `/dev/ttyACM0`
  - Run: `ls /dev/ttyUSB* /dev/ttyACM*` to find it
- **Simulator**: The simulator prints its pty path on startup, e.g., `/dev/pts/4`
  - Run: `python3 ~/code/rover/simulator/rover_sim.py` — it prints the port

### Changing the port

Edit `~/.openclaw/openclaw.json`, find `plugins.entries.rover-control.config.serialPort` and set it:

```json
"config": {
  "serialPort": "/dev/pts/4",
  "baudRate": 9600
}
```

Then restart OpenClaw.

### Speed reference

| Label  | PWM value |
|--------|-----------|
| Slow   | ~80       |
| Medium | ~150      |
| Fast   | ~200      |
| Max    | 255       |

## Telemetry Monitor

- Start: `python3 ~/code/rover/monitor/rover_monitor.py`
- Connects to `/tmp/rover-telemetry.sock` (created by the plugin)
- Shows live motor state, vitals, command history
