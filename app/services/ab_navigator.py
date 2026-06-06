import math
import time
import json
import threading
import logging
import os

try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

class ABNavigator:
    def __init__(self, gps_system, vehicle_controller, config):
        self.logger = logging.getLogger(__name__)
        self.drive_logger = DriveLogger() if DriveLogger else None
        
        self.gps = gps_system
        self.vehicle = vehicle_controller
        
        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)
        self.max_angle = config.get("steering", {}).get("max_angle_degrees", 45.0)
        
        self.work_width_m = 4.0
        self.field_length_m = 50.0
        self.target_speed_kmh = 3.0
        self.turn_speed_kmh = 2.0
        self.lookahead_m = 2.5
        self.tolerance_m = 0.2
        
        self.is_active = False
        self.nav_thread = None
        self.state = "IDLE"
        
        self.ref_lat = 0.0
        self.ref_lon = 0.0
        self.line_heading_rad = 0.0
        self.current_swath = 0
        self.turn_waypoints = []

    def set_ab_line(self, lat_a, lon_a, lat_b, lon_b):
        if None in [lat_a, lon_a, lat_b, lon_b]:
            return False
            
        self.ref_lat = lat_a
        self.ref_lon = lon_a
        
        xb, yb = self._latlon_to_xy(lat_b, lon_b)
        self.line_heading_rad = math.atan2(yb, xb)
        
        self.current_swath = 0
        return True

    def start_mission(self, work_width, field_length, speed):
        self.work_width_m = work_width
        self.field_length_m = field_length
        self.target_speed_kmh = speed
        self.current_swath = 0
        self.state = "TRACKING"
        
        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="AB_Missie")
            
        if self.is_active:
            self.stop()
            
        self.is_active = True
        self.nav_thread = threading.Thread(target=self._navigation_loop, daemon=True)
        self.nav_thread.start()

    def stop(self):
        self.is_active = False
        self.state = "IDLE"
        if self.nav_thread and self.nav_thread.is_alive():
            self.nav_thread.join(timeout=1.0)
        self.vehicle.stop()
        if self.drive_logger:
            self.drive_logger.stop_log()

    def _navigation_loop(self):
        rate_hz = 10.0
        interval = 1.0 / rate_hz
        
        while self.is_active:
            start_time = time.time()
            curr_pos = self.gps.get_current_position()
            
            if not curr_pos or curr_pos.get("fix", 0) < 2:
                self.vehicle.drive(0.0, 0.0)
                time.sleep(0.1)
                continue
                
            x_bot, y_bot = self._latlon_to_xy(curr_pos["lat"], curr_pos["lon"])
            heading_bot_rad = math.radians(curr_pos["heading"])
            
            if self.state == "TRACKING":
                self._handle_tracking(x_bot, y_bot, heading_bot_rad, curr_pos)
            elif self.state == "TURNING":
                self._handle_turning(x_bot, y_bot, heading_bot_rad, curr_pos)

            elapsed = time.time() - start_time
            time.sleep(max(0.01, interval - elapsed))
            
        self.vehicle.stop()

    def _handle_tracking(self, x, y, heading_rad, raw_gps):
        offset_distance = self.current_swath * self.work_width_m
        
        distance_along_line = x * math.cos(self.line_heading_rad) + y * math.sin(self.line_heading_rad)
        
        distance_perpendicular = -x * math.sin(self.line_heading_rad) + y * math.cos(self.line_heading_rad)
        xte = distance_perpendicular - offset_distance
        
        if distance_along_line >= self.field_length_m:
            self._generate_turn_path(distance_along_line, offset_distance)
            self.state = "TURNING"
            return
            
        target_along = distance_along_line + self.lookahead_m
        target_x = target_along * math.cos(self.line_heading_rad) - offset_distance * math.sin(self.line_heading_rad)
        target_y = target_along * math.sin(self.line_heading_rad) + offset_distance * math.cos(self.line_heading_rad)
        
        alpha = math.atan2(target_y - y, target_x - x) - heading_rad
        alpha = (alpha + math.pi) % (2 * math.pi) - math.pi
        
        steering_angle = math.degrees(math.atan2(2.0 * self.wheelbase * math.sin(alpha), self.lookahead_m))
        
        if abs(xte) < self.tolerance_m:
            steering_angle *= 0.5
            
        final_angle = max(-self.max_angle, min(self.max_angle, steering_angle))
        self.vehicle.drive(self.target_speed_kmh, final_angle)

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=raw_gps["lat"], lon=raw_gps["lon"],
                fix=raw_gps.get("fix", 0), hdop=raw_gps.get("hdop", 99.0),
                heading_echt=raw_gps["heading"], heading_doel=math.degrees(self.line_heading_rad),
                heading_fout=xte, stuurhoek=final_angle, doel_kmh=self.target_speed_kmh,
                echt_kmh=raw_gps.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links, dac_rechts=self.vehicle.current_dac_rechts,
                dist_wp=distance_along_line, lookahead=self.lookahead_m, dt=0.1
            )

    def _generate_turn_path(self, current_length, current_offset):
        self.turn_waypoints = []
        next_swath = self.current_swath + 1
        self.current_swath = next_swath

    def _handle_turning(self, x, y, heading_rad, raw_gps):
        self.line_heading_rad = (self.line_heading_rad + math.pi) % (2 * math.pi)
        self.state = "TRACKING"

    def _latlon_to_xy(self, lat, lon):
        r_earth = 6371000.0
        lat_rad = math.radians(lat)
        ref_lat_rad = math.radians(self.ref_lat)
        lon_rad = math.radians(lon)
        ref_lon_rad = math.radians(self.ref_lon)
        
        x = r_earth * (lon_rad - ref_lon_rad) * math.cos((lat_rad + ref_lat_rad) / 2.0)
        y = r_earth * (lat_rad - ref_lat_rad)
        return x, y