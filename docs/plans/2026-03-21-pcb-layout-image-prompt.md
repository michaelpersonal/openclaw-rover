# PCB Layout Image Generation Prompt

Use this prompt with an image generation AI (e.g., DALL-E, Midjourney, Gemini) to produce a visual PCB layout of the outdoor autonomous rover.

---

Create a top-down PCB layout illustration showing all electronic components and their pin-to-pin connections for an autonomous rover. Use a clean, professional PCB design style with a dark green board background, copper-colored traces, and white silkscreen labels for component names and pin labels. No traces should cross over each other.

IMPORTANT: The Arduino Nano pinout must match the real hardware. All digital pins D2-D13 are on one side, all analog pins A0-A7 plus 5V/GND/VIN are on the other side.

Board layout (arranged to eliminate crossovers based on real pinouts):

Top edge — Power supply section (left to right):
- Battery pack (labeled "BATTERY 6-9V") with two terminals: (+) and (-)
- 5V Voltage Regulator (labeled "5V REG LM7805") with pins: IN, GND, OUT
- Power rails running horizontally across the board: a red 5V rail and a black GND rail

Far left — Brain section (top to bottom):
- Raspberry Pi Zero (labeled "Pi Zero") as a rectangular board outline showing these specific GPIO pins along its right edge from top to bottom: Pin 1 (3.3V), Pin 2 (5V), Pin 6 (GND), Pin 8 (GPIO14 TX), Pin 10 (GPIO15 RX). Show a USB-A port on its bottom edge. Include a small "USB" label with a dashed line going right toward the Arduino, labeled "USB CABLE (serial 9600 baud + power)"
- NEO-6M GPS module (labeled "NEO-6M GPS") positioned directly below Pi Zero, showing pins on its top edge: VCC, GND, TX, RX. Draw a small antenna icon on the module.

Center — Arduino Nano (positioned horizontally, USB connector facing left toward Pi Zero):
The Nano has two rows of pins. Match the REAL Arduino Nano pinout exactly:
- Top row of pins (left to right, USB end is left): TX(D1), RX(D0), RST, GND, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13
- Bottom row of pins (left to right, USB end is left): VIN, GND, RST, 5V, A7, A6, A5, A4, A3, A2, A1, A0, AREF, 3V3
- Show the USB Mini-B connector on the left edge

Above the Arduino (connecting to top-row pins) — two component groups:
- HC-SR04 ultrasonic sensor (labeled "HC-SR04 ULTRASONIC") positioned above pins D2/D3 area, showing pins on its bottom edge: VCC, TRIG, ECHO, GND
- TB6612FNG motor driver (labeled "TB6612FNG MOTOR DRIVER") positioned above pins D6-D12 area, showing input pins on its bottom edge: PWMA, AIN2, AIN1, BIN1, BIN2, PWMB, STBY, VCC, GND, VM. Show output pins on its top edge: AO1, AO2, BO1, BO2

Below the Arduino (connecting to bottom-row pins) — I2C sensor section:
- MPU6050 Gyroscope (labeled "MPU6050 GYRO addr:0x68") positioned below the A4/A5 area, showing pins on its top edge: VCC, GND, SCL, SDA
- HMC5883L Compass (labeled "HMC5883L COMPASS addr:0x1E") positioned next to MPU6050 (to its left), showing pins on its top edge: VCC, GND, SCL, SDA

Far right — Motors:
- Two DC motors (labeled "LEFT MOTOR" and "RIGHT MOTOR") positioned at far right, connected from TB6612FNG output pins

Data traces (blue lines, no crossovers):
- Arduino D2 (top row) → HC-SR04 TRIG (straight up)
- Arduino D3 (top row) → HC-SR04 ECHO (straight up)
- Arduino D6 (top row) → TB6612FNG PWMA (straight up)
- Arduino D7 (top row) → TB6612FNG AIN2 (straight up)
- Arduino D8 (top row) → TB6612FNG AIN1 (straight up)
- Arduino D9 (top row) → TB6612FNG BIN1 (straight up)
- Arduino D10 (top row) → TB6612FNG BIN2 (straight up)
- Arduino D11 (top row) → TB6612FNG PWMB (straight up)
- Arduino D12 (top row) → TB6612FNG STBY (straight up)
- Pi Zero Pin 8 (GPIO14 TX) → NEO-6M RX (straight down, short trace)
- Pi Zero Pin 10 (GPIO15 RX) → NEO-6M TX (straight down, short trace)

I2C bus traces (yellow lines, shared bus):
- Arduino A4/SDA (bottom row) → MPU6050 SDA → HMC5883L SDA (single shared trace going straight down, branching to both)
- Arduino A5/SCL (bottom row) → MPU6050 SCL → HMC5883L SCL (single shared trace going straight down, branching to both)

USB connection (dashed blue line):
- Pi Zero USB-A port → Arduino USB Mini-B port. Draw this as a dashed line with label "USB CABLE" to indicate it is a physical cable, not a PCB trace

Power traces (red lines):
- BATTERY (+) → REG IN
- REG OUT → 5V rail (horizontal red line across board)
- BATTERY (-) → REG GND → GND rail (horizontal black line across board)
- 5V rail drops down to: Pi Zero Pin 2, Arduino 5V (bottom row), HC-SR04 VCC, MPU6050 VCC, HMC5883L VCC, TB6612FNG VCC
- GND rail drops down to: Pi Zero Pin 6, Arduino GND (bottom row), HC-SR04 GND, MPU6050 GND, HMC5883L GND, TB6612FNG GND, NEO-6M GND
- Pi Zero Pin 1 (3.3V) → NEO-6M VCC (short trace, label "3.3V ONLY — do not use 5V")
- BATTERY (+) → TB6612FNG VM (separate red trace, label "MOTOR POWER — direct from battery")

Motor traces (green lines):
- TB6612FNG AO1 → Left Motor (+)
- TB6612FNG AO2 → Left Motor (-)
- TB6612FNG BO1 → Right Motor (+)
- TB6612FNG BO2 → Right Motor (-)

Style details:
- Dark green PCB background with rounded corners and mounting holes in all four corners
- Traces color-coded: red for power, blue for data, yellow for I2C, green for motor, dashed blue for cable
- Each component drawn as a white silkscreen outline rectangle with component name and a small icon inside (chip icon for ICs, antenna icon for GPS, speaker icon for ultrasonic, gear icon for motors)
- Pin labels in small white text at each connection point on the component outlines
- A legend box in the bottom-left corner showing: Red = Power, Blue = Data, Yellow = I2C Bus, Green = Motor, Dashed = Cable
- Title silkscreen in top-left: "ROVER AUTONOMOUS DRIVING — PCB LAYOUT v1"
- Board dimensions label in bottom-right corner: "150mm x 100mm"
- Mark pins D4, D5, D13, A0-A3 on the Arduino as "FREE" in small gray text
