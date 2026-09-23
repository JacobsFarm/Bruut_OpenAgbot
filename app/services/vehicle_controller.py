import time
import math
import logging
import threading

# Importeer de hardware-modules (pas de paden aan als jouw mappenstructuur iets anders heet)
from app.hardware.motor_logic import MotorController
from app.hardware.stepper_logic import StepperSteering

class VehicleController:
    """
    De 'Spieren' van de AgBot: twee gestuurde voorwielen (stappenmotoren,
    Ackermann) en twee aangedreven achterwielen (VESC's over CAN).

    Een regellus op 50 Hz maakt van de gevraagde snelheid en stuurhoek een
    eRPM per achterwiel:

      * Elektronisch differentieel, exact uit de stuurgeometrie. Een VESC houdt
        zijn toerental vast in plaats van een gashendel te volgen. Krijgen beide
        wielen in een bocht hetzelfde toerental, dan vechten ze via de grond
        tegen elkaar: schuren, extra stroom, en de neus duwt de bocht uit.
      * Optrekken en afremmen gebeurt op de snelheid van het midden van de
        achteras, met één factor voor beide wielen. Zo blijft de verhouding
        tussen de wielen - de bocht - ook tijdens het optrekken kloppen.
      * Wat niet kan, lossen we op door beide wielen samen te schalen: onder
        min_erpm draait een wiel niet en boven max_erpm mag het niet. De bocht
        blijft gelijk, de snelheid past zich aan.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # 1. Hardware Initialisatie
        self.motor_controller = MotorController(config)
        self.stepper_steering = StepperSteering(config)

        # 2. Voertuig Afmetingen
        vehicle_cfg = config.get("vehicle", {})
        self.wheelbase = vehicle_cfg.get("wheelbase_m", 1.2)
        self.track_width = vehicle_cfg.get("track_width_m", 1.0)
        self.max_steer_angle = config.get("steering", {}).get("max_angle_degrees", 45.0)

        # max_angle_degrees is de limiet van een WIEL. Het binnenste wiel staat
        # bij Ackermann altijd scherper dan het virtuele midden, dus de grootste
        # bruikbare middenhoek ligt lager. Zonder deze afleiding zou het
        # binnenwiel afgekapt worden en klopt de Ackermann-verhouding niet meer.
        self.max_center_angle = self._max_center_angle()

        # 3. Rijgedrag. differential_gain 1.0 = exact volgens de geometrie,
        #    0.0 = beide achterwielen gekoppeld op hetzelfde toerental.
        self.differential_gain = min(2.0, max(0.0, vehicle_cfg.get("differential_gain", 1.0)))
        self.accel_mps2 = vehicle_cfg.get("accel_mps2", 0.5)
        self.decel_mps2 = vehicle_cfg.get("decel_mps2", 0.8)
        # Dodemansknop voor handbediening, zie drive().
        self.manual_timeout_s = vehicle_cfg.get("manual_timeout_s", 1.5)

        # 4. Doel (gezet door drive()) en wat de regellus nu werkelijk vraagt,
        #    beide als snelheid van het midden van de achteras in m/s. Het doel
        #    is één tuple, zodat de regellus nooit een half bijgewerkt doel leest.
        self._target = (0.0, 0.0, None)   # (m/s, middenhoek in graden, deadline)
        self._speed = 0.0
        self._lock = threading.Lock()

        # 5. Start de regellus
        self.running = True
        self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
        self.control_thread.start()

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

    def drive(self, speed_kmh, angle_degrees, allow_reverse=False, timeout_s=None):
        """
        Het hoofdcommando voor navigatie en handmatige besturing.

        speed_kmh is de snelheid van het midden van de achteras. Negatief is
        achteruit en wordt alleen uitgevoerd met allow_reverse=True: handmatig
        rijden mag achteruit, de navigators rijden uitsluitend vooruit.

        timeout_s maakt er een dodemansknop van: komt er binnen die tijd geen
        nieuw commando, dan remt hij af tot stilstand. De handbediening geeft
        die mee (wifi weg, telefoon op slot); de navigators sturen tien keer
        per seconde en hebben hem niet nodig.
        """
        # 0. Begrens de gevraagde middenhoek. Doen we dit niet, dan kapt de
        #    stuurmodule straks alleen het binnenwiel af en staan de twee
        #    voorwielen niet meer in de juiste Ackermann-verhouding.
        angle_degrees = max(-self.max_center_angle, min(self.max_center_angle, angle_degrees))

        # 1. Stuur de twee voorwielen aan, elk onder zijn eigen Ackermann-hoek
        hoek_links, hoek_rechts = self._calculate_ackermann_steering(angle_degrees)
        self.stepper_steering.set_angles(hoek_links, hoek_rechts)

        # 2. Snelheid vastleggen; de regellus rampt ernaartoe.
        if speed_kmh < 0 and not allow_reverse:
            speed_kmh = 0.0
        if abs(speed_kmh) < 0.1:
            speed_kmh = 0.0
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        self._target = (speed_kmh / 3.6, angle_degrees, deadline)

        self.logger.debug(
            f"Stuur: {angle_degrees:.1f}° (wiel L:{hoek_links:.1f}° R:{hoek_rechts:.1f}°) | "
            f"Doel: {speed_kmh:.2f} km/h"
        )

    def stop(self):
        """Noodstop: Direct stoppen, negeer de vloeiende overgang."""
        with self._lock:
            self._target = (0.0, self._target[1], None)
            self._speed = 0.0
            self.motor_controller.stop()
        self.logger.warning("VOERTUIG NOODSTOP GEACTIVEERD.")

    @property
    def drive_fault(self):
        """Waarom de aandrijving niet rijdt (CAN weg, VESC-fout, stall), of None."""
        return self.motor_controller.fault

    def reset_drive_faults(self):
        """Vrijgeven na een stall of oververhitting. Hij blijft staan tot het volgende commando."""
        with self._lock:
            self._target = (0.0, self._target[1], None)
            self._speed = 0.0
            self.motor_controller.reset_faults()

    def _turning_radius(self, angle_degrees):
        """
        Draaistraal van het midden van de ACHTERAS (fietsmodel): het draaipunt
        ligt op het verlengde van de achteras.

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

    def _wheel_factors(self, angle_degrees):
        """
        Snelheid van elk achterwiel als factor van het midden van de achteras.

        Het binnenwiel loopt een cirkel met straal R - spoor/2, het buitenwiel
        R + spoor/2, met R = wielbasis / tan(middenhoek):
            v_links  = v * (1 + spoor / 2R)
            v_rechts = v * (1 - spoor / 2R)
        Positieve hoek = bocht naar rechts, dan loopt rechts binnen. Dezelfde
        factoren gelden achteruit. differential_gain schaalt het verschil.
        """
        kromming = math.tan(math.radians(angle_degrees)) / self.wheelbase  # 1/R
        half = self.differential_gain * kromming * self.track_width / 2.0
        return max(0.0, 1.0 + half), max(0.0, 1.0 - half)

    def _center_speed_range(self, target, factor_links, factor_rechts):
        """
        Kleinste en grootste snelheid van het midden van de achteras (m/s)
        waarbij BEIDE wielen tussen min_erpm en max_erpm blijven. Beide wielen
        schalen met dezelfde factor mee, dus de bocht verandert daarbij niet.
        """
        motors = self.motor_controller
        max_erpm = motors.max_erpm if target >= 0 else motors.max_erpm_reverse
        hoog, laag = max(factor_links, factor_rechts), min(factor_links, factor_rechts)
        v_max = max_erpm / motors.erpm_per_mps / hoog
        v_min = motors.min_erpm / motors.erpm_per_mps / laag if laag > 0 else v_max
        return min(v_min, v_max), v_max

    @staticmethod
    def _step(value, target, max_step):
        if abs(target - value) <= max_step:
            return target
        return value + math.copysign(max_step, target - value)

    def _forget(self, snapshot):
        """Doel naar stilstand, tenzij drive() intussen al een nieuw doel neerzette."""
        if self._target is snapshot:
            self._target = (0.0, snapshot[1], None)

    def _control_step(self, dt):
        motors = self.motor_controller
        snapshot = self._target
        target, angle, deadline = snapshot

        # Geblokkeerd (verbinding weg, VESC-fout, vastgelopen wiel): stilstaan
        # en het doel vergeten. Na herstel rijdt hij pas weer op een nieuw
        # commando, niet vanzelf op het laatste.
        if motors.fault is not None:
            self._speed = 0.0
            self._forget(snapshot)
            motors.command(0, 0, dt)
            return

        # Dodemansknop: de handbediening is stil gevallen.
        if deadline is not None and time.monotonic() > deadline:
            self.logger.warning("Handbediening: geen commando meer ontvangen, afremmen tot stilstand.")
            self._forget(snapshot)
            target = 0.0

        factor_links, factor_rechts = self._wheel_factors(angle)
        v_min, v_max = self._center_speed_range(target, factor_links, factor_rechts)
        if target != 0.0:
            target = math.copysign(min(max(abs(target), v_min), v_max), target)

        speed = self._speed
        if speed != 0.0 and (target == 0.0 or (speed > 0) != (target > 0)):
            # Stoppen of van richting wisselen: eerst afremmen. Onder de dode
            # zone valt hij in één keer stil; die snelheden bestaan niet.
            speed = self._step(speed, 0.0, self.decel_mps2 * dt)
            if abs(speed) < v_min:
                speed = 0.0
        elif speed == 0.0 and target != 0.0:
            # Wegrijden: in één keer over de dode zone naar de laagste snelheid.
            speed = math.copysign(v_min, target)
        elif target != 0.0:
            rate = self.accel_mps2 if abs(target) > abs(speed) else self.decel_mps2
            speed = self._step(speed, target, rate * dt)
            # Is de bocht intussen veranderd, dan binnen het haalbare blijven.
            speed = math.copysign(min(max(abs(speed), v_min), v_max), speed)
        self._speed = speed

        motors.command(speed * factor_links * motors.erpm_per_mps,
                       speed * factor_rechts * motors.erpm_per_mps, dt)

    def _control_loop(self):
        """
        Achtergrondproces (thread) op send_rate_hz. Zendt ook bij stilstand:
        die frames zijn de levenslijn van de VESC's. Sterft deze lus, dan
        stoppen de frames en zetten beide VESC's zichzelf uit na hun timeout.
        """
        interval = 1.0 / self.motor_controller.rate_hz
        last = time.monotonic()
        last_error_log = 0.0
        while self.running:
            start = time.monotonic()
            dt, last = min(start - last, 0.2), start
            try:
                with self._lock:
                    self._control_step(dt)
            except Exception as e:
                # Doorlopen, maar de log niet elke 20 ms vullen.
                if start - last_error_log > 5.0:
                    last_error_log = start
                    self.logger.exception(f"Fout in de regellus: {e}")
            time.sleep(max(0.001, interval - (time.monotonic() - start)))

    def status(self):
        """Alle aandrijfdata voor /api/motors: VESC-telemetrie plus de rijopdracht."""
        status = self.motor_controller.status()
        target, angle, deadline = self._target
        factor_links, factor_rechts = self._wheel_factors(angle)
        status["drive"] = {
            "target_kmh": round(target * 3.6, 2),
            "speed_kmh": round(self._speed * 3.6, 2),
            "angle_degrees": round(angle, 2),
            "wheel_factor": {"left": round(factor_links, 3), "right": round(factor_rechts, 3)},
            "differential_gain": self.differential_gain,
            "accel_mps2": self.accel_mps2,
            "decel_mps2": self.decel_mps2,
            "manual_timeout_s": self.manual_timeout_s,
            "deadman_active": deadline is not None,
        }
        return status

    def log_snapshot(self):
        """Aandrijfkolommen voor de ritlog."""
        return self.motor_controller.log_snapshot()

    def shutdown(self):
        """Veilig afsluiten van de regellus, de CAN-bus en de stuur-Arduino."""
        self.stop()
        self.running = False
        if self.control_thread.is_alive():
            self.control_thread.join(timeout=1.0)
        self.motor_controller.close()
        self.stepper_steering.close()
