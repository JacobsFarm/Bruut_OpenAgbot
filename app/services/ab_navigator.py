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
      2. EIND  : draai aan het eind een halve cirkel naar RECHTS (kopakker-bocht)
                 en pak de volgende baan op, 'work_width' meter naar rechts en in
                 omgekeerde rijrichting.
    """

    def __init__(self, gps_system, vehicle_controller, config):
        self.logger = logging.getLogger(__name__)
        self.drive_logger = DriveLogger() if DriveLogger else None

        self.gps = gps_system
        self.vehicle = vehicle_controller

        # Voertuig / stuur
        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)
        self.max_angle = config.get("steering", {}).get("max_angle_degrees", 45.0)

        # Navigatie-instellingen (met config-fallback)
        nav_cfg = config.get("navigation", {})
        self.lookahead_m = nav_cfg.get("lookahead_distance_m", 2.5)
        self.turn_wp_threshold_m = nav_cfg.get("arrival_threshold_intermediate_m", 0.6)
        self.turn_speed_kmh = nav_cfg.get("turn_speed_kmh", 2.0)
        self.max_swaths = nav_cfg.get("max_swaths", 1000)

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
        self.turn_waypoints = []         # lijst {"lat","lon"} voor de kopakker-bocht
        self.turn_wp_index = 0

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
        self.turn_waypoints = []
        self.turn_wp_index = 0
        self.state = "TRACKING"

        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="AB_Missie")

        self.is_active = True
        self.nav_thread = threading.Thread(target=self._navigation_loop, daemon=True)
        self.nav_thread.start()
        self.logger.info(
            f"AB-missie gestart: werkbreedte={self.work_width_m} m, "
            f"baanlengte={self.field_length_m} m, snelheid={self.target_speed_kmh} km/h."
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
        rate_hz = 10.0
        interval = 1.0 / rate_hz

        while self.is_active:
            start_time = time.time()
            curr_pos = self.gps.get_current_position()

            # Veiligheid: geen (RTK-)fix -> stilstaan
            if not curr_pos or curr_pos.get("lat", 0.0) == 0.0 or curr_pos.get("fix", 0) < 2:
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
            self._plan_turn(along, offset, sign)
            self.state = "TURNING"
            self.turn_wp_index = 0
            return

        # Carrot-punt: op de baanlijn, 'lookahead' meter vooruit.
        carrot_along = along + sign * self.lookahead_m
        c_lat, c_lon = self._local_to_latlon(carrot_along, offset)

        target_bearing = self._bearing(curr_pos["lat"], curr_pos["lon"], c_lat, c_lon)
        steering = self._pure_pursuit_steer(target_bearing, curr_pos["heading"])

        self.vehicle.drive(self.target_speed_kmh, steering)

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=curr_pos["heading"], heading_doel=target_bearing,
                heading_fout=xte, stuurhoek=steering, doel_kmh=self.target_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                dist_wp=progress, lookahead=self.lookahead_m, dt=0.1
            )

    # ------------------------------------------------------------------ #
    #  TURNING: volg de gegenereerde kopakker-bocht (waypoint pure pursuit)
    # ------------------------------------------------------------------ #
    def _handle_turning(self, curr_pos):
        if self.turn_wp_index >= len(self.turn_waypoints):
            # Bocht klaar: volgende baan oppakken.
            self.current_swath += 1
            self.pass_start_along = None
            self.state = "TRACKING"
            self.logger.info(f"Bocht klaar. Baan {self.current_swath} wordt opgepakt.")
            return

        wp = self.turn_waypoints[self.turn_wp_index]
        dist = self._haversine(curr_pos["lat"], curr_pos["lon"], wp["lat"], wp["lon"])

        # Bij dit bocht-punt aangekomen? Door naar het volgende.
        if dist <= self.turn_wp_threshold_m:
            self.turn_wp_index += 1
            return

        target_bearing = self._bearing(curr_pos["lat"], curr_pos["lon"], wp["lat"], wp["lon"])
        steering = self._pure_pursuit_steer(target_bearing, curr_pos["heading"])
        self.vehicle.drive(self.turn_speed_kmh, steering)

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.turn_wp_index, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=curr_pos["heading"], heading_doel=target_bearing,
                heading_fout=0.0, stuurhoek=steering, doel_kmh=self.turn_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                dist_wp=dist, lookahead=self.lookahead_m, dt=0.1
            )

    def _plan_turn(self, along_end, offset, sign):
        """
        Genereer een halve cirkel naar RECHTS van de huidige baan naar de
        volgende baan (offset + work_width), in omgekeerde rijrichting.

        Het middelpunt ligt 'radius' naar rechts van het baan-eind; de bocht
        bolt voorbij het veld-eind uit (de kopakker). Bij een te smalle
        werkbreedte wordt de minimale (fysieke) draaicirkel gebruikt; de
        cross-track correctie van TRACKING trekt de robot daarna alsnog op lijn.
        """
        min_radius = self.wheelbase / math.tan(math.radians(self.max_angle))
        radius = max(min_radius, self.work_width_m / 2.0)

        along_c = along_end                 # middelpunt: zelfde langs-positie
        right_c = offset + radius           # middelpunt naar rechts van baan-eind

        n_points = max(6, int(math.pi * radius / 0.5))
        self.turn_waypoints = []
        for i in range(1, n_points + 1):
            theta = math.pi * i / n_points          # 0 -> pi
            a = along_c + sign * radius * math.sin(theta)
            r = right_c - radius * math.cos(theta)  # offset -> offset + 2*radius
            lat, lon = self._local_to_latlon(a, r)
            self.turn_waypoints.append({"lat": lat, "lon": lon})

        self.logger.info(
            f"Kopakker-bocht gepland: {len(self.turn_waypoints)} punten, "
            f"radius {radius:.2f} m, naar baan {self.current_swath + 1}."
        )

    # ------------------------------------------------------------------ #
    #  Wiskunde-helpers (alles in kompas-graden)
    # ------------------------------------------------------------------ #
    def _pass_sign(self):
        """+1 voor even banen (basisrichting), -1 voor oneven (omgekeerd)."""
        return 1.0 if (self.current_swath % 2 == 0) else -1.0

    def _pure_pursuit_steer(self, target_bearing_deg, heading_deg):
        alpha = (target_bearing_deg - heading_deg + 180.0) % 360.0 - 180.0
        alpha_rad = math.radians(alpha)
        delta = math.degrees(
            math.atan2(2.0 * self.wheelbase * math.sin(alpha_rad), self.lookahead_m)
        )
        return max(-self.max_angle, min(self.max_angle, delta))

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
