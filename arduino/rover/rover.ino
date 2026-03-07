// Rover firmware — serial command parser with motor control
// Protocol: ASCII, newline-terminated, 9600 baud
// See docs/plans/2026-03-01-rover-brain-design.md
#include <Wire.h>

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

// Ultrasonic sensor (HC-SR04)
const int TRIG_PIN = 2;
const int ECHO_PIN = 3;

const int OBSTACLE_THRESHOLD_CM = 20;

// MPU6050 gyroscope
const int MPU_ADDR = 0x68;
const int SPIN_TO_SPEED = 120;
const unsigned long SPIN_TO_TIMEOUT = 5000;
const float HEADING_TOLERANCE = 3.0;

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

long distanceCm = 999;
bool obstacleBlocked = false;
unsigned long lastMeasureTime = 0;
const unsigned long MEASURE_INTERVAL = 60;  // ms between readings

float heading = 0.0;
float gyroZoffset = 0.0;
unsigned long lastGyroTime = 0;
bool spinToActive = false;
float spinToTarget = 0.0;
unsigned long spinToStart = 0;

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
  Serial.print(";dist=");
  Serial.print(distanceCm);
  Serial.print("cm;heading=");
  Serial.print((int)heading);
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

void initGyro() {
  Wire.begin();
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission();

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);
  Wire.write(0);
  Wire.endTransmission();

  delay(100);
  float sum = 0;
  for (int i = 0; i < 100; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x47);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, 2);
    int16_t raw = (Wire.read() << 8) | Wire.read();
    sum += raw;
    delay(2);
  }
  gyroZoffset = sum / 100.0;
  lastGyroTime = micros();
}

void updateHeading() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x47);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 2);
  int16_t raw = (Wire.read() << 8) | Wire.read();

  unsigned long now = micros();
  float dt = (now - lastGyroTime) / 1000000.0;
  lastGyroTime = now;

  float rate = (raw - gyroZoffset) / 131.0;
  heading += rate * dt;

  while (heading < 0) heading += 360.0;
  while (heading >= 360) heading -= 360.0;
}

void processSpinTo() {
  if (!spinToActive) return;

  if (millis() - spinToStart > SPIN_TO_TIMEOUT) {
    stopMotors();
    spinToActive = false;
    Serial.println("ERR:SPIN_TIMEOUT");
    return;
  }

  float diff = spinToTarget - heading;
  if (diff > 180) diff -= 360;
  if (diff < -180) diff += 360;

  if (abs(diff) <= HEADING_TOLERANCE) {
    stopMotors();
    spinToActive = false;
    Serial.println("OK");
    return;
  }

  if (diff > 0) {
    setMotors(SPIN_TO_SPEED, DIR_FORWARD, SPIN_TO_SPEED, DIR_REVERSE);
  } else {
    setMotors(SPIN_TO_SPEED, DIR_REVERSE, SPIN_TO_SPEED, DIR_FORWARD);
  }
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
  int arg = 0;
  if (space != NULL) {
    *space = '\0';
    arg = atoi(space + 1);
  }

  // Dispatch
  if (strcmp(cmd, "FORWARD") == 0) {
    if (obstacleBlocked) {
      Serial.println("ERR:OBSTACLE");
    } else {
      int speed = constrain(arg, 0, 255);
      setMotors(speed, DIR_FORWARD, speed, DIR_FORWARD);
      Serial.println("OK");
    }
  } else if (strcmp(cmd, "BACKWARD") == 0) {
    int speed = constrain(arg, 0, 255);
    setMotors(speed, DIR_REVERSE, speed, DIR_REVERSE);
    Serial.println("OK");
  } else if (strcmp(cmd, "LEFT") == 0) {
    int speed = constrain(arg, 0, 255);
    setMotors(0, DIR_STOP, speed, DIR_FORWARD);
    Serial.println("OK");
  } else if (strcmp(cmd, "RIGHT") == 0) {
    int speed = constrain(arg, 0, 255);
    setMotors(speed, DIR_FORWARD, 0, DIR_STOP);
    Serial.println("OK");
  } else if (strcmp(cmd, "SPIN_LEFT") == 0) {
    int speed = constrain(arg, 0, 255);
    setMotors(speed, DIR_REVERSE, speed, DIR_FORWARD);
    Serial.println("OK");
  } else if (strcmp(cmd, "SPIN_RIGHT") == 0) {
    int speed = constrain(arg, 0, 255);
    setMotors(speed, DIR_FORWARD, speed, DIR_REVERSE);
    Serial.println("OK");
  } else if (strcmp(cmd, "SPIN_TO") == 0) {
    spinToTarget = constrain(arg, 0, 359);
    spinToActive = true;
    spinToStart = millis();
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

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(STBY, HIGH);
  stopMotors();

  Serial.begin(9600);
  initGyro();
  lastCmdTime = millis();
  loopRateTime = millis();
}

// === Main loop (non-blocking) ===
void loop() {
  // 1. Watchdog check (skip during SPIN_TO)
  if (cmdCount > 0 && !watchdogFired && !spinToActive) {
    if (millis() - lastCmdTime > WATCHDOG_TIMEOUT) {
      stopMotors();
      Serial.println("STOPPED:WATCHDOG");
      watchdogFired = true;
    }
  }

  // 2. Ultrasonic distance check
  measureDistance();

  // 3. Gyroscope heading update
  updateHeading();

  // 4. SPIN_TO processing
  processSpinTo();

  // 5. Read serial byte-by-byte
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

  // 6. Loop rate tracking (update every second)
  loopCount++;
  if (millis() - loopRateTime >= 1000) {
    loopRate = loopCount;
    loopCount = 0;
    loopRateTime = millis();
  }
}
