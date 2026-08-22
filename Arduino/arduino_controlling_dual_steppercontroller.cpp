/*
 * OpenAgbot - Stuurcontroller voor TWEE gestuurde voorwielen
 * -----------------------------------------------------------
 * Board   : Arduino UNO R4 Minima
 * Drivers : 2x HBS86H (closed loop) + NEMA 34 met 5:1 tandwielkast
 * Pinnen  : zie setup/information/steppermotor_information.json
 *
 * Bedrading per driver: PUL+/DIR+/ENA+ op de Arduino pin,
 * PUL-/DIR-/ENA- van BEIDE drivers samen op Arduino GND.
 * De 48V-min blijft gescheiden (de driver-ingangen zijn opto-geisoleerd).
 *
 * D0/D1 blijven bewust vrij: dat is Serial1 (UART), handig voor debug.
 * De Jetson praat via USB, dat is de aparte `Serial` poort.
 *
 * Alle communicatie is regelgebaseerd ASCII. Elk commando geeft precies een
 * antwoordregel terug, zodat de Python-kant altijd kan synchroniseren.
 * Het volledige protocol staat in steppermotor_information.json.
 */

#include <Arduino.h>

// ---------------------------------------------------------------------------
// Pinnen
// ---------------------------------------------------------------------------
#define LEFT_PUL_PIN   2
#define LEFT_DIR_PIN   3
#define LEFT_ENA_PIN   4

#define RIGHT_PUL_PIN  5
#define RIGHT_DIR_PIN  6
#define RIGHT_ENA_PIN  7

// ---------------------------------------------------------------------------
// Mechanische constanten
// ---------------------------------------------------------------------------
const float STEPS_PER_REV    = 3200.0;                               // microstappen per motoromwenteling
const float GEAR_RATIO       = 5.0;                                  // tandwielkast
const float STEPS_PER_DEGREE = (STEPS_PER_REV * GEAR_RATIO) / 360.0; // 44.444 stappen per graad

// Timing die de HBS86H nodig heeft
const unsigned int PULSE_WIDTH_US = 5;  // breedte van de PUL puls
const unsigned int DIR_SETUP_US   = 5;  // rusttijd na een richtingswissel, voor de eerstvolgende puls

// ---------------------------------------------------------------------------
// Instelbaar via serieel (V: en M:)
// ---------------------------------------------------------------------------
unsigned long minStepDelayUs   = 300;   // hoogste snelheid. Lager = sneller (kijk uit i.v.m. stallen)
unsigned long startStepDelayUs = 1200;  // startsnelheid van de acceleratieramp
long          rampSteps        = 400;   // aantal stappen om op te trekken / af te remmen (0 = geen ramp)
float         maxAngleDeg      = 50.0;  // softwarelimiet op de stuuruitslag, gelijk aan config.json

// ---------------------------------------------------------------------------
// Motorstructuur
// ---------------------------------------------------------------------------
struct Stepper {
  uint8_t       pulPin;
  uint8_t       dirPin;
  uint8_t       enaPin;
  long          currentSteps;
  long          targetSteps;
  unsigned long lastStepMicros;
  long          stepsIntoMove;   // teller voor de acceleratieramp
  int8_t        lastDir;         // -1, 0 of +1; 0 betekent nog niet gezet
  bool          enabled;
};

const uint8_t MOTOR_COUNT = 2;
const uint8_t LEFT  = 0;
const uint8_t RIGHT = 1;

Stepper motors[MOTOR_COUNT] = {
  { LEFT_PUL_PIN,  LEFT_DIR_PIN,  LEFT_ENA_PIN,  0, 0, 0, 0, 0, true },  // index 0 = linker voorwiel
  { RIGHT_PUL_PIN, RIGHT_DIR_PIN, RIGHT_ENA_PIN, 0, 0, 0, 0, 0, true }   // index 1 = rechter voorwiel
};

// ---------------------------------------------------------------------------
// Seriele regelbuffer
// ---------------------------------------------------------------------------
char    lineBuf[80];
uint8_t lineLen      = 0;
bool    lineOverflow = false;

// ---------------------------------------------------------------------------
// Hulpfuncties
// ---------------------------------------------------------------------------
long degreesToSteps(float degrees) {
  return (long)lround(degrees * STEPS_PER_DEGREE);
}

float stepsToDegrees(long steps) {
  return (float)steps / STEPS_PER_DEGREE;
}

void setEnabled(Stepper &m, bool on) {
  // Bij de HBS86H betekent LOW op ENA dat de driver AAN staat (as vastgehouden).
  digitalWrite(m.enaPin, on ? LOW : HIGH);
  m.enabled = on;
  if (on) {
    // Voorkom dat de motor bij het vastzetten alsnog naar een oud doel schiet:
    // na handmatig verdraaien klopt die oude target niet meer.
    m.targetSteps    = m.currentSteps;
    m.stepsIntoMove  = 0;
    m.lastStepMicros = micros();
  }
}

// Zet een doelhoek. Geeft true terug als de hoek door de limiet is bijgesneden.
bool setTargetDegrees(Stepper &m, float degrees) {
  bool clamped = false;
  if (degrees > maxAngleDeg)       { degrees = maxAngleDeg;  clamped = true; }
  else if (degrees < -maxAngleDeg) { degrees = -maxAngleDeg; clamped = true; }
  m.targetSteps = degreesToSteps(degrees);
  return clamped;
}

void zeroMotor(Stepper &m) {
  m.currentSteps  = 0;
  m.targetSteps   = 0;
  m.stepsIntoMove = 0;
}

// Huidige stapinterval, inclusief lineaire optrek- en afremramp.
unsigned long currentInterval(const Stepper &m) {
  if (rampSteps <= 0) return minStepDelayUs;

  long remaining = labs(m.targetSteps - m.currentSteps);
  // De ramp kijkt naar de kortste van twee: hoe ver we onderweg zijn (optrekken)
  // en hoe ver we nog moeten (afremmen).
  long phase = (m.stepsIntoMove < remaining) ? m.stepsIntoMove : remaining;
  if (phase >= rampSteps) return minStepDelayUs;

  long span = (long)startStepDelayUs - (long)minStepDelayUs;
  if (span <= 0) return minStepDelayUs;
  return (unsigned long)((long)startStepDelayUs - (span * phase) / rampSteps);
}

bool anyMotorMoving() {
  for (uint8_t i = 0; i < MOTOR_COUNT; i++) {
    if (motors[i].enabled && motors[i].currentSteps != motors[i].targetSteps) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Motoraansturing: beide motoren pulsen in dezelfde loop-iteratie, zodat de een
// niet op de ander hoeft te wachten.
// ---------------------------------------------------------------------------
void serviceMotors() {
  unsigned long now    = micros();
  bool          pulsed = false;

  for (uint8_t i = 0; i < MOTOR_COUNT; i++) {
    Stepper &m = motors[i];

    if (!m.enabled) continue;

    if (m.currentSteps == m.targetSteps) {
      m.stepsIntoMove = 0;   // klaar: een volgende beweging begint weer onderaan de ramp
      continue;
    }

    if ((unsigned long)(now - m.lastStepMicros) < currentInterval(m)) continue;

    int8_t dir = (m.currentSteps < m.targetSteps) ? 1 : -1;
    if (dir != m.lastDir) {
      digitalWrite(m.dirPin, dir > 0 ? HIGH : LOW);
      m.lastDir = dir;
      delayMicroseconds(DIR_SETUP_US); // DIR moet stabiel staan voor de PUL flank
    }

    digitalWrite(m.pulPin, HIGH);
    m.lastStepMicros = now;
    m.currentSteps  += dir;
    if (m.stepsIntoMove < 1000000L) m.stepsIntoMove++;
    pulsed = true;
  }

  if (pulsed) {
    delayMicroseconds(PULSE_WIDTH_US);
    for (uint8_t i = 0; i < MOTOR_COUNT; i++) digitalWrite(motors[i].pulPin, LOW);
  }
}

// ---------------------------------------------------------------------------
// Antwoorden
// ---------------------------------------------------------------------------
void printPositions() {
  Serial.print("POS:");
  Serial.print(stepsToDegrees(motors[LEFT].currentSteps), 2);
  Serial.print(",");
  Serial.println(stepsToDegrees(motors[RIGHT].currentSteps), 2);
}

void printStatus() {
  Serial.print("STA:POS=");
  Serial.print(stepsToDegrees(motors[LEFT].currentSteps), 2);
  Serial.print(",");
  Serial.print(stepsToDegrees(motors[RIGHT].currentSteps), 2);
  Serial.print(";TGT=");
  Serial.print(stepsToDegrees(motors[LEFT].targetSteps), 2);
  Serial.print(",");
  Serial.print(stepsToDegrees(motors[RIGHT].targetSteps), 2);
  Serial.print(";EN=");
  Serial.print(motors[LEFT].enabled ? 1 : 0);
  Serial.print(",");
  Serial.print(motors[RIGHT].enabled ? 1 : 0);
  Serial.print(";MOV=");
  Serial.print(anyMotorMoving() ? 1 : 0);
  Serial.print(";LIM=");
  Serial.print(maxAngleDeg, 2);
  Serial.print(";VMIN=");
  Serial.print(minStepDelayUs);
  Serial.print(";VSTART=");
  Serial.print(startStepDelayUs);
  Serial.print(";RAMP=");
  Serial.println(rampSteps);
}

void ackOk(const char* cmd, bool clamped = false) {
  Serial.print("OK:");
  Serial.print(cmd);
  if (clamped) Serial.print(";CLAMPED");
  Serial.println();
}

void ackErr(const char* reason) {
  Serial.print("ERR:");
  Serial.println(reason);
}

// ---------------------------------------------------------------------------
// Commando parsing
// ---------------------------------------------------------------------------
const uint8_t PARSE_ERROR = 0xFF;

// Splitst "1.5,-2.0" op in floats. Geeft PARSE_ERROR bij een ongeldig getal
// of bij meer waarden dan verwacht.
uint8_t parseFloats(char* arg, float* out, uint8_t maxCount) {
  uint8_t n   = 0;
  char*   tok = strtok(arg, ",");
  while (tok != NULL) {
    if (n >= maxCount) return PARSE_ERROR;
    char* end;
    float value = (float)strtod(tok, &end);
    if (end == tok) return PARSE_ERROR;
    out[n++] = value;
    tok = strtok(NULL, ",");
  }
  return n;
}

void processCommand(char* line) {
  // Splits op de dubbele punt
  char* colon = strchr(line, ':');
  if (colon == NULL) { ackErr("NO_COLON"); return; }
  *colon    = '\0';
  char* cmd = line;
  char* arg = colon + 1;

  // Commando naar hoofdletters, zodat "a:10" ook werkt
  for (char* p = cmd; *p; p++) *p = toupper(*p);

  float   values[3];
  uint8_t count;

  // ---- Stuurhoek zetten -------------------------------------------------
  if (strcmp(cmd, "A") == 0) {
    count = parseFloats(arg, values, 2);
    if (count == PARSE_ERROR || count == 0) { ackErr("A_BAD_ARG"); return; }
    bool clamped = setTargetDegrees(motors[LEFT], values[0]);
    // Een enkele waarde betekent: beide wielen dezelfde hoek.
    clamped |= setTargetDegrees(motors[RIGHT], (count == 2) ? values[1] : values[0]);
    ackOk("A", clamped);
    return;
  }
  if (strcmp(cmd, "AL") == 0 || strcmp(cmd, "AR") == 0) {
    count = parseFloats(arg, values, 1);
    if (count != 1) { ackErr("A_BAD_ARG"); return; }
    bool clamped = setTargetDegrees(motors[cmd[1] == 'L' ? LEFT : RIGHT], values[0]);
    ackOk(cmd, clamped);
    return;
  }

  // ---- Relatieve verplaatsing (jog, voor kalibratie) --------------------
  if (strcmp(cmd, "J") == 0) {
    count = parseFloats(arg, values, 2);
    if (count == PARSE_ERROR || count == 0) { ackErr("J_BAD_ARG"); return; }
    float dl = values[0];
    float dr = (count == 2) ? values[1] : values[0];
    bool clamped = setTargetDegrees(motors[LEFT],  stepsToDegrees(motors[LEFT].targetSteps)  + dl);
    clamped     |= setTargetDegrees(motors[RIGHT], stepsToDegrees(motors[RIGHT].targetSteps) + dr);
    ackOk("J", clamped);
    return;
  }

  // ---- Vast / vrij zetten ----------------------------------------------
  if (strcmp(cmd, "E") == 0 || strcmp(cmd, "EL") == 0 || strcmp(cmd, "ER") == 0) {
    count = parseFloats(arg, values, 1);
    if (count != 1) { ackErr("E_BAD_ARG"); return; }
    bool on = (values[0] != 0.0f);
    if (strcmp(cmd, "E") == 0) {
      setEnabled(motors[LEFT],  on);
      setEnabled(motors[RIGHT], on);
    } else {
      setEnabled(motors[cmd[1] == 'L' ? LEFT : RIGHT], on);
    }
    ackOk(cmd);
    return;
  }

  // ---- Nulpunt instellen ------------------------------------------------
  if (strcmp(cmd, "Z")  == 0) { zeroMotor(motors[LEFT]); zeroMotor(motors[RIGHT]); ackOk("Z");  return; }
  if (strcmp(cmd, "ZL") == 0) { zeroMotor(motors[LEFT]);                           ackOk("ZL"); return; }
  if (strcmp(cmd, "ZR") == 0) { zeroMotor(motors[RIGHT]);                          ackOk("ZR"); return; }

  // ---- Uitlezen ---------------------------------------------------------
  if (strcmp(cmd, "P") == 0) { printPositions(); return; }
  if (strcmp(cmd, "S") == 0) { printStatus();    return; }
  if (strcmp(cmd, "I") == 0) { Serial.println("ID:OPENAGBOT-STEER,2.0,MOTORS=2"); return; }

  // ---- Snelheid en acceleratieramp --------------------------------------
  if (strcmp(cmd, "V") == 0) {
    count = parseFloats(arg, values, 3);
    if (count == PARSE_ERROR || count == 0) { ackErr("V_BAD_ARG"); return; }
    if (values[0] < 20.0f || values[0] > 100000.0f) { ackErr("V_OUT_OF_RANGE"); return; }
    minStepDelayUs = (unsigned long)values[0];
    if (count >= 2) {
      if (values[1] < (float)minStepDelayUs) { ackErr("V_START_BELOW_MIN"); return; }
      startStepDelayUs = (unsigned long)values[1];
    }
    if (count >= 3) {
      if (values[2] < 0.0f) { ackErr("V_RAMP_NEGATIVE"); return; }
      rampSteps = (long)values[2];
    }
    if (startStepDelayUs < minStepDelayUs) startStepDelayUs = minStepDelayUs;
    ackOk("V");
    return;
  }

  // ---- Softwarelimiet op de stuuruitslag --------------------------------
  if (strcmp(cmd, "M") == 0) {
    count = parseFloats(arg, values, 1);
    if (count != 1) { ackErr("M_BAD_ARG"); return; }
    if (values[0] <= 0.0f || values[0] > 180.0f) { ackErr("M_OUT_OF_RANGE"); return; }
    maxAngleDeg = values[0];
    // Bestaande doelen opnieuw begrenzen, anders blijft een oud doel buiten de limiet staan.
    for (uint8_t i = 0; i < MOTOR_COUNT; i++) {
      setTargetDegrees(motors[i], stepsToDegrees(motors[i].targetSteps));
    }
    ackOk("M");
    return;
  }

  ackErr("UNKNOWN_CMD");
}

// ---------------------------------------------------------------------------
// Seriele invoer: niet-blokkerend regel voor regel inlezen.
// (readStringUntil() zou tot de timeout blijven hangen en de motoren stilzetten.)
// ---------------------------------------------------------------------------
void handleSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      if (lineOverflow) {
        ackErr("LINE_TOO_LONG");
      } else if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        processCommand(lineBuf);
      }
      lineLen      = 0;
      lineOverflow = false;
      return; // een commando per loop-iteratie, zodat de motoren blijven lopen
    }

    if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineOverflow = true;
    }
  }
}

// ---------------------------------------------------------------------------
void setup() {
  // Zelfde baudrate als de Jetson setup en als de DAC-Arduino. Op de R4 Minima
  // is Serial native USB CDC, dus dit getal wordt door de hardware genegeerd;
  // het staat er voor de consistentie en voor als je ooit naar Serial1 (D0/D1)
  // overstapt, waar het wel een echte UART-snelheid is.
  // Niet wachten op een host: de robot moet ook zonder laptop kunnen opstarten.
  Serial.begin(115200);

  for (uint8_t i = 0; i < MOTOR_COUNT; i++) {
    pinMode(motors[i].pulPin, OUTPUT);
    pinMode(motors[i].dirPin, OUTPUT);
    pinMode(motors[i].enaPin, OUTPUT);
    digitalWrite(motors[i].pulPin, LOW);
    digitalWrite(motors[i].dirPin, LOW);
    motors[i].lastDir        = 0;
    motors[i].lastStepMicros = micros();
    setEnabled(motors[i], true); // start met beide wielen vast op hun huidige stand
  }

  Serial.println("READY");
}

void loop() {
  handleSerial();  // luister naar de Jetson
  serviceMotors(); // stap beide motoren richting hun doelhoek
}
