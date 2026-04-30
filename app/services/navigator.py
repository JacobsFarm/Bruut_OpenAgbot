import math
import time
import threading

class Navigator:
    def __init__(self, gps_sys, motor_ctrl):
        self.gps = gps_sys
        self.motor = motor_ctrl
        self.waypoints = []
        self.base_pwm = 1500
        self.active = False
        self.thread = None
        self.last_pos = None

    def start(self, waypoints, base_pwm=1500):
        self.waypoints = waypoints
        self.base_pwm = base_pwm
        self.active = True
        self.last_pos = None
        self.thread = threading.Thread(target=self._navigate_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        self.motor.stop()

    def _haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    def _bearing(self, lat1, lon1, lat2, lon2):
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        l1 = math.radians(lon1)
        l2 = math.radians(lon2)
        y = math.sin(l2 - l1) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(l2 - l1)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def _navigate_loop(self):
        kp = 8.0
        wp_idx = 0
        
        while self.active and wp_idx < len(self.waypoints):
            curr = self.gps.current_position
            if curr["lat"] == 0.0 or curr["lon"] == 0.0:
                time.sleep(1)
                continue
                
            target = self.waypoints[wp_idx]
            dist = self._haversine(curr["lat"], curr["lon"], target["lat"], target["lon"])
            
            if dist < 1.0:
                wp_idx += 1
                continue
                
            if self.last_pos is None:
                self.last_pos = dict(curr)
                self.motor.stuur_motoren(self.base_pwm, self.base_pwm)
                time.sleep(1)
                continue
                
            moved_dist = self._haversine(self.last_pos["lat"], self.last_pos["lon"], curr["lat"], curr["lon"])
            if moved_dist < 0.2:
                time.sleep(0.5)
                continue

            current_heading = self._bearing(self.last_pos["lat"], self.last_pos["lon"], curr["lat"], curr["lon"])
            target_bearing = self._bearing(curr["lat"], curr["lon"], target["lat"], target["lon"])
            
            error = target_bearing - current_heading
            if error > 180:
                error -= 360
            if error < -180:
                error += 360
            
            turn = error * kp
            left_pwm = int(self.base_pwm + turn)
            right_pwm = int(self.base_pwm - turn)
            
            self.motor.stuur_motoren(left_pwm, right_pwm)
            self.last_pos = dict(curr)
            time.sleep(0.5)
            
        self.stop()