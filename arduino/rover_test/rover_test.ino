// TB6612FNG integration test — forward/reverse loop
// No serial communication yet. Motors only.

// Pin mapping (Arduino Nano → TB6612FNG)
// Motor A = Left motor
const int PWMA = 6;   // Motor A speed (PWM)
const int AIN2 = 7;   // Motor A direction 2
const int AIN1 = 8;   // Motor A direction 1

// Motor B = Right motor
const int BIN1 = 9;   // Motor B direction 1
const int BIN2 = 10;  // Motor B direction 2
const int PWMB = 11;  // Motor B speed (PWM)

// Standby — must be HIGH to enable driver
const int STBY = 12;

void setup() {
  pinMode(PWMA, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(PWMB, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(STBY, OUTPUT);

  digitalWrite(STBY, HIGH);  // enable driver
  analogWrite(PWMA, 0);      // motors off
  analogWrite(PWMB, 0);
}

void loop() {
  // forward
  digitalWrite(AIN1, HIGH);
  digitalWrite(AIN2, LOW);
  digitalWrite(BIN1, HIGH);
  digitalWrite(BIN2, LOW);
  analogWrite(PWMA, 180);
  analogWrite(PWMB, 180);
  delay(1500);

  // stop
  analogWrite(PWMA, 0);
  analogWrite(PWMB, 0);
  delay(500);

  // reverse
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, HIGH);
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, HIGH);
  analogWrite(PWMA, 180);
  analogWrite(PWMB, 180);
  delay(1500);

  // stop
  analogWrite(PWMA, 0);
  analogWrite(PWMB, 0);
  delay(1000);
}
