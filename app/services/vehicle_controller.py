import time
import math
import logging
import threading

from app.hardware.motor_logic import MotorController
from app.hardware.throttle_map import ThrottleMap


class VehicleController:
    """
    De 'Spieren' van de AgBot: een SKID STEER aandrijving.

    De robot heeft twee aangedreven kanten (links en rechts, elk met eigen
    hubmotoren) en geen gestuurd wiel. Sturen = snelheidsverschil tussen die
    twee kanten. De hele besturing draait daarom om twee grootheden:

        v      = rijsnelheid van het midden van de robot (m/s)
        omega  = draaisnelheid om de verticale as (graden/s, + = rechtsom)

    en die vertalen we met de spoorbreedte W naar wielsnelheden:

        v_links  = v + omega_rad * W/2
        v_rechts = v - omega_rad * W/2

    Drie hardware-beperkingen bepalen de rest van deze klasse:

      1. VOORUIT-ONLY. De DAC-uitgang kent geen richting, dus een wielsnelheid
         mag nooit negatief worden. Echt op de plek tegengesteld draaien kan
         dus niet; de scherpste bocht is een pivot om het stilstaande
         binnenwiel (straal = W/2).
      2. DODE ZONE. Onder DAC 1200 (~0.24 m/s) draait een wiel niet. Een wiel
         staat dus óf stil, óf het rijdt minimaal 0.24 m/s.
      3. SLIP. Te grote of te plotselinge verschillen laten de banden schuiven
         en wringen aan de aandrijving. Vandaar de begrenzing op draaisnelheid
         en de gekoppelde acceleratie-begrenzer.

    Als een gevraagde combinatie niet haalbaar is, houden we de BOCHT (de
    verhouding tussen links en rechts) heilig en passen we de snelheid aan.
    Een te snel genomen bocht blijft dan wel de juiste lijn volgen; andersom
    zou de robot naast de lijn belanden.
    """

    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # 1. Hardware
        motor_cfg = config.get("motor_control", {})
        self.throttle = ThrottleMap(config)
        self.motor_controller = MotorController(
            port=config.get("hardware", {}).get("arduino_dac_port", "/dev/ttyACM3"),
            baudrate=config.get("hardware", {}).get("arduino_dac_baudrate", 115200),
            dac_stop=self.throttle.dac_stop,
            dac_max=self.throttle.dac_max,
            min_interval_sec=motor_cfg.get("smoothing_interval_sec", 0.05),
        )

        # 2. Voertuig-afmetingen (skid steer heeft alleen de spoorbreedte nodig)
        vehicle_cfg = config.get("vehicle", {})
        self.track_width = float(vehicle_cfg.get("track_width_m", 0.85))
        self.half_track = self.track_width / 2.0

        # Scherpste bocht die we willen toestaan. Fysiek kan de robot niet
        # scherper dan een pivot om het binnenwiel (W/2); daaronder zou hij
        # achteruit moeten kunnen.
        self.pivot_radius = self.half_track
        self.min_turn_radius = max(
            self.pivot_radius, float(vehicle_cfg.get("min_turn_radius_m", 0.85))
        )
        self.max_yaw_rate_dps = float(vehicle_cfg.get("max_yaw_rate_dps", 45.0))

        # 3. Snelheidsgrenzen uit de ingemeten tabel
        self.min_speed_mps = self.throttle.min_speed_mps      # laagste draaiende snelheid
        self.max_speed_mps = self.throttle.max_speed_mps
        # Onder deze gevraagde snelheid gaan we stilstaan in plaats van
        # optrekken naar de minimum-draaisnelheid.
        self.creep_threshold_mps = float(
            motor_cfg.get("creep_threshold_mps", self.min_speed_mps * 0.5)
        )

        # 4. Vloeiend maken (acceleratie-begrenzing in m/s², niet in DAC-stappen:
        #    zo is de instelling onafhankelijk van de motorkarakteristiek)
        self.max_accel_mps2 = float(motor_cfg.get("max_accel_mps2", 0.6))
        self.max_decel_mps2 = float(motor_cfg.get("max_decel_mps2", 1.5))
        self.smoothing_interval = float(motor_cfg.get("smoothing_interval_sec", 0.05))

        # 5. Veiligheids-watchdog: stopt de robot als er geen commando's meer
        #    binnenkomen (crash van de navigatie-thread, browser weg, wifi weg).
        #    0 = uit.
        self.command_timeout = float(motor_cfg.get("command_timeout_sec", 2.0))

        # 6. Toestand
        self._lock = threading.Lock()
        self.target_speed_links = 0.0
        self.target_speed_rechts = 0.0
        self.current_speed_links = 0.0
        self.current_speed_rechts = 0.0
        self.current_dac_links = self.throttle.dac_stop
        self.current_dac_rechts = self.throttle.dac_stop
        self.last_command_time = time.time()
        self.watchdog_tripped = False

        # Laatst gevraagde commando (puur voor status/log)
        self.command_speed_kmh = 0.0
        self.command_yaw_dps = 0.0

        self.running = True
        self.smoothing_thread = threading.Thread(target=self._smoothing_loop, daemon=True)
        self.smoothing_thread.start()

        self.logger.info(
            f"VehicleController (skid steer) gestart: spoorbreedte "
            f"{self.track_width:.2f} m, snelheid {self.min_speed_mps:.2f}-"
            f"{self.max_speed_mps:.2f} m/s, min. draaistraal "
            f"{self.min_turn_radius:.2f} m, max. draaisnelheid "
            f"{self.max_yaw_rate_dps:.0f} graden/s."
        )

    # ------------------------------------------------------------------ #
    #  Publieke API
    # ------------------------------------------------------------------ #
    def drive(self, speed_kmh, yaw_rate_dps):
        """
        Hoofdcommando: rijsnelheid (km/h) + draaisnelheid (graden/s, + = rechts).

        Draaisnelheid in plaats van een stuurhoek, want dat is wat een skid
        steer daadwerkelijk regelt. Het werkt bovendien gewoon door bij
        snelheid 0 (draaien op de plek), waar een stuurhoek betekenisloos is.
        """
        speed_mps = speed_kmh / 3.6
        yaw_dps = max(-self.max_yaw_rate_dps, min(self.max_yaw_rate_dps, yaw_rate_dps))

        v_links, v_rechts = self._wheel_speeds(speed_mps, math.radians(yaw_dps))
        v_links, v_rechts = self._fit_to_hardware(v_links, v_rechts)

        with self._lock:
            self.target_speed_links = v_links
            self.target_speed_rechts = v_rechts
            self.command_speed_kmh = speed_kmh
            self.command_yaw_dps = yaw_dps
            self.last_command_time = time.time()
            self.watchdog_tripped = False

    def drive_curvature(self, speed_kmh, curvature):
        """
        Rijden langs een boog met een gegeven kromming (1/m, + = rechtsom).

        Dit is wat pure pursuit oplevert. Bij snelheid 0 is kromming
        betekenisloos (je draait dan om een punt, niet langs een boog); de
        navigators gebruiken daarvoor turn_in_place().

        Is de bocht te scherp voor de toegestane draaisnelheid, dan REMMEN we
        af in plaats van de bocht flauwer te maken. De robot blijft zo op de
        gevraagde lijn; hij doet er alleen wat langer over.
        """
        curvature = self._clamp_curvature(curvature)
        speed_mps = speed_kmh / 3.6
        yaw_dps = math.degrees(speed_mps * curvature)

        if abs(yaw_dps) > self.max_yaw_rate_dps and abs(curvature) > 1e-6:
            speed_mps = math.radians(self.max_yaw_rate_dps) / abs(curvature)
            speed_kmh = math.copysign(speed_mps * 3.6, speed_kmh)
            yaw_dps = math.copysign(self.max_yaw_rate_dps, yaw_dps)

        self.drive(speed_kmh, yaw_dps)

    def turn_in_place(self, yaw_rate_dps):
        """
        Draaien op de plek: rijsnelheid 0, alleen draaien.

        Met vooruit-only motoren wordt dit een pivot om het stilstaande
        binnenwiel: de robot draait om een punt op de as, halverwege onder het
        binnenwiel, en schuift daarbij een klein stukje vooruit.
        """
        self.drive(0.0, yaw_rate_dps)

    def drive_manual(self, speed_kmh, turn_percentage):
        """Handbediening: -100% = maximaal linksom, +100% = maximaal rechtsom."""
        turn_percentage = max(-100.0, min(100.0, turn_percentage))
        self.drive(speed_kmh, (turn_percentage / 100.0) * self.max_yaw_rate_dps)

    def stop(self):
        """Noodstop: direct stil, zonder vloeiende afbouw."""
        with self._lock:
            self.target_speed_links = 0.0
            self.target_speed_rechts = 0.0
            self.current_speed_links = 0.0
            self.current_speed_rechts = 0.0
            self.command_speed_kmh = 0.0
            self.command_yaw_dps = 0.0
            self.current_dac_links = self.throttle.dac_stop
            self.current_dac_rechts = self.throttle.dac_stop
            self.last_command_time = time.time()
        self.motor_controller.stop()
        self.logger.warning("VOERTUIG NOODSTOP GEACTIVEERD.")

    def get_state(self):
        """Momentopname voor de API en de logging."""
        with self._lock:
            v_l, v_r = self.current_speed_links, self.current_speed_rechts
            return {
                "speed_links_mps": round(v_l, 3),
                "speed_rechts_mps": round(v_r, 3),
                "dac_links": self.current_dac_links,
                "dac_rechts": self.current_dac_rechts,
                "snelheid_kmh": round((v_l + v_r) / 2.0 * 3.6, 2),
                "draaisnelheid_dps": round(
                    math.degrees((v_l - v_r) / self.track_width), 1
                ),
                "commando_kmh": round(self.command_speed_kmh, 2),
                "commando_dps": round(self.command_yaw_dps, 1),
                "watchdog": self.watchdog_tripped,
            }

    def shutdown(self):
        """Veilig afsluiten van thread en seriële poort."""
        self.running = False
        self.stop()
        if self.smoothing_thread.is_alive():
            self.smoothing_thread.join(timeout=1.0)
        self.motor_controller.close()

    # ------------------------------------------------------------------ #
    #  Skid steer wiskunde
    # ------------------------------------------------------------------ #
    def _wheel_speeds(self, speed_mps, yaw_rad_s):
        """(v, omega) -> (v_links, v_rechts). Rechtsom draaien = links sneller."""
        verschil = yaw_rad_s * self.half_track
        return speed_mps + verschil, speed_mps - verschil

    def _clamp_curvature(self, curvature):
        max_curv = 1.0 / self.min_turn_radius
        return max(-max_curv, min(max_curv, curvature))

    def _fit_to_hardware(self, v_links, v_rechts):
        """
        Pers de gewenste wielsnelheden in wat de hardware kan: vooruit-only,
        een dode zone onderin en een maximum bovenin.

        Leidend principe: de VERHOUDING tussen links en rechts (en daarmee de
        draaistraal) blijft zoveel mogelijk staan. Beide wielen met dezelfde
        factor schalen verandert namelijk wel de snelheid, maar niet de bocht.
        """
        # 1. Vooruit-only. Een negatieve kant kan niet; we zetten hem stil en
        #    geven het verschil door aan de andere kant. Zo blijft de gevraagde
        #    DRAAISNELHEID exact staan (de robot kruipt alleen wat vooruit
        #    terwijl hij draait, in plaats van om zijn as te draaien).
        if v_links < 0.0:
            v_rechts -= v_links
            v_links = 0.0
        if v_rechts < 0.0:
            v_links -= v_rechts
            v_rechts = 0.0

        buiten = max(v_links, v_rechts)
        if buiten <= self.creep_threshold_mps:
            return 0.0, 0.0  # te traag om iets zinnigs te doen -> stilstaan

        # 2. Buitenste wiel binnen het werkbereik van de motor brengen.
        schaal = 1.0
        if buiten < self.min_speed_mps:
            schaal = self.min_speed_mps / buiten   # optrekken uit de dode zone
        if buiten * schaal > self.max_speed_mps:
            schaal = self.max_speed_mps / buiten   # aftoppen op de topsnelheid
        v_links *= schaal
        v_rechts *= schaal

        # 3. Binnenste wiel in de dode zone? Twee mogelijkheden:
        #    - de bocht is flauw genoeg: beide wielen samen optrekken tot het
        #      binnenwiel net draait (bocht blijft exact gelijk);
        #    - de bocht is te scherp: binnenwiel stilzetten en om dat wiel
        #      pivoteren (de scherpste bocht die deze hardware kan maken).
        buiten = max(v_links, v_rechts)
        binnen = min(v_links, v_rechts)
        if 0.0 < binnen < self.min_speed_mps:
            haalbare_verhouding = self.min_speed_mps / self.max_speed_mps
            if binnen / buiten >= haalbare_verhouding:
                schaal_op = self.min_speed_mps / binnen
                v_links *= schaal_op
                v_rechts *= schaal_op
            elif v_links < v_rechts:
                v_links = 0.0
            else:
                v_rechts = 0.0

        return v_links, v_rechts

    # ------------------------------------------------------------------ #
    #  Achtergrondlus: vloeiend maken en naar de hardware sturen
    # ------------------------------------------------------------------ #
    def _smoothing_loop(self):
        """
        Draait op vaste frequentie (standaard 20 Hz) en schuift de actuele
        wielsnelheden richting de doelwaarden.

        Beide kanten worden GEKOPPELD begrensd: we bepalen één factor voor de
        grootste stap en passen die op allebei toe. Zouden we per wiel apart
        begrenzen, dan is het binnenwiel eerder op zijn doelwaarde dan het
        buitenwiel en stuurt de robot tijdens elke acceleratie even de
        verkeerde kant op.
        """
        while self.running:
            start_time = time.time()

            with self._lock:
                doel_l = self.target_speed_links
                doel_r = self.target_speed_rechts

                # Watchdog: al te lang niets gehoord -> zelf stoppen.
                if (self.command_timeout > 0
                        and (doel_l > 0.0 or doel_r > 0.0)
                        and (start_time - self.last_command_time) > self.command_timeout):
                    if not self.watchdog_tripped:
                        self.logger.warning(
                            f"Geen rijcommando in {self.command_timeout:.1f}s: "
                            f"robot wordt uit veiligheid gestopt."
                        )
                    self.watchdog_tripped = True
                    doel_l = doel_r = 0.0
                    self.target_speed_links = 0.0
                    self.target_speed_rechts = 0.0

                huidig_l = self.current_speed_links
                huidig_r = self.current_speed_rechts

                stilstand = (huidig_l <= 0.0 and huidig_r <= 0.0)
                if stilstand and (doel_l > 0.0 or doel_r > 0.0):
                    # Wegrijden: sla de dode zone in één keer over, op de juiste
                    # verhouding, zodat de robot niet eerst 'niets' doet en
                    # daarna met een schok aan de gang gaat.
                    huidig_l, huidig_r = self._kickstart(doel_l, doel_r)
                else:
                    huidig_l, huidig_r = self._slew(huidig_l, huidig_r, doel_l, doel_r)

                self.current_speed_links = huidig_l
                self.current_speed_rechts = huidig_r
                dac_l = self._speed_to_dac(huidig_l)
                dac_r = self._speed_to_dac(huidig_r)
                self.current_dac_links = dac_l
                self.current_dac_rechts = dac_r

            self.motor_controller.stuur_motoren(dac_l, dac_r)

            elapsed = time.time() - start_time
            time.sleep(max(0.001, self.smoothing_interval - elapsed))

    def _kickstart(self, doel_l, doel_r):
        """
        Springt vanuit stilstand direct naar de laagste snelheid waarbij het
        traagste meedraaiende wiel net uit de dode zone komt, met dezelfde
        links/rechts-verhouding als het doel. Vanaf daar accelereert de
        normale begrenzer verder.
        """
        rijdend = [v for v in (doel_l, doel_r) if v > 0.0]
        if not rijdend:
            return 0.0, 0.0
        schaal = min(1.0, self.min_speed_mps / min(rijdend))
        return doel_l * schaal, doel_r * schaal

    def _slew(self, huidig_l, huidig_r, doel_l, doel_r):
        """Gekoppelde acceleratie-/rembegrenzing: één factor voor beide kanten."""
        d_l = doel_l - huidig_l
        d_r = doel_r - huidig_r
        grootste = max(abs(d_l), abs(d_r))
        if grootste < 1e-6:
            return doel_l, doel_r

        # Afremmen mag sneller dan optrekken: veiligheid boven comfort.
        remmen = (abs(doel_l) + abs(doel_r)) < (abs(huidig_l) + abs(huidig_r))
        limiet = self.max_decel_mps2 if remmen else self.max_accel_mps2
        max_stap = limiet * self.smoothing_interval

        factor = 1.0 if grootste <= max_stap else (max_stap / grootste)
        nieuw_l = huidig_l + d_l * factor
        nieuw_r = huidig_r + d_r * factor

        # Onder de dode zone heeft 'langzaam uitrollen' geen betekenis meer:
        # de motor staat daar toch stil. Netjes op 0 zetten voorkomt dat de
        # robot in een schijnbeweging blijft hangen.
        if doel_l <= 0.0 and nieuw_l < self.min_speed_mps:
            nieuw_l = 0.0
        if doel_r <= 0.0 and nieuw_r < self.min_speed_mps:
            nieuw_r = 0.0

        return max(0.0, nieuw_l), max(0.0, nieuw_r)

    def _speed_to_dac(self, speed_mps):
        if speed_mps < self.min_speed_mps:
            return self.throttle.dac_stop
        return self.throttle.speed_to_dac(min(speed_mps, self.max_speed_mps))
