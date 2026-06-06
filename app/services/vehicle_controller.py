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
        
        self.logger.info("VehicleController succesvol opgestart gekoppeld aan config.json.")

    def drive(self, speed_kmh, angle_degrees):
        """
        Het hoofdcommando voor navigatie en handmatige besturing.
        Zet snelheid en hoek om in veilige, gecorrigeerde motorsignalen.
        """
        # 1. Stuur zwenkwiel aan
        self.stepper_steering.set_angle(angle_degrees)
        
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
            f"Stuur: {angle_degrees:.1f}° | Verschil: {int(dac_diff)} DAC | "
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

    def _calculate_differential(self, speed_mps, angle_degrees):
        """
        Berekent wielsnelheden gebaseerd op Ackermann besturing.
        Voorkomt ook dat de wiskunde probeert om wielen in z'n achteruit te zetten.
        """
        if abs(angle_degrees) < 1.0:
            return speed_mps, speed_mps # Rijden in een rechte lijn
            
        angle_rad = math.radians(angle_degrees)
        turning_radius = self.wheelbase / math.tan(angle_rad)
        
        # Bereken snelheid per wiel gebaseerd op de draaicirkel
        v_links = speed_mps * (1 - (self.track_width / (2 * turning_radius)))
        v_rechts = speed_mps * (1 + (self.track_width / (2 * turning_radius)))

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