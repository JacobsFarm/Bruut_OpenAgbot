import math
import time
import threading
import logging
from app.services.logger import DriveLogger

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
    def __init__(self, gps_sys, motor_ctrl, stuur_ctrl):
        self.gps = gps_sys
        self.motor = motor_ctrl
        self.stuur = stuur_ctrl
        self.logger = DriveLogger()
        
        self.waypoints = []
        self.mode = "pure_pursuit"
        self.doel_snelheid_kmh = 0.0
        
        self.lookahead_distance = 1.5
        self.tuning_gain = 1.0
        
        # --- NIEUW: Elektronisch Differentieel ---
        # 0.0 = geen verschil (beide wielen even snel). 
        # 0.4 = binnenste wiel mag in een maximale bocht tot 40% langzamer draaien.
        self.differentieel_sterkte = 0.0 
        self.max_stuurhoek = 45.0 # Gebruikt om te berekenen hoe "scherp" de bocht is
        
        self.active = False
        self.thread = None
        self._huidige_dac_links = DAC_RUST
        self._huidige_dac_rechts = DAC_RUST
        self.logger_agent = logging.getLogger(__name__)

    # ... (start, update_sliders, stop blijven exact hetzelfde als eerder) ...
    def start(self, waypoints, mode="pure_pursuit", target_speed_kmh=2.0, lookahead_distance=1.5, gain=1.0):
        self.waypoints = waypoints
        self.mode = mode
        self.doel_snelheid_kmh = target_speed_kmh
        self.lookahead_distance = lookahead_distance
        self.tuning_gain = gain
        
        if not self.active:
            self.active = True
            try:
                self.logger.start_nieuwe_rit(navigatie_modus=mode)
            except Exception:
                pass
            self.thread = threading.Thread(target=self._nav_loop, daemon=True)
            self.thread.start()
            self.logger_agent.info(f"Autonome navigatie gestart. Modus: {mode}")

    def update_sliders(self, target_speed_kmh=None, lookahead_distance=None, gain=None):
        if target_speed_kmh is not None: self.doel_snelheid_kmh = target_speed_kmh
        if lookahead_distance is not None: self.lookahead_distance = lookahead_distance
        if gain is not None: self.tuning_gain = gain

    def stop(self):
        self.active = False
        if self.thread:
            self.thread.join(timeout=1.0)
        self.motor.stuur_motoren(DAC_RUST, DAC_RUST)
        self.stuur.set_angle(0.0)
        self.logger_agent.info("Autonome navigatie gestopt. Motoren neutraal.")

    def _smooth_dac(self, huidig, doel):
        """Voorkomt te hard optrekken / remmen"""
        if doel > huidig:
            return min(doel, huidig + 120)
        elif doel < huidig:
            return max(doel, huidig - 180)
        return huidig

    def _nav_loop(self):
        wp_idx = 0
        R_EARTH = 6371000.0
        
        while self.active:
            start_time = time.time()
            
            curr = self.gps.current_position
            current_heading = self.gps.current_heading
            
            if not curr or curr.get("fix", 0) < 4:
                self.motor.stuur_motoren(DAC_RUST, DAC_RUST)
                time.sleep(0.1)
                continue
                
            if wp_idx >= len(self.waypoints):
                self.stop()
                break
                
            target_wp = self.waypoints[wp_idx]
            
            # Wiskunde voor afstand en hoek (blijft hetzelfde)
            lat1, lon1 = math.radians(curr["lat"]), math.radians(curr["lon"])
            lat2, lon2 = math.radians(target_wp["lat"]), math.radians(target_wp["lon"])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            dist_to_target = R_EARTH * c
            
            y_brg = math.sin(dlon) * math.cos(lat2)
            x_brg = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
            target_bearing = math.degrees(math.atan2(y_brg, x_brg))
            target_bearing = (target_bearing + 360) % 360
            
            fout_graden = target_bearing - current_heading
            if fout_graden > 180: fout_graden -= 360
            elif fout_graden < -180: fout_graden += 360
            
            doel_stuurhoek = 0.0
            
            if self.mode == "point_to_point":
                doel_stuurhoek = fout_graden * self.tuning_gain
                if dist_to_target < 0.6: wp_idx += 1
                    
            elif self.mode == "pure_pursuit":
                alpha_rad = math.radians(fout_graden)
                wheelbase = 1.1 
                num = 2.0 * wheelbase * math.sin(alpha_rad)
                den = max(0.2, self.lookahead_distance) 
                doel_stuurhoek = math.degrees(math.atan2(num, den)) * self.tuning_gain
                
                if dist_to_target < max(0.5, self.lookahead_distance * 0.7):
                    wp_idx += 1
            
            # 1. Stuurhoek doorgeven
            # Beperk voor wiskunde de stuurhoek tot het absolute maximum
            gelimiteerde_stuurhoek = max(-self.max_stuurhoek, min(self.max_stuurhoek, doel_stuurhoek))
            self.stuur.set_angle(gelimiteerde_stuurhoek)
            
            # 2. Snelheid en Elektronisch Differentieel verwerken
            target_mps = self.doel_snelheid_kmh / 3.6
            mps_links = target_mps
            mps_rechts = target_mps

            if self.differentieel_sterkte > 0.0 and target_mps > 0:
                # Bereken hoe scherp we sturen (0.0 = rechtuit, 1.0 = maximale uitslag)
                draai_factor = abs(gelimiteerde_stuurhoek) / self.max_stuurhoek
                snelheids_reductie = 1.0 - (draai_factor * self.differentieel_sterkte)

                if gelimiteerde_stuurhoek > 2.0:
                    # Stuur rechts = rechts is binnenbocht, dus rechts draait langzamer
                    mps_rechts = target_mps * snelheids_reductie
                elif gelimiteerde_stuurhoek < -2.0:
                    # Stuur links = links is binnenbocht, dus links draait langzamer
                    mps_links = target_mps * snelheids_reductie
            
            # Bereken individuele DAC waarden
            doel_dac_links = speed_mps_to_dac(mps_links)
            doel_dac_rechts = speed_mps_to_dac(mps_rechts)
            
            # Snelheids-smoothing per wiel apart
            self._huidige_dac_links = self._smooth_dac(self._huidige_dac_links, doel_dac_links)
            self._huidige_dac_rechts = self._smooth_dac(self._huidige_dac_rechts, doel_dac_rechts)
                
            self.motor.stuur_motoren(self._huidige_dac_links, self._huidige_dac_rechts)
            
            try:
                elapsed = time.time() - start_time
                self.logger.log_regel(
                    wp_idx=wp_idx, modus=self.mode, lat=curr["lat"], lon=curr["lon"], 
                    fix=curr.get("fix", 0), hdop=curr.get("hdop", 99.0), 
                    heading_echt=current_heading, heading_doel=target_bearing,
                    heading_fout=fout_graden, stuurhoek=gelimiteerde_stuurhoek, 
                    doel_kmh=self.doel_snelheid_kmh, echt_kmh=target_mps * 3.6,
                    dac_links=self._huidige_dac_links, dac_rechts=self._huidige_dac_rechts, # <-- Nu gesplitst gelogd!
                    dist_wp=dist_to_target, 
                    lookahead=self.lookahead_distance if self.mode == "pure_pursuit" else 0.0,
                    dt=elapsed
                )
            except Exception as e:
                pass
                
            elapsed = time.time() - start_time
            time.sleep(max(0.01, 0.1 - elapsed))