import math
import time
import threading
import logging

try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

R_EARTH = 6371000.0


class ABNavigator:
    """
    AB-lijn navigator voor het rijden van parallelle banen ('swaths').

    Werkt - net als de waypoint-Navigator - volledig in KOMPAS-graden
    (0 graden = Noord, met de klok mee). Dit is essentieel: de GPS levert een
    kompasheading, dus alle hoek-wiskunde moet in datzelfde stelsel gebeuren.

    Gedrag:
      1. START : pak de AB-lijn op en rijd 'field_length' meter in de richting
                 van de lijn. Staat A == B (of liggen ze vlak bij elkaar), dan
                 wordt de baanrichting afgeleid uit de huidige neus-richting
                 (GPS-heading) en de huidige positie.
      2. EIND  : draai aan het eind een halve cirkel (kopakker-bocht) en pak de
                 volgende baan op, 'work_width' meter opzij en in omgekeerde
                 rijrichting. De draairichting wisselt per baan (rechts, links,
                 rechts, ...) zodat de banen steeds dezelfde kant op opschuiven.

    Skid steer: sturen gaat via KROMMING (1/m) in plaats van een stuurhoek.
    Dat maakt de kopakker-bocht een stuk eenvoudiger dan bij een gestuurd
    voorwiel: de robot kan elke straal draaien tot aan een pivot om zijn eigen
    binnenwiel toe, dus de bochtstraal volgt gewoon uit de werkbreedte.
    """

    def __init__(self, gps_system, vehicle_controller, config):
        self.logger = logging.getLogger(__name__)
        self.drive_logger = DriveLogger() if DriveLogger else None

        self.gps = gps_system
        self.vehicle = vehicle_controller

        # Scherpste bocht die de aandrijving aankan (komt uit de
        # VehicleController, die de spoorbreedte en de motorlimieten kent).
        self.min_turn_radius = getattr(vehicle_controller, "min_turn_radius", 0.85)

        # Navigatie-instellingen (met config-fallback)
        nav_cfg = config.get("navigation", {})
        self.lookahead_m = nav_cfg.get("lookahead_distance_m", 2.5)
        self.turn_speed_kmh = nav_cfg.get("turn_speed_kmh", 2.0)
        self.max_swaths = nav_cfg.get("max_swaths", 1000)
        # Kopakker-bocht: stop de bocht als de koers binnen deze tolerantie van de
        # volgende baanrichting ligt; de timeout voorkomt eindeloos rondjes draaien.
        self.turn_heading_tol_deg = nav_cfg.get("turn_heading_tolerance_deg", 8.0)
        self.turn_timeout_s = nav_cfg.get("turn_timeout_s", 40.0)
        # Bij een grote koersfout op de baan eerst op de plek indraaien.
        self.spot_turn_threshold_deg = nav_cfg.get("spot_turn_threshold_deg", 60.0)
        self.spot_turn_yaw_dps = nav_cfg.get("spot_turn_yaw_rate_dps", 25.0)
        # De ZED-X20D levert tot 25 Hz, dus de regellus mag sneller dan 10 Hz.
        self.loop_rate_hz = nav_cfg.get("loop_rate_hz", 20.0)
        self.min_fix_quality = nav_cfg.get("min_fix_quality", 2)

        # Missie-parameters (gezet via start_mission)
        self.work_width_m = 4.0
        self.field_length_m = 50.0
        self.target_speed_kmh = 3.0

        # Lijn-definitie (lokaal kompasframe rond een vast referentiepunt)
        self.ref_lat = 0.0
        self.ref_lon = 0.0
        self.base_bearing_deg = 0.0      # richting van baan 0 (kompas)
        self.line_initialized = False    # False = afleiden uit eerste GPS-fix
        self._ab_distinct = False        # True als A en B betekenisvol verschillen

        # Missie-status
        self.is_active = False
        self.nav_thread = None
        self.state = "IDLE"              # IDLE | TRACKING | TURNING
        self.current_swath = 0
        self.pass_start_along = None     # langs-afstand bij start van huidige baan
        # Kopakker-bocht (vaste-boog met heading-feedback)
        self.turn_target_bearing = 0.0   # koers van de volgende baan
        self.turn_curvature = 0.0        # vaste kromming tijdens de bocht (+ = rechts)
        self.turn_start_heading = 0.0
        self.turn_start_time = 0.0

    # ------------------------------------------------------------------ #
    #  Publieke API (gebruikt door endpoints.py)
    # ------------------------------------------------------------------ #
    def set_ab_line(self, lat_a, lon_a, lat_b, lon_b):
        if None in (lat_a, lon_a, lat_b, lon_b):
            return False

        self.ref_lat = lat_a
        self.ref_lon = lon_a

        # Verschillen A en B genoeg om er een richting uit te halen?
        ab_dist = self._haversine(lat_a, lon_a, lat_b, lon_b)
        if ab_dist > 1.0:
            self.base_bearing_deg = self._bearing(lat_a, lon_a, lat_b, lon_b)
            self.line_initialized = True
            self._ab_distinct = True
            self.logger.info(
                f"AB-lijn gezet uit A->B: richting {self.base_bearing_deg:.1f} graden "
                f"({ab_dist:.1f} m tussen A en B)."
            )
        else:
            # A == B: richting + oorsprong afleiden uit de eerste goede GPS-fix.
            self.line_initialized = False
            self._ab_distinct = False
            self.logger.info(
                "A en B vallen samen -> baanrichting wordt bij start afgeleid "
                "uit de huidige neus-richting (GPS-heading)."
            )

        self.current_swath = 0
        return True

    def start_mission(self, work_width, field_length, speed):
        self.work_width_m = max(0.1, work_width)
        self.field_length_m = max(1.0, field_length)
        self.target_speed_kmh = speed

        if self.is_active:
            self.stop()

        self.current_swath = 0
        self.pass_start_along = None
        self.state = "TRACKING"

        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="AB_Missie")

        # Een 180-graden kopakkerbocht verplaatst de robot 2*R zijwaarts. Bij
        # skid steer is de minimale straal de pivot om het binnenwiel, dus dit
        # gaat vrijwel altijd goed; alleen bij een heel smalle werkbreedte
        # overschiet de bocht nog.
        min_radius = self.min_turn_radius
        if self.work_width_m < 2.0 * min_radius:
            self.logger.warning(
                f"Werkbreedte {self.work_width_m:.2f} m < min. bochtbreedte "
                f"{2.0 * min_radius:.2f} m (R_min={min_radius:.2f} m). De bocht "
                f"overschiet; cross-track correctie trekt terug op lijn."
            )

        self.is_active = True
        self.nav_thread = threading.Thread(target=self._navigation_loop, daemon=True)
        self.nav_thread.start()
        self.logger.info(
            f"AB-missie gestart: werkbreedte={self.work_width_m} m, "
            f"baanlengte={self.field_length_m} m, snelheid={self.target_speed_kmh} km/h, "
            f"min. draaistraal R={min_radius:.2f} m."
        )

    def stop(self):
        self.is_active = False
        self.state = "IDLE"
        if self.nav_thread and self.nav_thread.is_alive():
            self.nav_thread.join(timeout=1.0)
        self.vehicle.stop()
        if self.drive_logger:
            self.drive_logger.stop_log()
        self.logger.info("AB-missie gestopt.")

    # ------------------------------------------------------------------ #
    #  Hoofdlus
    # ------------------------------------------------------------------ #
    def _navigation_loop(self):
        interval = 1.0 / max(1.0, self.loop_rate_hz)

        while self.is_active:
            start_time = time.time()
            curr_pos = self.gps.get_current_position()

            # Veiligheid: geen (RTK-)fix -> stilstaan
            if not curr_pos or curr_pos.get("lat", 0.0) == 0.0 or curr_pos.get("fix", 0) < self.min_fix_quality:
                self.vehicle.drive(0.0, 0.0)
                time.sleep(0.1)
                continue

            # Zonder geldige koers kan een skid steer geen kant op: stilstaan.
            if not curr_pos.get("heading_geldig", True):
                self.vehicle.drive(0.0, 0.0)
                time.sleep(0.1)
                continue

            # Lijn afleiden bij eerste goede fix (alleen als A == B)
            if not self.line_initialized:
                self.ref_lat = curr_pos["lat"]
                self.ref_lon = curr_pos["lon"]
                self.base_bearing_deg = curr_pos["heading"]
                self.line_initialized = True
                self.logger.info(
                    f"Baanrichting afgeleid uit neus: {self.base_bearing_deg:.1f} graden."
                )

            if self.state == "TRACKING":
                self._handle_tracking(curr_pos)
            elif self.state == "TURNING":
                self._handle_turning(curr_pos)

            elapsed = time.time() - start_time
            time.sleep(max(0.01, interval - elapsed))

        self.vehicle.stop()

    # ------------------------------------------------------------------ #
    #  TRACKING: volg de huidige baanlijn met pure pursuit
    # ------------------------------------------------------------------ #
    def _handle_tracking(self, curr_pos):
        along, cross = self._along_cross(curr_pos["lat"], curr_pos["lon"])
        sign = self._pass_sign()                       # +1 of -1 (rijrichting baan)

        # Begin van een nieuwe baan? Leg het startpunt langs de lijn vast.
        if self.pass_start_along is None:
            self.pass_start_along = along

        progress = sign * (along - self.pass_start_along)   # afgelegd op deze baan
        offset = self.current_swath * self.work_width_m     # baan-offset naar rechts
        xte = cross - offset                                 # cross-track error

        # Eind van de baan bereikt -> kopakker-bocht plannen
        if progress >= self.field_length_m:
            if self.current_swath + 1 >= self.max_swaths:
                self.logger.info("Maximaal aantal banen bereikt. Missie klaar.")
                self.stop()
                return
            self._plan_turn(curr_pos)
            self.state = "TURNING"
            return

        # Carrot-punt: op de baanlijn, 'lookahead' meter vooruit.
        carrot_along = along + sign * self.lookahead_m
        c_lat, c_lon = self._local_to_latlon(carrot_along, offset)

        target_bearing = self._bearing(curr_pos["lat"], curr_pos["lon"], c_lat, c_lon)
        alpha = self._norm180(target_bearing - curr_pos["heading"])

        if abs(alpha) > self.spot_turn_threshold_deg:
            # Staat de robot dwars op de baan (bv. handmatig verzet), dan eerst
            # op de plek indraaien; pure pursuit is bij zulke hoeken onbetrouwbaar.
            curvature = 0.0
            draai_dps = math.copysign(self.spot_turn_yaw_dps, alpha)
            self.vehicle.turn_in_place(draai_dps)
        else:
            curvature = self._pure_pursuit_curvature(alpha)
            draai_dps = math.degrees((self.target_speed_kmh / 3.6) * curvature)
            self.vehicle.drive_curvature(self.target_speed_kmh, curvature)

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=curr_pos["heading"], heading_doel=target_bearing,
                heading_fout=xte, draai_dps=draai_dps, kromming=curvature,
                doel_kmh=self.target_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                snelheid_links=self.vehicle.current_speed_links,
                snelheid_rechts=self.vehicle.current_speed_rechts,
                dist_wp=progress, lookahead=self.lookahead_m, dt=(1.0 / self.loop_rate_hz)
            )

    # ------------------------------------------------------------------ #
    #  TURNING: vaste-boog kopakker-bocht met heading-feedback
    # ------------------------------------------------------------------ #
    def _handle_turning(self, curr_pos):
        heading = curr_pos["heading"]

        # Hoeveel is de koers nog verwijderd van de volgende baanrichting?
        rest = abs(self._norm180(self.turn_target_bearing - heading))
        # Hoeveel is hij al gedraaid sinds het begin van de bocht?
        gedraaid = abs(self._norm180(heading - self.turn_start_heading))
        timeout = (time.time() - self.turn_start_time) > self.turn_timeout_s

        # Bocht klaar: koers ligt op de nieuwe baan (na min. 120° gedraaid),
        # of de veiligheids-timeout grijpt in (voorkomt eindeloos rondjes).
        if (rest <= self.turn_heading_tol_deg and gedraaid >= 120.0) or timeout:
            self.current_swath += 1
            self.pass_start_along = None
            self.state = "TRACKING"
            if timeout:
                self.logger.warning(
                    f"Bocht-timeout ({self.turn_timeout_s:.0f}s) -> baan "
                    f"{self.current_swath} wordt geforceerd opgepakt."
                )
            else:
                self.logger.info(f"Bocht klaar. Baan {self.current_swath} wordt opgepakt.")
            return

        # Tijdens de bocht: constante kromming, dus een vaste draaicirkel.
        self.vehicle.drive_curvature(self.turn_speed_kmh, self.turn_curvature)

        if self.drive_logger:
            draai_dps = math.degrees((self.turn_speed_kmh / 3.6) * self.turn_curvature)
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=heading, heading_doel=self.turn_target_bearing,
                heading_fout=rest, draai_dps=draai_dps, kromming=self.turn_curvature,
                doel_kmh=self.turn_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                snelheid_links=self.vehicle.current_speed_links,
                snelheid_rechts=self.vehicle.current_speed_rechts,
                dist_wp=gedraaid, lookahead=self.lookahead_m, dt=(1.0 / self.loop_rate_hz)
            )

    def _plan_turn(self, curr_pos):
        """
        Plan een kopakker-bocht met een vaste draaicirkel.

        We rijden met een constante kromming (straal = werkbreedte/2, of de
        minimale fysieke draaistraal) tot de koers ~180 graden is omgedraaid en
        op de richting van de volgende baan ligt. Open-loop op positie, maar
        closed-loop op koers: dit kan - anders dan waypoint-volgen - niet in een
        oneindige cirkel blijven hangen. De cross-track correctie van TRACKING
        trekt de robot daarna netjes op de nieuwe lijn.
        """
        # Straal -> kromming. Naar RECHTS = positieve kromming (zelfde
        # conventie als de pure-pursuit tracking).
        radius = max(self.min_turn_radius, self.work_width_m / 2.0)
        kromming = 1.0 / radius

        # Boustrophedon: de draairichting MOET per baan wisselen, anders pendelt
        # de robot tussen twee posities i.p.v. steeds een werkbreedte op te
        # schuiven. Even baan -> rechtsbocht (+), oneven baan -> linksbocht (-).
        turn_dir = self._pass_sign()
        self.turn_curvature = turn_dir * kromming

        # Richting van de volgende baan (omgekeerd t.o.v. de huidige).
        next_swath = self.current_swath + 1
        forward = self.base_bearing_deg if (next_swath % 2 == 0) else self.base_bearing_deg + 180.0
        self.turn_target_bearing = forward % 360.0

        self.turn_start_heading = curr_pos["heading"]
        self.turn_start_time = time.time()

        richting = "rechts" if self.turn_curvature >= 0 else "links"
        self.logger.info(
            f"Kopakker-bocht (vaste boog) naar {richting}: straal {radius:.2f} m, "
            f"kromming {self.turn_curvature:.3f} 1/m, doelkoers "
            f"{self.turn_target_bearing:.1f} graden naar baan {next_swath}."
        )

    # ------------------------------------------------------------------ #
    #  Wiskunde-helpers (alles in kompas-graden)
    # ------------------------------------------------------------------ #
    def _pass_sign(self):
        """+1 voor even banen (basisrichting), -1 voor oneven (omgekeerd)."""
        return 1.0 if (self.current_swath % 2 == 0) else -1.0

    @staticmethod
    def _norm180(deg):
        """Normaliseer een hoekverschil naar -180 .. +180 graden."""
        return (deg + 180.0) % 360.0 - 180.0

    def _pure_pursuit_curvature(self, alpha_deg):
        """
        Kromming (1/m, + = rechtsom) van de boog door de robot en het
        carrot-punt: kappa = 2 * sin(alpha) / lookahead.

        De VehicleController topt te scherpe bochten zelf af (en remt daarbij
        af in plaats van de bocht flauwer te maken), dus hier geen extra limiet.
        """
        return 2.0 * math.sin(math.radians(alpha_deg)) / self.lookahead_m

    def _along_cross(self, lat, lon):
        """Projecteer (lat,lon) op het baanframe: langs- en rechts-afstand (m)."""
        north = R_EARTH * math.radians(lat - self.ref_lat)
        east = R_EARTH * math.radians(lon - self.ref_lon) * math.cos(math.radians(self.ref_lat))
        b = math.radians(self.base_bearing_deg)
        along = north * math.cos(b) + east * math.sin(b)
        right = -north * math.sin(b) + east * math.cos(b)
        return along, right

    def _local_to_latlon(self, along, right):
        """Inverse van _along_cross: baanframe (langs, rechts) -> (lat, lon)."""
        b = math.radians(self.base_bearing_deg)
        north = along * math.cos(b) - right * math.sin(b)
        east = along * math.sin(b) + right * math.cos(b)
        lat = self.ref_lat + math.degrees(north / R_EARTH)
        lon = self.ref_lon + math.degrees(east / (R_EARTH * math.cos(math.radians(self.ref_lat))))
        return lat, lon

    def _haversine(self, lat1, lon1, lat2, lon2):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _bearing(self, lat1, lon1, lat2, lon2):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dlmb = math.radians(lon2 - lon1)
        y = math.sin(dlmb) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
