// Pinnen gebaseerd op steppermotor_information.json
#define PUL_PIN 5
#define DIR_PIN 6
#define ENA_PIN 7

// Constanten voor berekeningen
const float STEPS_PER_REV = 3200.0;
const float GEAR_RATIO = 5.0;
const float STEPS_PER_DEGREE = (STEPS_PER_REV * GEAR_RATIO) / 360.0; // 44.444 stappen per graad

// Variabelen voor positie
long current_steps = 0;
long target_steps = 0;
bool motor_enabled = true;

// Timing voor non-blocking beweging
unsigned long previousMicros = 0;
long stepDelayUs = 300; // Snelheid van de motor. Lager = sneller (Kijk uit met te laag i.v.m. stallen)

void setup() {
  Serial.begin(9600); // Zelfde baudrate als de Jetson setup
  
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);

  enableMotor(); // Start met de motor vast/actief
  Serial.println("Arduino Stappenmotor Controller Gestart");
}

void loop() {
  handleSerial(); // Luister naar de Jetson
  moveMotor();    // Beweeg de motor als we nog niet op de target_steps zijn
}

void handleSerial() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim(); // Verwijder witregels

    if (command.startsWith("A:")) {
      // SET HOEK (Draaihoek)
      float target_angle = command.substring(2).toFloat();
      target_steps = round(target_angle * STEPS_PER_DEGREE);
    } 
    else if (command.startsWith("E:")) {
      // MOTOR VRIJZETTEN / VASTZETTEN
      int state = command.substring(2).toInt();
      if (state == 1) {
        enableMotor();
        Serial.println("Motor Vast (Enabled)");
      } else {
        disableMotor();
        Serial.println("Motor Vrij (Disabled)");
      }
    } 
    else if (command.startsWith("Z:")) {
      // NULPUNT INSTELLEN (Kalibratie)
      current_steps = 0;
      target_steps = 0;
      Serial.println("Nulpunt ingesteld (0 graden)");
    } 
    else if (command.startsWith("P:?")) {
      // HUIDIGE POSITIE OPVRAGEN
      float current_angle = current_steps / STEPS_PER_DEGREE;
      Serial.print("Positie:");
      Serial.println(current_angle);
    }
  }
}

void moveMotor() {
  if (!motor_enabled) return; // Doe niks als de motor in de 'vrij' stand staat

  if (current_steps != target_steps) {
    unsigned long currentMicros = micros();
    
    // Check of het tijd is voor de volgende stap (bepaalt de snelheid)
    if (currentMicros - previousMicros >= stepDelayUs) {
      previousMicros = currentMicros;

      // Bepaal richting
      if (current_steps < target_steps) {
        digitalWrite(DIR_PIN, HIGH);
        current_steps++;
      } else {
        digitalWrite(DIR_PIN, LOW);
        current_steps--;
      }

      // Geef de puls
      digitalWrite(PUL_PIN, HIGH);
      delayMicroseconds(5); // Korte puls voor de HBS86H driver
      digitalWrite(PUL_PIN, LOW);
    }
  }
}

void enableMotor() {
  // Bij de meeste closed-loop/industriële drivers betekent LOW (0V) dat hij AAN staat
  digitalWrite(ENA_PIN, LOW);
  motor_enabled = true;
}

void disableMotor() {
  // HIGH (5V) op de ENA pin zet de driver meestal in alarm/vrijloop modus
  digitalWrite(ENA_PIN, HIGH);
  motor_enabled = false;
}