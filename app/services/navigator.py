import math
import time
import threading
from collections import deque

class Navigator:
    def __init__(self, gps_sys, motor_ctrl):
        self.gps = gps_sys
        self.motor = motor_ctrl
        self.waypoints = []
        self.base_pwm = 1500
        self.active = False
        self.thread = None

        # ==========================================
        # --- JOUW TUNING PARAMETERS VOOR HET VELD ---
        # ==========================================
        self.kp = 4.0      # Stuurkracht: Hoe hard stuurt hij naar de doellijn?
        self.kd = 8.0      # Schokbreker: Hoe hard remt hij de draai af? (Skid-steer zweepslag filter)
        self.k_xte = 20.0  # Lijn-compensatie: Extra graden tegensturen per meter naast de lijn
        
        # --- GPS Filtering ---
        self._heading_buffer = deque(maxlen=4)

        # --- PWM smoothing ---
        self._max_pwm_stap = 30 # Maximaal toegestane PWM-sprong per 0.1 seconde
        self._huidige_links = None
        self._huidige_rechts = None

        # --- PD state ---
        self._vorige_fout = 0.0
        self._vorige_tijd = None

    def start(self, waypoints, base_pwm=1500):
        self.waypoints = waypoints
        self.base_pwm = base_pwm
        self._huidige_links = base_pwm
        self._huidige_rechts = base_pwm
        self._vorige_fout = 0.0
        self._vorige_tijd = None
        self._heading_buffer.clear()
        self.active = True
        self.thread = threading.Thread(target=self._navigate_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        # NOODSTOP: De hardware rem wordt geactiveerd met 700!
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

        # Alleen toevoegen als de waarde nieuw is (voorkomt stale data in buffer bij 1Hz)
        if len(self._heading_buffer) == 0 or math.degrees(self._heading_buffer[-1]) != raw:
            self._heading_buffer.append(math.radians(raw))

        sin_gem = sum(math.sin(h) for h in self._heading_buffer) / len(self._heading_buffer)
        cos_gem = sum(math.cos(h) for h in self._heading_buffer) / len(self._heading_buffer)
        return (math.degrees(math.atan2(sin_gem, cos_gem)) + 360) % 360

    def _smooth_pwm(self, doel_links, doel_rechts):
        def stap(huidig, doel):
            delta = doel - huidig
            delta = max(-self._max_pwm_stap, min(self._max_pwm_stap, delta))
            return huidig + delta

        self._huidige_links  = stap(self._huidige_links,  doel_links)
        self._huidige_rechts = stap(self._huidige_rechts, doel_rechts)
        return int(self._huidige_links), int(self._huidige_rechts)

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
            
            # Stel initieel startpunt in voor de allereerste lijn
            if prev_wp is None:
                prev_wp = dict(curr)

            dist = self._haversine(curr["lat"], curr["lon"], target["lat"], target["lon"])

            if dist < 1.0:
                print(f"[NAVIGATOR] Waypoint {wp_idx} bereikt.")
                prev_wp = dict(target) # Huidig doel wordt startpunt voor volgende lijn
                wp_idx += 1
                self._vorige_fout = 0.0
                self._vorige_tijd = None
                continue

            current_heading = self._gefilterde_heading()

            if current_heading == 0.0:
                print("[NAVIGATOR] Wachten op Dual-GPS heading...")
                self.motor.stuur_motoren(1500, 1500)
                time.sleep(0.5)
                continue

            # 1. Bepaal lijn tussen vorige WP en target WP
            target_bearing = self._bearing(curr["lat"], curr["lon"], target["lat"], target["lon"])
            line_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
            curr_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
            dist_from_prev = self._haversine(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
            
            # 2. Cross-Track Error (XTE) compensatie
            angle_diff = math.radians(curr_bearing - line_bearing)
            xte = math.asin(math.sin(dist_from_prev / 6371000) * math.sin(angle_diff)) * 6371000
            
            correction = max(-50.0, min(50.0, xte * self.k_xte))
            corrected_target_bearing = (target_bearing - correction) % 360

            # 3. Fout berekenen
            fout = corrected_target_bearing - current_heading
            if fout > 180: fout -= 360
            if fout < -180: fout += 360

            # 4. PD regelaar met tijdsdelta
            now = time.time()
            if self._vorige_tijd is None:
                dt = 0.1
            else:
                dt = max(0.01, min(now - self._vorige_tijd, 0.5))

            d_fout = (fout - self._vorige_fout) / dt
            self._vorige_fout = fout
            self._vorige_tijd = now

            turn = (self.kp * fout) + (self.kd * d_fout)
            turn = max(-200, min(200, turn))

            # 5. Skid-steer Bocht-vertraging (Geef de robot koppel om te draaien)
            hoek_penalty = min(1.0, abs(fout) / 30.0) 
            snelheids_factor = 1.0 - (hoek_penalty * 0.5) 
            actuele_base_pwm = 1500 + ((self.base_pwm - 1500) * snelheids_factor)

            doel_links  = actuele_base_pwm + turn
            doel_rechts = actuele_base_pwm - turn

            # 6. Zachte PWM-overgang
            links, rechts = self._smooth_pwm(doel_links, doel_rechts)

            # Veiligheid
            links = max(1000, min(2000, links))
            rechts = max(1000, min(2000, rechts))

            # 7. Aandrijving
            self.motor.stuur_motoren(links, rechts)

            # Debug output terminal
            print(f"[NAV] hdg={current_heading:.1f}° doel={target_bearing:.1f}° "
                  f"fout={fout:.1f}° xte={xte:.2f}m d_fout={d_fout:.2f} "
                  f"turn={turn:.0f} L={links} R={rechts} dist={dist:.2f}m")

            time.sleep(0.1)

        self.stop()