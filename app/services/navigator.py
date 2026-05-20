import math
import time
import threading
from collections import deque
from app.services.logger import DriveLogger

class Navigator:
    def __init__(self, gps_sys, motor_ctrl):
        self.gps = gps_sys
        self.motor = motor_ctrl
        self.logger = DriveLogger() # Koppel de telemetrie logger
        self.waypoints = []
        
        # State variabelen
        self.doel_snelheid_kmh = 0.0
        self.active = False
        self.thread = None

        # ==========================================
        # --- GEOPTIMALISEERDE TUNING PARAMETERS ---
        # ==========================================
        # STUREN (PD-Regelaar)
        self.kp = 12.0     # Agressiever terugsturen naar de lijn
        self.kd = 18.0     # Zwaardere schokbreker om slingeren te voorkomen
        self.k_xte = 10.0  # Iets zachtere reactie op XTE meters (voorkomt paniek)
        
        # SNELHEID CRUISE CONTROL (PI-Regelaar)
        self.kp_snelheid = 500.0  # Gas bijgeven als hij afwijkt (bijv. door modder)
        self.ki_snelheid = 250.0  # Geheugen: bouwt extra gas op als hij structureel traag blijft

        # --- GPS Filtering ---
        self._heading_buffer = deque(maxlen=4)

        # --- Actuele status ---
        self._huidige_links = 700
        self._huidige_rechts = 700
        self._vorige_actuele_positie = None
        self._gefilterde_snelheid_mps = 0.0 # Gemeten GPS snelheid in meter/seconde
        self._speed_integraal = 0.0         # Geheugen voor de Cruise Control

        # --- Stuur state ---
        self._vorige_fout = 0.0
        self._vorige_tijd = None

    def kmh_naar_dac(self, kmh):
        """Zet de theoretische snelheid om naar een DAC basiswaarde (Feedforward)"""
        if kmh <= 0.1:
            return 700 
            
        dac = (kmh / 3.6 + 0.96) * 1000
        # 1200 is het fysieke motor startpunt
        return max(1200, min(3100, int(dac)))

    def start(self, waypoints, target_speed_kmh=3.0):
        # Maak een nieuwe CSV log aan voor deze rit
        self.logger.start_nieuwe_rit()
        
        self.waypoints = waypoints
        self.doel_snelheid_kmh = target_speed_kmh
        
        # Reset waardes voor een schone start
        self._huidige_links = 700
        self._huidige_rechts = 700
        self._vorige_fout = 0.0
        self._vorige_tijd = None
        self._vorige_actuele_positie = None
        self._gefilterde_snelheid_mps = 0.0
        self._speed_integraal = 0.0
        self._heading_buffer.clear()
        
        self.active = True
        self.thread = threading.Thread(target=self._navigate_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        self.motor.stuur_motoren(700, 700) 

    # ------------------------------------------------------------------
    # Wiskunde Hulpfuncties
    # ------------------------------------------------------------------
    def _haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    def _bearing(self, lat1, lon1, lat2, lon2):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        l1, l2 = math.radians(lon1), math.radians(lon2)
        y = math.sin(l2 - l1) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(l2 - l1)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    # ------------------------------------------------------------------
    # Filtering & Smoothing
    # ------------------------------------------------------------------
    def _gefilterde_heading(self):
        raw = self.gps.current_heading
        if raw == 0.0:
            return 0.0

        if len(self._heading_buffer) == 0 or math.degrees(self._heading_buffer[-1]) != raw:
            self._heading_buffer.append(math.radians(raw))

        sin_gem = sum(math.sin(h) for h in self._heading_buffer) / len(self._heading_buffer)
        cos_gem = sum(math.cos(h) for h in self._heading_buffer) / len(self._heading_buffer)
        return (math.degrees(math.atan2(sin_gem, cos_gem)) + 360) % 360

    def _smooth_dac(self, huidig, doel):
        if huidig < 1200 and doel >= 1200:
            huidig = 1200
            
        if doel <= 700 and huidig <= 1200:
            return 700
            
        verschil = doel - huidig
        if verschil > 100:
            return huidig + 100
        elif verschil < -100:
            return huidig - 100
        else:
            return doel

    # ------------------------------------------------------------------
    # Hoofd navigatielus
    # ------------------------------------------------------------------
    def _navigate_loop(self):
        wp_idx = 0
        prev_wp = None

        while self.active and wp_idx < len(self.waypoints):
            curr = self.gps.current_position
            if curr["lat"] == 0.0 or curr["lon"] == 0.0:
                time.sleep(0.1)
                continue

            target = self.waypoints[wp_idx]
            if prev_wp is None:
                prev_wp = dict(curr)

            # Tijd en afstand sinds vorige loop meten (Voor Snelheid en Sturen)
            now = time.time()
            if self._vorige_tijd is None:
                dt = 0.1
            else:
                dt = max(0.01, min(now - self._vorige_tijd, 0.5))
            
            # --- 1. WERKELIJKE GPS SNELHEID BEREKENEN ---
            if self._vorige_actuele_positie is not None:
                verplaatsing = self._haversine(self._vorige_actuele_positie["lat"], self._vorige_actuele_positie["lon"], curr["lat"], curr["lon"])
                ruwe_snelheid_mps = verplaatsing / dt
                # Filter om GPS ruis in kleine stapjes glad te strijken
                self._gefilterde_snelheid_mps = (0.2 * ruwe_snelheid_mps) + (0.8 * self._gefilterde_snelheid_mps)
            
            self._vorige_actuele_positie = dict(curr)

            dist_to_target = self._haversine(curr["lat"], curr["lon"], target["lat"], target["lon"])

            if dist_to_target < 1.0:
                print(f"[NAVIGATOR] Waypoint {wp_idx} bereikt.")
                prev_wp = dict(target) 
                wp_idx += 1
                self._vorige_fout = 0.0
                self._vorige_tijd = None
                self._speed_integraal = 0.0 # Reset geheugen bij nieuw waypoint
                continue

            current_heading = self._gefilterde_heading()

            if current_heading == 0.0:
                print("[NAVIGATOR] Wachten op Dual-GPS heading...")
                self._huidige_links = self._smooth_dac(self._huidige_links, 700)
                self._huidige_rechts = self._smooth_dac(self._huidige_rechts, 700)
                self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)
                time.sleep(0.5)
                continue

            # --- 2. STUUR LOGICA (Lijn volgen) ---
            target_bearing = self._bearing(curr["lat"], curr["lon"], target["lat"], target["lon"])
            line_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
            curr_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
            dist_from_prev = self._haversine(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
            
            angle_diff = math.radians(curr_bearing - line_bearing)
            xte = math.asin(math.sin(dist_from_prev / 6371000) * math.sin(angle_diff)) * 6371000
            
            correction = max(-50.0, min(50.0, xte * self.k_xte))
            corrected_target_bearing = (target_bearing - correction) % 360

            fout = corrected_target_bearing - current_heading
            if fout > 180: fout -= 360
            if fout < -180: fout += 360

            d_fout = (fout - self._vorige_fout) / dt
            self._vorige_fout = fout
            self._vorige_tijd = now

            turn = (self.kp * fout) + (self.kd * d_fout)
            turn = max(-400, min(400, turn))

            # --- 3. DYNAMISCHE SNELHEID & CRUISE CONTROL ---
            # Versoepelde bochten-rem: Remt pas maximaal af bij 35 graden fout (was 20)
            hoek_penalty = min(1.0, abs(fout) / 35.0) 
            snelheids_factor = max(0.0, 1.0 - (hoek_penalty * 0.8))
            
            doel_snelheid_mps = (self.doel_snelheid_kmh / 3.6) * snelheids_factor
            basis_theoretische_dac = self.kmh_naar_dac(doel_snelheid_mps * 3.6)

            # PI Regelaar om afwijking te corrigeren
            snelheids_fout = doel_snelheid_mps - self._gefilterde_snelheid_mps
            
            self._speed_integraal += snelheids_fout * dt
            self._speed_integraal = max(-1.0, min(1.0, self._speed_integraal))

            pi_correctie = (self.kp_snelheid * snelheids_fout) + (self.ki_snelheid * self._speed_integraal)
            actuele_base_dac = basis_theoretische_dac + pi_correctie

            # --- 4. MOTOREN AANSTUREN ---
            doel_links  = actuele_base_dac + turn
            doel_rechts = actuele_base_dac - turn

            # --- Actieve Stuur-Behoud (Drag-Wheel Fix op 1300 DAC) ---
            if self.doel_snelheid_kmh > 0.1:
                if doel_links < 1300:
                    tekort = 1300 - doel_links
                    doel_links = 1300
                    doel_rechts += tekort
                elif doel_rechts < 1300:
                    tekort = 1300 - doel_rechts
                    doel_rechts = 1300
                    doel_links += tekort

            # Harde veiligheidslimieten van de hardware (700 = noodstop, 3100 = motor max)
            doel_links = int(max(700, min(3100, doel_links)))
            doel_rechts = int(max(700, min(3100, doel_rechts)))

            # Toepassen van de "Stapjes van 100" smoothing zodat correcties vloeiend verlopen
            self._huidige_links = self._smooth_dac(self._huidige_links, doel_links)
            self._huidige_rechts = self._smooth_dac(self._huidige_rechts, doel_rechts)

            self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)

            # --- 5. DATA LOGGEN ---
            actuele_kmh = self._gefilterde_snelheid_mps * 3.6
            huidige_fix = curr.get("fix", 0)
            huidige_hdop = curr.get("hdop", 99.0)

            self.logger.log_regel(
                wp_idx=wp_idx,
                lat=curr["lat"],
                lon=curr["lon"],
                fix=huidige_fix,
                hdop=huidige_hdop,
                heading=current_heading,
                doel_heading=target_bearing,
                fout=fout,
                xte=xte,
                doel_kmh=self.doel_snelheid_kmh,
                echt_kmh=actuele_kmh,
                turn=turn,
                pi_corr=pi_correctie,
                i_term=self._speed_integraal,
                links=self._huidige_links,
                rechts=self._huidige_rechts,
                dist=dist_to_target,
                dt=dt
            )

            print(f"[NAV] hdg={current_heading:.1f}° fout={fout:.1f}° "
                  f"Doel={doel_snelheid_mps * 3.6:.1f} Echt={actuele_kmh:.1f} "
                  f"PICorr={pi_correctie:.0f} L={self._huidige_links} R={self._huidige_rechts}")

            time.sleep(0.1)

        self.stop()