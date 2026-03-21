# TODO

- [ ] Generalize async rover event notifier beyond obstacle only: publish and handle `OBSTACLE`, `WATCHDOG`, `RECOVERED`, and periodic `STATUS` updates via the rover agent/event bus (Telegram remains transport only).

## Outdoor Autonomous Driving — Future Rewiring Plan

When ready to add cellular modem, consider moving Arduino from USB to GPIO UART to free Pi Zero's USB port:

### Arduino Nano GPIO Rewiring (deferred)
- D0 (RX) ← Pi Zero GPIO 14 (TX) — serial data
- D1 (TX) → Pi Zero GPIO 15 (RX) — serial data
- 5V/GND from power bus (not USB)
- `roverctl.py` changes port from `/dev/ttyUSB0` to `/dev/serial0`
- Must disconnect D0/D1 wires to upload new firmware
- Must disable Pi Zero serial console via `raspi-config`
- Pi Zero USB port becomes free for cellular dongle

### Full Arduino Nano Pin Map (current + planned)
| Pin | Use | Device |
|-----|-----|--------|
| D0/D1 | USB serial (current), GPIO UART (future) | Pi Zero |
| D2/D3 | TRIG/ECHO | HC-SR04 ultrasonic |
| D4/D5 | free (reserve for future SoftwareSerial GPS if needed) | — |
| D6-D12 | Motor driver | TB6612FNG |
| D13 | free | — |
| A0-A3 | free | — |
| A4/A5 | I2C shared bus | MPU6050 gyro + HMC5883L compass |

### Power Bus (required for multi-sensor)
- Battery → 5V regulator → power bus (breadboard rail)
- Bus distributes 5V + GND to: Pi Zero, Arduino, ultrasonic, gyro, compass, GPS
- Eliminates single-pin power bottleneck on Arduino

## Shopping List — Outdoor Autonomous Driving

### Phase 1 (needed now)
- [ ] NEO-6M GPS module (~$8-12) — lat/lng positioning, connects to Pi Zero UART, comes with antenna
- [ ] HMC5883L or QMC5883L compass/magnetometer (~$3-5) — shares I2C bus with gyro on Arduino A4/A5
- [ ] 5V voltage regulator, e.g., LM7805 or buck converter (~$3-5) — battery input, 5V output to power bus
- [ ] Small breadboard or terminal strip (~$2-3) — power distribution bus for 5V + GND
- [ ] Jumper wires, female-to-female + female-to-male (~$3-5) — if not enough on hand

### Already owned or on existing shopping list
- Solderless 40-pin hammer header (owned)
- HC-SR04 ultrasonic sensor (on existing list)
- GY-521 MPU6050 gyroscope (on existing list)

### Phase 2 (deferred)
- [ ] USB hub (~$5) — needed when adding cellular dongle
- [ ] Cellular SIM module (e.g., SIM7600 USB dongle) — replace phone hotspot with dedicated cellular
- [ ] Bigger wheels/motors for outdoor terrain — keep existing TB6612FNG driver if possible
