import math
import time
import threading
import logging

from app.services.gnss_navigatie import GnssBewaker, LijnRegelaar, lijn_frame, peiling, norm180

# Optioneel: Importeer je bestaande logger als je die nog gebruikt voor analyse
try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

class Navigator:
    """
    De 'Routeplanner en Chauffeur' van de AgBot.
    Volgt een lijst met GPS-waypoints. Geheel onafhankelijk van
    hardware-specifieke (motor) logica.

    Hij volgt het LIJNSTUK van het vorige punt (bij het eerste punt: de
    startpositie) naar het huidige, met dezelfde LijnRegelaar als de
    AB-banen (Stanley of pure pursuit). Een punt is bereikt binnen de
    aankomstdrempel, of zodra de robot de loodlijn door het punt passeert -
    met RTK hoeft hij er niet exact overheen om door te gaan.
    De regellus loopt op het ritme van de GNSS (25 Hz) en de GnssBewaker
    bepaalt of en hoe hard er gereden wordt.
    """
    def __init__(self, gps_system, vehicle_controller, config):
        self.logger = logging.getLogger(__name__)
        if DriveLogger:
            self.drive_logger = DriveLogger()
        else:
            self.drive_logger = None
        
        # Geïnjecteerde modules
        self.gps = gps_system
        self.vehicle = vehicle_controller
        
        # Voertuig & Stuur parameters
        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)
        steering_config = config.get("steering", {})
        # Grootste stuurhoek van het virtuele midden. Dit is NIET de wiellimiet
        # uit de config: het binnenste voorwiel staat bij Ackermann scherper dan
        # het midden, dus de bruikbare middenhoek ligt lager. De
        # VehicleController leidt hem af uit wielbasis en spoorbreedte.
        self.max_angle = getattr(
            vehicle_controller, "max_center_angle",
            steering_config.get("max_angle_degrees", 45.0)
        )
        
        # Pure Pursuit & Navigatie instellingen
        nav_config = config.get("navigation", {})
        self.lookahead_distance = nav_config.get("lookahead_distance_m", 2.0)
        self.arrival_threshold_inter = nav_config.get("arrival_threshold_intermediate_m", 0.6) # Tussen-waypoints
        self.arrival_threshold_final = nav_config.get("arrival_threshold_final_m", 0.3)        # Laatste waypoint
        
        # Missie status
        self.waypoints = []
        self.current_wp_index = 0
        self.target_speed_kmh = 0.0
        self.mode = "pure_pursuit"
        
        self.bewaker = GnssBewaker(config)
        self.regelaar = LijnRegelaar(config, self.wheelbase, self.max_angle)
        self.mode = self.regelaar.soort
        self.segment_start = None      # (lat, lon) waar het huidige lijnstuk begint

        self.is_active = False
        self.nav_thread = None
        self.state = "IDLE"            # IDLE | WACHT_OP_GNSS | RIJDEN | KLAAR | FOUT
        self.status_message = "Gestopt"

    def load_route(self, waypoints, speed_kmh):
        """
        Laadt een nieuwe route in.
        :param waypoints: Lijst met dicts [{"lat": 52.1, "lon": 4.1}, ...]
        """
        self.waypoints = waypoints
        self.current_wp_index = 0
        self.segment_start = None
        self.target_speed_kmh = speed_kmh
        self.logger.info(f"Route geladen met {len(waypoints)} waypoints. Doelsnelheid: {speed_kmh} km/h")

    def start(self):
        """Start de autonome navigatiemissie langs de geladen waypoints."""
        if not self.waypoints:
            self.state = "FOUT"
            self.status_message = "Geen waypoints geladen"
            self.logger.warning("Kan niet starten: Geen waypoints geladen!")
            return

        if self.is_active:
            self.stop()

        # Start een nieuw logbestand voor deze rit (anders wordt er niets gelogd).
        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="Waypoint_Route")

        self.segment_start = None      # eerste lijnstuk begint waar de robot nu staat
        self.is_active = True
        self.state = "RIJDEN"
        self.status_message = f"Route actief ({len(self.waypoints)} punten)"
        self.nav_thread = threading.Thread(target=self._navigation_loop, daemon=True)
        self.nav_thread.start()
        self.logger.info("Autonome navigatie GESTART.")

    def stop(self):
        """Stopt de navigatie direct en zet het voertuig veilig stil."""
        self.is_active = False
        if self.nav_thread and self.nav_thread.is_alive():
            self.nav_thread.join(timeout=1.0)

        # Laat de spieren direct stoppen
        self.vehicle.stop()
        if self.drive_logger:
            self.drive_logger.stop_log()
        if self.state not in ("KLAAR", "FOUT"):
            self.state = "IDLE"
            self.status_message = "Gestopt"
        self.logger.info("Navigatie GESTOPT. Voertuig staat stil.")

    def _navigation_loop(self):
        """
        De hoofd-regellus, op het ritme van de GNSS (25 Hz). Berekent continu
        de positie, het volgende doel en de benodigde stuurcorrectie.
        """
        try:
            self._run_loop()
        except Exception as e:
            # Een onafgevangen fout zou de (daemon) thread stil laten sterven:
            # geen rijden, geen logging, geen melding. Hier maken we hem zichtbaar.
            self.state = "FOUT"
            self.status_message = f"Navigatiefout: {e}"
            self.logger.exception(f"Onverwachte fout in navigatie-lus: {e}")
        finally:
            self.is_active = False
            self.vehicle.stop()
            if self.drive_logger:
                self.drive_logger.stop_log()

    def _run_loop(self):
        epoch = -1
        vorige = time.time()
        while self.is_active and self.current_wp_index < len(self.waypoints):
            # Rekenen zodra er een nieuwe meting is (25 Hz); na 0.1 s zonder
            # data toch een rondje, dan zet de GnssBewaker hem stil.
            epoch = self.gps.wacht_op_epoch(epoch, timeout=0.1)
            nu = time.time()
            dt, vorige = nu - vorige, nu

            # 0. Aandrijving in orde? CAN weg, een VESC-fout of een vastgelopen
            #    wiel beeindigt de missie; opnieuw rijden gaat via een nieuwe start.
            fout = self.vehicle.drive_fault
            if fout:
                self.state = "FOUT"
                self.status_message = f"Aandrijving: {fout}"
                self.logger.error(f"Navigatie gestopt, aandrijving: {fout}")
                break

            # 1. Nieuwste GNSS-meting, en mag daarop gereden worden?
            curr_pos = self.gps.get_current_position()
            snelheid, melding = self.bewaker.beoordeel(curr_pos, self.target_speed_kmh)
            if snelheid <= 0.0:
                if self.state != "WACHT_OP_GNSS":
                    self.logger.warning(f"Navigatie wacht: {melding}")
                self.state = "WACHT_OP_GNSS"
                self.status_message = melding
                self.vehicle.drive(0.0, 0.0) # Veiligheid: stilstaan zonder goede GNSS
                continue

            self.state = "RIJDEN"

            curr_lat = curr_pos["lat"]
            curr_lon = curr_pos["lon"]
            curr_heading = curr_pos["heading"]
            if self.segment_start is None:
                self.segment_start = (curr_lat, curr_lon)

            # 2. Huidig lijnstuk: van segment_start naar het doelpunt
            target_wp = self.waypoints[self.current_wp_index]
            is_last_wp = (self.current_wp_index == len(self.waypoints) - 1)
            start_lat, start_lon = self.segment_start
            lengte = self._calculate_distance(start_lat, start_lon, target_wp["lat"], target_wp["lon"])
            distance = self._calculate_distance(curr_lat, curr_lon, target_wp["lat"], target_wp["lon"])
            if lengte < 0.5:
                # Punt ligt op het vorige (of op de startplek): koers recht naar het punt.
                lijn_koers = self._calculate_bearing(curr_lat, curr_lon, target_wp["lat"], target_wp["lon"])
                langs, afwijking = 0.0, 0.0
            else:
                lijn_koers = peiling(start_lat, start_lon, target_wp["lat"], target_wp["lon"])
                langs, afwijking = lijn_frame(curr_lat, curr_lon, start_lat, start_lon, lijn_koers)

            # 3. Aangekomen: binnen de drempel, of de loodlijn door het punt gepasseerd
            threshold = self.arrival_threshold_final if is_last_wp else self.arrival_threshold_inter
            gepasseerd = lengte >= 0.5 and langs >= lengte
            if distance <= threshold or gepasseerd:
                self.logger.info(
                    f"Waypoint {self.current_wp_index} bereikt (afstand {distance:.2f} m"
                    f"{', loodlijn gepasseerd' if gepasseerd and distance > threshold else ''})."
                )
                self.segment_start = (target_wp["lat"], target_wp["lon"])
                self.current_wp_index += 1
                if self.current_wp_index >= len(self.waypoints):
                    self.state = "KLAAR"
                    self.status_message = "Eindbestemming bereikt"
                    self.logger.info("🏁 Eindbestemming bereikt! Missie voltooid.")
                    break # Verlaat de loop, we zijn klaar!
                continue # Direct doorrekenen naar volgende waypoint

            # 4. Stuurhoek met de LijnRegelaar (Stanley of pure pursuit)
            final_steering_angle = self.regelaar.stuur(
                curr_heading, lijn_koers, afwijking, curr_pos.get("speed_kmh", 0.0),
                curr_pos.get("draaisnelheid_dps", 0.0), self.lookahead_distance,
                lijn_id=(id(self.waypoints), self.current_wp_index), dt=dt
            )

            # 5. STUUR HET VOERTUIG AAN
            # De VehicleController handelt het differentieel, smoothing en anti-stall af.
            self.vehicle.drive(snelheid, final_steering_angle)
            self.status_message = (
                f"Naar punt {self.current_wp_index + 1}/{len(self.waypoints)}: nog {distance:.1f} m, "
                f"afwijking {afwijking:+.2f} m" + (f" | {melding}" if melding else "")
            )

            # 6. LOGGING
            if self.drive_logger:
                try:
                    self.drive_logger.log_regel(
                        wp_idx=self.current_wp_index,
                        modus=self.mode,
                        lat=curr_lat,
                        lon=curr_lon,
                        fix=curr_pos.get("fix", 0),
                        hdop=curr_pos.get("hdop", 99.0),
                        heading_echt=curr_heading,
                        heading_doel=lijn_koers,
                        heading_fout=norm180(lijn_koers - curr_heading),
                        stuurhoek=final_steering_angle,
                        doel_kmh=snelheid,
                        echt_kmh=curr_pos.get("speed_kmh", 0.0),
                        dist_wp=distance,
                        lookahead=self.lookahead_distance,
                        dt=dt,
                        motor=self.vehicle.log_snapshot(),
                        xte=afwijking, regelaar=self.regelaar.soort, gnss=curr_pos
                    )
                except Exception as e:
                    self.logger.error(f"Fout bij loggen: {e}")

        # Afronden (stoppen, logbestand afsluiten) gebeurt in _navigation_loop().

    # --- HULPFUNCTIES (Wiskunde) ---

    def _calculate_distance(self, lat1, lon1, lat2, lon2):
        """Berekent de afstand in meters tussen twee GPS coördinaten (Haversine)."""
        R = 6371000.0 # Aardstraal in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _calculate_bearing(self, lat1, lon1, lat2, lon2):
        """Berekent de kompasrichting (0-360 graden) van positie 1 naar positie 2."""
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)
        
        y = math.sin(delta_lambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
        
        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360