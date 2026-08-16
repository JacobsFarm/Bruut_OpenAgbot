import math
import time
import threading
import logging

# Optioneel: Importeer je bestaande logger als je die nog gebruikt voor analyse
try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

class Navigator:
    """
    De 'Routeplanner en Chauffeur' van de AgBot.
    Volgt een lijst met GPS-waypoints via het Pure Pursuit algoritme.
    Geheel onafhankelijk van hardware-specifieke (DAC) logica.

    Skid steer: het resultaat van pure pursuit is hier een KROMMING (1/m) en
    geen stuurhoek. Een skid steer heeft geen stuurwiel en dus ook geen
    wielbasis in de wiskunde: de VehicleController vertaalt de kromming zelf
    naar een snelheidsverschil tussen links en rechts.
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

        # Pure Pursuit & Navigatie instellingen
        nav_config = config.get("navigation", {})
        self.lookahead_distance = nav_config.get("lookahead_distance_m", 2.0)
        self.arrival_threshold_inter = nav_config.get("arrival_threshold_intermediate_m", 0.6) # Tussen-waypoints
        self.arrival_threshold_final = nav_config.get("arrival_threshold_final_m", 0.3)        # Laatste waypoint

        # Staat het doel te ver naast onze neus, dan draaien we eerst op de
        # plek. Pure pursuit is daar niet geschikt voor: bij een koersfout van
        # bijna 180 graden wordt sin(alpha) juist weer klein en zou de robot
        # rechtdoor gaan rijden. Draaien op de plek kan een skid steer wél.
        self.spot_turn_threshold_deg = nav_config.get("spot_turn_threshold_deg", 60.0)
        self.spot_turn_yaw_dps = nav_config.get("spot_turn_yaw_rate_dps", 25.0)

        # De ZED-X20D levert positie en koers tot 25 Hz; de regellus mag dus
        # sneller dan de 10 Hz van de oude opstelling.
        self.loop_rate_hz = nav_config.get("loop_rate_hz", 20.0)
        self.min_fix_quality = nav_config.get("min_fix_quality", 2)

        # Missie status
        self.waypoints = []
        self.current_wp_index = 0
        self.target_speed_kmh = 0.0
        self.mode = "pure_pursuit"
        
        self.is_active = False
        self.nav_thread = None
        self.state = "IDLE"            # IDLE | WACHT_OP_FIX | RIJDEN | KLAAR | FOUT
        self.status_message = "Gestopt"

    def load_route(self, waypoints, speed_kmh):
        """
        Laadt een nieuwe route in.
        :param waypoints: Lijst met dicts [{"lat": 52.1, "lon": 4.1}, ...]
        """
        self.waypoints = waypoints
        self.current_wp_index = 0
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
        De hoofd-regellus. Berekent continu de positie,
        het volgende doel en de benodigde stuurcorrectie.
        """
        interval = 1.0 / max(1.0, self.loop_rate_hz)

        try:
            self._run_loop(interval)
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

    def _run_loop(self, interval):
        while self.is_active and self.current_wp_index < len(self.waypoints):
            start_time = time.time()

            # 1. Haal de nieuwste (hybride) GPS data op
            curr_pos = self.gps.get_current_position()

            if not curr_pos or curr_pos.get("lat") == 0.0 or curr_pos.get("fix", 0) < self.min_fix_quality:
                self.state = "WACHT_OP_FIX"
                self.status_message = (
                    f"Wachten op RTK-fix (fix={curr_pos.get('fix', 0) if curr_pos else 0})"
                )
                self.logger.warning("Wachten op goede GPS/RTK fix...")
                self.vehicle.drive(0.0, 0.0) # Veiligheid: stop met rijden bij slecht signaal
                time.sleep(0.5)
                continue

            # Zonder betrouwbare koers is elke stuurcorrectie een gok. Een skid
            # steer heeft niets wat hem mechanisch rechthoudt, dus dan stoppen
            # we liever. Met de ZED-X20D hoort dit zelden voor te komen: de
            # moving baseline werkt ook zonder RTK-fix.
            if not curr_pos.get("heading_geldig", True):
                self.state = "WACHT_OP_KOERS"
                self.status_message = "Wachten op geldige koers (THS)"
                self.logger.warning("Geen geldige koers van de GNSS-ontvanger.")
                self.vehicle.drive(0.0, 0.0)
                time.sleep(0.2)
                continue

            self.state = "RIJDEN"

            curr_lat = curr_pos["lat"]
            curr_lon = curr_pos["lon"]
            curr_heading = curr_pos["heading"]
            
            # 2. Bepaal het huidige doelpunt (Waypoint)
            target_wp = self.waypoints[self.current_wp_index]
            is_last_wp = (self.current_wp_index == len(self.waypoints) - 1)
            
            # 3. Bereken afstand en absolute richting (Bearing) naar waypoint
            distance = self._calculate_distance(curr_lat, curr_lon, target_wp["lat"], target_wp["lon"])
            target_bearing = self._calculate_bearing(curr_lat, curr_lon, target_wp["lat"], target_wp["lon"])
            
            # 4. Check of we zijn aangekomen bij het doelpunt
            threshold = self.arrival_threshold_final if is_last_wp else self.arrival_threshold_inter
            if distance <= threshold:
                self.logger.info(f"Waypoint {self.current_wp_index} bereikt (afstand: {distance:.2f}m).")
                self.current_wp_index += 1
                if self.current_wp_index >= len(self.waypoints):
                    self.state = "KLAAR"
                    self.status_message = "Eindbestemming bereikt"
                    self.logger.info("🏁 Eindbestemming bereikt! Missie voltooid.")
                    break # Verlaat de loop, we zijn klaar!
                continue # Direct doorrekenen naar volgende waypoint
                
            # 5. PURE PURSUIT BEREKENING
            # Alpha: De hoek tussen onze huidige neus en de lijn naar het doelpunt
            alpha = target_bearing - curr_heading
            alpha = (alpha + 180) % 360 - 180 # Normaliseer naar -180 tot +180 graden

            if abs(alpha) > self.spot_turn_threshold_deg:
                # Doel ligt (bijna) achter of ver opzij: eerst op de plek
                # indraaien, daarna pas rijden.
                yaw_dps = math.copysign(self.spot_turn_yaw_dps, alpha)
                self.vehicle.turn_in_place(yaw_dps)
                curvature = 0.0
                self.status_message = f"Indraaien naar doel ({alpha:.0f}°)"
            else:
                # Kromming van de boog door robot en doelpunt:
                #   kappa = 2 * sin(alpha) / lookahead   (+ = rechtsom)
                # De VehicleController maakt hier een snelheidsverschil tussen
                # links en rechts van, en remt af als de bocht te scherp wordt.
                curvature = 2.0 * math.sin(math.radians(alpha)) / self.lookahead_distance
                yaw_dps = math.degrees((self.target_speed_kmh / 3.6) * curvature)

                # 6. STUUR HET VOERTUIG AAN
                self.vehicle.drive_curvature(self.target_speed_kmh, curvature)

            # 7. LOGGING (Optioneel, overgenomen uit je oude code)
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
                        heading_doel=target_bearing,
                        heading_fout=alpha,
                        draai_dps=yaw_dps,
                        kromming=curvature,
                        doel_kmh=self.target_speed_kmh,
                        echt_kmh=curr_pos.get("speed_kmh", 0.0),
                        dac_links=self.vehicle.current_dac_links,
                        dac_rechts=self.vehicle.current_dac_rechts,
                        snelheid_links=self.vehicle.current_speed_links,
                        snelheid_rechts=self.vehicle.current_speed_rechts,
                        dist_wp=distance,
                        lookahead=self.lookahead_distance,
                        dt=(time.time() - start_time)
                    )
                except Exception as e:
                    self.logger.error(f"Fout bij loggen: {e}")
            
            # 8. Wacht strak tot het volgende 10Hz tick-moment
            elapsed = time.time() - start_time
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

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