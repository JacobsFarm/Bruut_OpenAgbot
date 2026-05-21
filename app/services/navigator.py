import math
import time
import threading
from collections import deque
from app.services.logger import DriveLogger

# ============================================================
# NAVIGATOR V3 — Point-and-Shoot (Go-To-Goal) Logica
# voor skid-steer veldrobot met dual RTK-GPS.
#
# Gedrag:
#   1. Richten: Als neus > 15 graden afwijkt van doel -> 
#      Stilstaan en om as draaien (tank-turn).
#   2. Rijden: Als neus goed staat -> Snel vooruit en 
#      lichtjes bijsturen, wielen vallen niet meer stil.
#
# Logging:
#   De XTE (afwijking van de ideale doellijn) en het 
#   Look-Ahead punt worden nog wél op de achtergrond berekend
#   puur voor de logbestanden, maar NIET gebruikt om te sturen!
# ============================================================

# --- Gecalibreerde motoreigenschappen ---
DAC_MIN   = 1200    
DAC_MAX   = 3100    
DAC_RUST  = 700     
_DAC_SLOPE     = 1000.0   
_DAC_INTERCEPT = 0.96     

def speed_mps_to_dac(speed_mps: float) -> int:
    if speed_mps <= 0.0:
        return DAC_RUST
    dac = (speed_mps + _DAC_INTERCEPT) * _DAC_SLOPE
    return int(max(DAC_MIN, min(DAC_MAX, dac)))

class Navigator:
    def __init__(self, gps_sys, motor_ctrl):
        self.gps   = gps_sys
        self.motor = motor_ctrl
        self.logger = DriveLogger()
        self.waypoints = []

        self.doel_snelheid_kmh = 0.0
        self.active = False
        self.thread = None

        # ==========================================
        # --- TUNING PARAMETERS ---
        # ==========================================
        self.kp = 12.0               # Stuurkracht (Point-and-Shoot mag iets hoger staan)
        self.kd = 20.0               # Demping op draaisnelheid (yaw-rate)
        
        # Logging parameters (worden NIET meer gebruikt voor rijden)
        self.look_ahead_dist = 2.5   

        # Snelheid: PI Cruise Control
        self.kp_snelheid = 400.0
        self.ki_snelheid = 250.0
        self.max_pi_correctie = 600

        self._heading_buffer = deque(maxlen=5)

        # Interne status variabelen
        self._huidige_links  = DAC_RUST
        self._huidige_rechts = DAC_RUST
        self._vorige_actuele_positie   = None
        self._gefilterde_snelheid_mps  = 0.0
        self._speed_integraal = 0.0
        self._vorige_heading  = None   
        self._vorige_fout     = 0.0
        self._vorige_tijd     = None

    def start(self, waypoints, target_speed_kmh=3.0):
        self.logger.start_nieuwe_rit()
        self.waypoints = waypoints
        self.doel_snelheid_kmh = target_speed_kmh
        self._reset_state()
        self.active = True
        self.thread = threading.Thread(target=self._navigate_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        self.motor.stuur_motoren(DAC_RUST, DAC_RUST)

    def _reset_state(self):
        self._huidige_links  = DAC_RUST
        self._huidige_rechts = DAC_RUST
        self._vorige_fout    = 0.0
        self._vorige_tijd    = None
        self._vorige_actuele_positie   = None
        self._gefilterde_snelheid_mps  = 0.0
        self._speed_integraal = 0.0
        self._vorige_heading  = None
        self._heading_buffer.clear()

    # --- Wiskunde hulpfuncties ---
    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        R = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi   = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _bearing(lat1, lon1, lat2, lon2) -> float:
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        y = math.sin(dl) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    @staticmethod
    def _destination_point(lat, lon, bearing_deg, distance_m):
        R = 6_371_000.0
        d = distance_m / R
        b = math.radians(bearing_deg)
        phi1 = math.radians(lat)
        lam1 = math.radians(lon)
        phi2 = math.asin(math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(b))
        lam2 = lam1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(phi1), math.cos(d) - math.sin(phi1) * math.sin(phi2))
        return math.degrees(phi2), (math.degrees(lam2) + 540) % 360 - 180

    @staticmethod
    def _angle_diff(a, b) -> float:
        return (a - b + 180) % 360 - 180

    def _gefilterde_heading(self) -> float:
        raw = self.gps.current_heading
        if raw == 0.0: return 0.0
        if len(self._heading_buffer) == 0 or self._heading_buffer[-1] != raw:
            self._heading_buffer.append(raw)
        rads = [math.radians(h) for h in self._heading_buffer]
        sin_gem = sum(math.sin(r) for r in rads) / len(rads)
        cos_gem = sum(math.cos(r) for r in rads) / len(rads)
        return (math.degrees(math.atan2(sin_gem, cos_gem)) + 360) % 360

    # --- Achtergrond Logging Functies (Niet voor rijden!) ---
    def _bereken_xte(self, prev_wp, curr, target) -> tuple[float, float, float]:
        line_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
        line_length = self._haversine(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
        curr_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
        dist_from_prev = self._haversine(prev_wp["lat"], prev_wp["lon"], curr["lat"], curr["lon"])
        angle = math.radians(self._angle_diff(curr_bearing, line_bearing))
        
        dist_along_line = dist_from_prev * math.cos(angle)
        xte             = dist_from_prev * math.sin(angle)
        return xte, dist_along_line, line_length

    def _lookahead_punt(self, prev_wp, target, dist_along_line, xte) -> tuple[float, float]:
        line_bearing = self._bearing(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
        line_length = self._haversine(prev_wp["lat"], prev_wp["lon"], target["lat"], target["lon"])
        xte_clamped = min(abs(xte), self.look_ahead_dist * 0.99)
        forward_offset = math.sqrt(self.look_ahead_dist ** 2 - xte_clamped ** 2)
        target_dist = max(0.0, min(line_length, dist_along_line + forward_offset))
        
        la_lat, la_lon = self._destination_point(prev_wp["lat"], prev_wp["lon"], line_bearing, target_dist)
        return la_lat, la_lon

    def _smooth_dac(self, huidig: int, doel: int) -> int:
        if huidig < DAC_MIN and doel >= DAC_MIN: return DAC_MIN
        if doel <= DAC_RUST and huidig <= DAC_MIN: return DAC_RUST
        verschil = doel - huidig
        if verschil > 100: return huidig + 100
        elif verschil < -100: return huidig - 100
        return doel

    # ==================================================================
    # HOOFD NAVIGATIELUS
    # ==================================================================
    def _navigate_loop(self):
        wp_idx  = 0
        prev_wp = None

        while self.active and wp_idx < len(self.waypoints):
            curr = self.gps.current_position
            if curr["lat"] == 0.0 or curr["lon"] == 0.0:
                time.sleep(0.1)
                continue

            target = self.waypoints[wp_idx]
            if prev_wp is None:
                prev_wp = dict(curr)

            # ── Tijd & Snelheid ──
            now = time.time()
            dt = 0.1 if self._vorige_tijd is None else max(0.01, min(now - self._vorige_tijd, 0.5))

            if self._vorige_actuele_positie is not None:
                verplaatsing = self._haversine(self._vorige_actuele_positie["lat"], self._vorige_actuele_positie["lon"], curr["lat"], curr["lon"])
                self._gefilterde_snelheid_mps = (0.2 * (verplaatsing / dt)) + (0.8 * self._gefilterde_snelheid_mps)
            self._vorige_actuele_positie = dict(curr)

            # ── Waypoint bereikt? ──
            dist_to_target = self._haversine(curr["lat"], curr["lon"], target["lat"], target["lon"])
            if dist_to_target < 1.0:
                print(f"[NAVIGATOR] Waypoint {wp_idx} bereikt.")
                prev_wp = dict(target)
                wp_idx += 1
                self._vorige_fout    = 0.0
                self._vorige_tijd    = None
                self._vorige_heading = None
                self._speed_integraal = 0.0
                continue

            # ── Heading ophalen ──
            current_heading = self._gefilterde_heading()
            if current_heading == 0.0:
                self._huidige_links  = self._smooth_dac(self._huidige_links,  DAC_RUST)
                self._huidige_rechts = self._smooth_dac(self._huidige_rechts, DAC_RUST)
                self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)
                time.sleep(0.5)
                continue

            # ── ACHTERGROND: XTE & Look-Ahead berekenen puur voor log ──
            xte, dist_along, line_length = self._bereken_xte(prev_wp, curr, target)
            lookahead_lat, lookahead_lon = self._lookahead_punt(prev_wp, target, dist_along, xte)

            # ── POINT-AND-SHOOT: Richt rechtstreeks op het einddoel! ──
            direct_target_bearing = self._bearing(curr["lat"], curr["lon"], target["lat"], target["lon"])
            fout = self._angle_diff(direct_target_bearing, current_heading)

            yaw_rate = 0.0 if self._vorige_heading is None else self._angle_diff(current_heading, self._vorige_heading) / dt
            self._vorige_heading = current_heading
            self._vorige_fout = fout
            self._vorige_tijd = now

            # ==========================================================
            # POINT AND SHOOT STATE MACHINE
            # ==========================================================
            if abs(fout) > 80.0:
                # FASE 1: RICHTEN (Meer dan 15 graden afwijking -> stop met rijden, draai om de as)
                turn = (self.kp * 1.5 * fout) - (self.kd * yaw_rate)
                turn = max(-600, min(600, turn))
                
                doel_links  = int(DAC_RUST + turn)
                doel_rechts = int(DAC_RUST - turn)
                
                pi_correctie = 0.0
                huidige_fase_kmh = 0.0 # We staan stil qua vooruit rijden
                
            else:
                # FASE 2: RIJDEN (We wijzen de goede kant op -> gas erop en koers houden)
                turn = (self.kp * fout) - (self.kd * yaw_rate)
                turn = max(-250, min(250, turn)) # Zachtere correctie tijdens rijden
                
                doel_snelheid_mps = self.doel_snelheid_kmh / 3.6
                basis_dac = speed_mps_to_dac(doel_snelheid_mps)

                snelheids_fout = doel_snelheid_mps - self._gefilterde_snelheid_mps
                
                pi_onbegrensd = (self.kp_snelheid * snelheids_fout) + (self.ki_snelheid * self._speed_integraal)
                if abs(pi_onbegrensd) < self.max_pi_correctie:
                    self._speed_integraal += snelheids_fout * dt
                    self._speed_integraal = max(-2.0, min(2.0, self._speed_integraal))

                pi_correctie = max(-self.max_pi_correctie, min(self.max_pi_correctie, pi_onbegrensd))
                actuele_base_dac = basis_dac + pi_correctie

                doel_links  = int(actuele_base_dac + turn)
                doel_rechts = int(actuele_base_dac - turn)

                # Voorkom dat wielen blokkeren tijdens het rijden (Anti-Pivot)
                MIN_ROLLEND_DAC = 1250 
                if doel_links < MIN_ROLLEND_DAC: 
                    doel_links = MIN_ROLLEND_DAC
                if doel_rechts < MIN_ROLLEND_DAC:
                    doel_rechts = MIN_ROLLEND_DAC
                    
                huidige_fase_kmh = self.doel_snelheid_kmh
            # ==========================================================

            # ── Hardware limieten & Smoothing ──
            doel_links  = max(DAC_RUST, min(DAC_MAX, doel_links))
            doel_rechts = max(DAC_RUST, min(DAC_MAX, doel_rechts))

            self._huidige_links  = self._smooth_dac(self._huidige_links,  doel_links)
            self._huidige_rechts = self._smooth_dac(self._huidige_rechts, doel_rechts)

            self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)

            # ── 6. LOGGING (Alle kolommen netjes gevuld) ──
            actuele_kmh = self._gefilterde_snelheid_mps * 3.6
            
            self.logger.log_regel(
                wp_idx=wp_idx,
                lat=curr["lat"],
                lon=curr["lon"],
                fix=curr.get("fix",  0),
                hdop=curr.get("hdop", 99.0),
                heading=current_heading,
                doel_heading=direct_target_bearing,
                fout=fout,
                xte=xte,                          # Opgeslagen puur voor analyse
                doel_kmh=huidige_fase_kmh,
                echt_kmh=actuele_kmh,
                turn=turn,
                pi_corr=pi_correctie,
                i_term=self._speed_integraal,
                links=self._huidige_links,
                rechts=self._huidige_rechts,
                dist=dist_to_target,
                dt=dt,
                lookahead_lat=lookahead_lat,      # Opgeslagen puur voor analyse
                lookahead_lon=lookahead_lon       # Opgeslagen puur voor analyse
            )

            print(
                f"[NAV] hdg={current_heading:.1f}° fout={fout:.1f}° xte={xte:.2f}m "
                f"L={self._huidige_links} R={self._huidige_rechts} turn={turn:.0f}"
            )

            time.sleep(0.1)

        self.stop()
