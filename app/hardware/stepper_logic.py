import serial
import time
import logging

class StepperSteering:
    """
    Klasse voor de aansturing van het zwenkwiel via een Arduino.
    Communiceert via een simpele seriële verbinding.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)
        
        # Lees poort en baudrate uit de config
        hardware_config = config.get("hardware", {})
        self.port = hardware_config.get("arduino_stepper_port", "/dev/ttyACM3")
        self.baudrate = hardware_config.get("arduino_stepper_baudrate", 9600)
        
        # Lees limieten uit de config
        steering_config = config.get("steering", {})
        self.max_angle = steering_config.get("max_angle_degrees", 45.0)
        
        # --- SOFTWARE INVERT ---
        # Haalt de instelling uit config.json. Als hij er niet in staat, is hij standaard False.
        self.invert_direction = steering_config.get("invert_direction", False)

        self.serial_conn = None

        try:
            # timeout=1 zorgt ervoor dat het script niet blijft hangen als er geen antwoord komt
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)  # Geef de Arduino de tijd om te herstarten
            self.logger.info(f"Verbonden met Arduino Stuur-Controller op {self.port}")
        except serial.SerialException as e:
            self.logger.error(f"Kan geen verbinding maken met stuur-Arduino op {self.port}: {e}")

    def _send_command(self, command):
        """Interne functie om veilig commando's te versturen."""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(f"{command}\n".encode('utf-8'))
            except Exception as e:
                self.logger.error(f"Fout bij verzenden commando '{command}': {e}")
        else:
            self.logger.warning(f"Kan commando '{command}' niet sturen: Seriële verbinding is dicht.")

    def set_angle(self, angle):
        """
        Stuur het wiel naar een specifieke hoek met softwarematige limieten.
        """
        # DRAAI DE HOEK OM ALS INVERT AAN STAAT IN DE CONFIG
        if self.invert_direction:
            angle = -angle

        # Beveiliging: beperk de maximale uitslag van het wiel
        if angle > self.max_angle:
            angle = self.max_angle
            self.logger.warning(f"Gevraagde hoek te groot. Beperkt tot {self.max_angle} graden.")
        elif angle < -self.max_angle:
            angle = -self.max_angle
            self.logger.warning(f"Gevraagde hoek te klein. Beperkt tot -{self.max_angle} graden.")

        self._send_command(f"A:{angle}")
        self.logger.debug(f"Stuurhoek ingesteld op: {angle} graden")

    def enable(self):
        """Zet de motor vast (houdt positie)."""
        self._send_command("E:1")
        self.logger.info("Stuurmotor is VASTGEZET (Enabled)")

    def disable(self):
        """Zet de motor in de vrijloop (kan met de hand gedraaid worden)."""
        self._send_command("E:0")
        self.logger.info("Stuurmotor is VRIJGEZET (Disabled)")

    def set_zero(self):
        """Stel de huidige positie in als het nieuwe nulpunt (rechtuit)."""
        self._send_command("Z:0")
        self.logger.info("Nulpunt stuurmotor opnieuw gekalibreerd (0 graden)")

    def get_position(self):
        """Vraag de huidige positie op aan de Arduino."""
        self._send_command("P:?")
        
        if self.serial_conn and self.serial_conn.is_open:
            try:
                response = self.serial_conn.readline().decode('utf-8').strip()
                if response.startswith("Positie:"):
                    current_angle = float(response.split(":")[1])
                    
                    # Als we hem omgekeerd hebben gestuurd, draaien we hem bij het uitlezen weer terug
                    # zodat de frontend UI gewoon de juiste hoek (links/rechts) laat zien.
                    if self.invert_direction:
                        current_angle = -current_angle
                        
                    return current_angle
            except Exception as e:
                self.logger.error(f"Fout bij lezen van positie: {e}")
                
        return None

    def close(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.logger.info("Seriële verbinding met stuur-Arduino gesloten.")