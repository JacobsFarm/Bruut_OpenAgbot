import time
import math
import logging
import threading

# Importeer de hardware-modules (pas de paden aan als jouw mappenstructuur iets anders heet)
from app.hardware.motor_logic import MotorController
from app.hardware.stepper_logic import StepperSteering

class VehicleController:
    """
    De 'Spieren' van de AgBot. 
    Regelt acceleratie-smoothing, elektronisch differentieel gebaseerd op DAC-waarden,
    en beschermt de hubmotoren tegen stalling (stilstaan) en extreme slip.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)
        
        # 1. Hardware Initialisatie
        self.motor_controller = MotorController(
            port=config.get("hardware", {}).get("arduino_dac_port", "/dev/ttyACM2"),
            baudrate=config.get("hardware", {}).get("arduino_dac_baudrate", 115200)
        )
        self.stepper_steering = StepperSteering(config)
        
        # 2. Voertuig Afmetingen
        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)      
        self.track_width = config.get("vehicle", {}).get("track_width_m", 1.0)  
        self.max_wheel_diff_dac = config.get("vehicle", {}).get("max_wheel_diff_dac", 1000.0)
        self.max_steer_angle = config.get("steering", {}).get("max_angle_degrees", 45.0)

        # max_angle_degrees is de limiet van een WIEL. Het binnenste wiel staat
        # bij Ackermann altijd scherper dan het virtuele midden, dus de grootste
        # bruikbare middenhoek ligt lager. Zonder deze afleiding zou het
        # binnenwiel afgekapt worden en klopt de Ackermann-verhouding niet meer.
        self.max_center_angle = self._max_center_angle()

        # 3. Motor Controle & Limieten (NU GEKOPPELD AAN CONFIG.JSON!)
        motor_cfg = config.get("motor_control", {})
        self.dac_stop = motor_cfg.get("dac_stop", 700.0)
        self.dac_min_start = motor_cfg.get("dac_min_start", 1200.0)
        self.dac_max = motor_cfg.get("dac_max", 3100.0)
        
        # 4. DAC Smoothing Variabelen
        self.current_dac_links = self.dac_stop
        self.current_dac_rechts = self.dac_stop
        self.target_dac_links = self.dac_stop
        self.target_dac_rechts = self.dac_stop
        
        self.max_dac_step_per_sec = motor_cfg.get("max_dac_step_per_sec", 800.0) 
        self.smoothing_interval = motor_cfg.get("smoothing_interval_sec", 0.05)
        
        # 5. Start de achtergrond-thread
        self.running = True
        self.smoothing_thread = threading.Thread(target=self._smoothing_loop, daemon=True)
        self.smoothing_thread.start()
        
        self.logger.info(
            f"VehicleController succesvol opgestart gekoppeld aan config.json. "
            f"Wiellimiet {self.max_steer_angle:.1f}° komt neer op maximaal "
            f"{self.max_center_angle:.1f}° middenhoek."
        )

    def _max_center_angle(self):
        """
        Grootste stuurhoek van het virtuele midden waarbij het binnenste
        voorwiel nog net binnen max_steer_angle blijft.
        """
        tangens = math.tan(math.radians(self.max_steer_angle))
        if tangens <= 1e-6:
            return self.max_steer_angle
        radius = self.wheelbase / tangens + (self.track_width / 2.0)
        return math.degrees(math.atan(self.wheelbase / radius))

    def drive(self, speed_kmh, angle_degrees):
        """
        Het hoofdcommando voor navigatie en handmatige besturing.
        Zet snelheid en hoek om in veilige, gecorrigeerde motorsignalen.
        """
        # 0. Begrens de gevraagde middenhoek. Doen we dit niet, dan kapt de
        #    stuurmodule straks alleen het binnenwiel af en staan de twee
        #    voorwielen niet meer in de juiste Ackermann-verhouding.
        angle_degrees = max(-self.max_center_angle, min(self.max_center_angle, angle_degrees))

        # 1. Stuur de twee voorwielen aan, elk onder zijn eigen Ackermann-hoek
        hoek_links, hoek_rechts = self._calculate_ackermann_steering(angle_degrees)
        self.stepper_steering.set_angles(hoek_links, hoek_rechts)

        # 2. Als we praktisch stilstaan, stuur direct STOP (rustwaarde 700)
        if abs(speed_kmh) < 0.1:
            self.target_dac_links = self.dac_stop
            self.target_dac_rechts = self.dac_stop
            return

        # 3. Reken doelsnelheid om naar meters per seconde (voor de pure wiskunde)
        speed_mps = speed_kmh / 3.6
        
        # 4. Bereken de pure, theoretische wielsnelheden via Ackermann
        v_links, v_rechts = self._calculate_differential(speed_mps, angle_degrees)
        
        # 5. Vertaal deze pure snelheden naar ruwe DAC-waarden
        dac_l = self._speed_to_raw_dac(v_links)
        dac_r = self._speed_to_raw_dac(v_rechts)
        
        # 6. BEGRENZ HET VERSCHIL (Slip & Wring Beveiliging)
        dac_diff = abs(dac_l - dac_r)
        if dac_diff > self.max_wheel_diff_dac:
            # Verdeel de overschrijding netjes over beide kanten rondom het gemiddelde
            correctie = (dac_diff - self.max_wheel_diff_dac) / 2.0
            if dac_l > dac_r:
                dac_l -= correctie
                dac_r += correctie
            else:
                dac_l += correctie
                dac_r -= correctie

        # 7. ANTI-STALL & HARDWARE LIMIETEN
        # Pas als allerlaatste stap zorgen we dat de motoren nooit onder 1200 of boven 3100 komen.
        self.target_dac_links = max(self.dac_min_start, min(self.dac_max, dac_l))
        self.target_dac_rechts = max(self.dac_min_start, min(self.dac_max, dac_r))
        
        self.logger.debug(
            f"Stuur: {angle_degrees:.1f}° (wiel L:{hoek_links:.1f}° R:{hoek_rechts:.1f}°) | "
            f"Verschil: {int(dac_diff)} DAC | "
            f"Output L: {int(self.target_dac_links)} R: {int(self.target_dac_rechts)}"
        )

    def stop(self):
        """Noodstop: Direct stoppen, negeer de vloeiende overgang."""
        self.target_dac_links = self.dac_stop
        self.target_dac_rechts = self.dac_stop
        self.current_dac_links = self.dac_stop
        self.current_dac_rechts = self.dac_stop
        self.motor_controller.stop()
        self.logger.warning("VOERTUIG NOODSTOP GEACTIVEERD.")

    def _turning_radius(self, angle_degrees):
        """
        Draaistraal vanaf het virtuele midden van de vooras (fietsmodel).

        Positief = bocht naar RECHTS, gemeten naar rechts vanaf het voertuig.
        Dat is de conventie van de hele rest van het systeem: de navigators
        rekenen alpha = doelpeiling - koers in kompasgraden (doel naar rechts
        geeft een positieve hoek) en de frontend labelt positief als 'Rechts'.

        Geeft None terug bij rechtuit rijden.
        """
        tangens = math.tan(math.radians(angle_degrees))
        if abs(tangens) < 1e-6:
            return None
        return self.wheelbase / tangens

    def _calculate_ackermann_steering(self, angle_degrees):
        """
        Zet de gevraagde stuurhoek van het virtuele midden om naar een aparte
        hoek per voorwiel.

        Het binnenste wiel draait een kleinere cirkel en moet dus scherper
        staan dan het buitenste. Krijgen beide wielen dezelfde hoek, dan
        vechten ze via de grond tegen elkaar: dat schuurt de banden en belast
        de tandwielkasten permanent.
        """
        radius = self._turning_radius(angle_degrees)
        if radius is None:
            return angle_degrees, angle_degrees  # rechtuit, beide wielen gelijk

        half_track = self.track_width / 2.0

        # Ligt het draaipunt binnen de spoorbreedte, dan klapt de meetkunde om
        # en zou het binnenwiel de andere kant op sturen. Met de standaardlimiet
        # kan dat niet gebeuren, maar we vangen het af in plaats van een
        # verkeerd teken door te laten.
        if abs(radius) <= half_track:
            limiet = math.copysign(self.max_steer_angle, angle_degrees)
            self.logger.warning(
                f"Draaistraal ({radius:.2f} m) valt binnen de spoorbreedte. "
                f"Stuuruitslag begrensd op {limiet:.1f}°."
            )
            return limiet, limiet

        # Positieve hoek = bocht naar rechts, dus dan is het RECHTER wiel het
        # binnenste en moet dat scherper staan. Bij een linkse bocht wordt de
        # straal negatief en draait de verhouding vanzelf om.
        hoek_rechts = math.degrees(math.atan(self.wheelbase / (radius - half_track)))
        hoek_links = math.degrees(math.atan(self.wheelbase / (radius + half_track)))
        return hoek_links, hoek_rechts

    def _calculate_differential(self, speed_mps, angle_degrees):
        """
        Berekent wielsnelheden gebaseerd op Ackermann besturing.
        Voorkomt ook dat de wiskunde probeert om wielen in z'n achteruit te zetten.
        """
        if abs(angle_degrees) < 1.0:
            return speed_mps, speed_mps # Rijden in een rechte lijn

        turning_radius = self._turning_radius(angle_degrees)
        if turning_radius is None:
            return speed_mps, speed_mps

        # Bereken snelheid per wiel gebaseerd op de draaicirkel. Positief =
        # bocht naar rechts, dus dan loopt het RECHTER wiel de kleinste cirkel
        # en moet dat langzamer draaien.
        v_rechts = speed_mps * (1 - (self.track_width / (2 * turning_radius)))
        v_links = speed_mps * (1 + (self.track_width / (2 * turning_radius)))

        # Anti-Achteruit: Omdat DAC in dit simpele systeem alleen 'vooruit' is,
        # dwingen we het binnenste wiel minimaal mee te rollen (0.05 m/s) in plaats van tegengas te geven.
        if v_links < 0.05: v_links = 0.05
        if v_rechts < 0.05: v_rechts = 0.05

        return v_links, v_rechts

    def _speed_to_raw_dac(self, target_speed_mps):
        """
        Zet m/s om in een pure theoretische DAC waarde. 
        (De fysieke limieten worden pas in de 'drive' functie toegepast).
        """
        if abs(target_speed_mps) < 0.01:
            return self.dac_stop
            
        # Formule (uit JSON tabel geëxtraheerd): DAC = (Speed + 0.96) / 0.001
        return (abs(target_speed_mps) + 0.96) * 1000

    def _smoothing_loop(self):
        """
        Achtergrondproces (thread).
        Zorgt voor vloeiende acceleratie en decelleratie om mechanische schade, 
        piekstromen en bokken te voorkomen.
        """
        while self.running:
            start_time = time.time()
            max_step = self.max_dac_step_per_sec * self.smoothing_interval
            
            # Linker wiel interpolatie
            diff_l = self.target_dac_links - self.current_dac_links
            if abs(diff_l) <= max_step:
                self.current_dac_links = self.target_dac_links
            else:
                self.current_dac_links += math.copysign(max_step, diff_l)
                
            # Rechter wiel interpolatie
            diff_r = self.target_dac_rechts - self.current_dac_rechts
            if abs(diff_r) <= max_step:
                self.current_dac_rechts = self.target_dac_rechts
            else:
                self.current_dac_rechts += math.copysign(max_step, diff_r)

            # Stuur actuele waarden naar de hardware (Arduino)
            self.motor_controller.stuur_motoren(int(self.current_dac_links), int(self.current_dac_rechts))
            
            # Wacht strak tot de volgende cyclus (bijv. 50ms)
            elapsed = time.time() - start_time
            sleep_time = max(0.001, self.smoothing_interval - elapsed)
            time.sleep(sleep_time)

    def shutdown(self):
        """Veilig afsluiten van threads en hardware-poorten."""
        self.running = False
        self.stop()
        if self.smoothing_thread.is_alive():
            self.smoothing_thread.join()
        self.stepper_steering.close()