import threading
import serial
import time
import socket
import base64
import math

class GpsSystem:
    def __init__(self, config):
        self.gps_port = config['hardware']['gps_port']
        # Haal de tweede poort op (met fallback voor als hij niet in config staat)
        self.gps_heading_port = config['hardware'].get('gps_heading_port', None)
        self.gps_baudrate = config['hardware']['gps_baudrate']
        self.ntrip_cfg = config['ntrip']
        
        self.ser_main = None
        self.ser_heading = None
        
        self.current_position = {"lat": 0.0, "lon": 0.0, "fix": 0, "hdop": 99.0}
        self.heading_position = {"lat": 0.0, "lon": 0.0, "fix": 0}
        
        # De live kompasrichting van de AgBot
        self.current_heading = 0.0 
        
        self._running = False
        self.connect()

    def connect(self):
        try:
            self.ser_main = serial.Serial(self.gps_port, self.gps_baudrate, timeout=1)
            print(f"[GPS] Main (Achter) verbonden op {self.gps_port}")
            
            if self.gps_heading_port:
                self.ser_heading = serial.Serial(self.gps_heading_port, self.gps_baudrate, timeout=1)
                print(f"[GPS] Heading (Voor) verbonden op {self.gps_heading_port}")

            self._running = True
            
            # Start achtergrond threads
            threading.Thread(target=self._lees_main_gps, daemon=True).start()
            if self.ser_heading:
                threading.Thread(target=self._lees_heading_gps, daemon=True).start()
            
            threading.Thread(target=self._start_ntrip, daemon=True).start()
        except Exception as e:
            print(f"[GPS ERROR] Kan niet verbinden: {e}")

    def _lees_main_gps(self):
        """Leest NMEA data van het 10Hz F9P board achterop"""
        while self._running and self.ser_main and self.ser_main.is_open:
            try:
                raw_bytes = self.ser_main.readline()
                if not raw_bytes: continue
                raw_text = raw_bytes.decode("ascii", errors="ignore").strip()
                
                if raw_text.startswith("$GNGGA") or raw_text.startswith("$GPGGA"):
                    self._parse_gga(raw_text)
            except Exception:
                time.sleep(0.1)

    def _lees_heading_gps(self):
        """Leest binaire UBX data van het 1Hz X20D board voorop"""
        while self._running and self.ser_heading and self.ser_heading.is_open:
            try:
                if self.ser_heading.read(1) == b'\xb5' and self.ser_heading.read(1) == b'\x62':
                    cls, id = self.ser_heading.read(1), self.ser_heading.read(1)
                    length = int.from_bytes(self.ser_heading.read(2), 'little')
                    payload = self.ser_heading.read(length)
                    self.ser_heading.read(2) # Checksum overslaan
                    
                    # NAV-PVT Bericht
                    if cls == b'\x01' and id == b'\x07' and len(payload) >= 32:
                        flags = payload[21]
                        quality = (flags >> 6) & 0x03 # RTK Status
                        
                        lon_int = int.from_bytes(payload[24:28], 'little', signed=True)
                        lat_int = int.from_bytes(payload[28:32], 'little', signed=True)
                        
                        self.heading_position["lon"] = lon_int * 1e-7
                        self.heading_position["lat"] = lat_int * 1e-7
                        self.heading_position["fix"] = quality
                        
                        # Zodra de voorste een update krijgt, rekenen we de hoek direct uit
                        self._update_live_heading()
            except Exception:
                time.sleep(0.1)

    def _update_live_heading(self):
        """Berekent de ware kompasrichting tussen achter (main) en voor (heading)"""
        lat1, lon1 = self.current_position["lat"], self.current_position["lon"]
        lat2, lon2 = self.heading_position["lat"], self.heading_position["lon"]
        
        if lat1 != 0.0 and lat2 != 0.0:
            lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
            dLon = lon2_r - lon1_r
            x = math.sin(dLon) * math.cos(lat2_r)
            y = math.cos(lat1_r) * math.sin(lat2_r) - (math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dLon))
            self.current_heading = (math.degrees(math.atan2(x, y)) + 360) % 360

    def _parse_gga(self, sentence):
        try:
            parts = sentence.split(",")
            if len(parts) < 10: return
            
            quality = int(parts[6]) if parts[6] else 0
            if quality > 0:
                lat = self._nmea_to_decimal(parts[2], parts[3])
                lon = self._nmea_to_decimal(parts[4], parts[5])
                hdop = float(parts[8]) if parts[8] else 99.0
                self.current_position = {"lat": lat, "lon": lon, "fix": quality, "hdop": hdop}
        except Exception:
            pass

    def _nmea_to_decimal(self, value, direction):
        if not value: return 0.0
        degrees = int(float(value) / 100)
        minutes = float(value) - degrees * 100
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"): decimal = -decimal
        return decimal

    def _start_ntrip(self):
        while self._running:
            try:
                auth = base64.b64encode(f"{self.ntrip_cfg['user']}:{self.ntrip_cfg['pass']}".encode()).decode()
                request = (
                    f"GET /{self.ntrip_cfg['mountpoint']} HTTP/1.0\r\n"
                    f"Host: {self.ntrip_cfg['host']}:{self.ntrip_cfg['port']}\r\n"
                    f"Ntrip-Version: Ntrip/2.0\r\n"
                    f"Authorization: Basic {auth}\r\n"
                    f"User-Agent: BruutAgbot/1.0\r\n\r\n"
                )
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((self.ntrip_cfg['host'], self.ntrip_cfg['port']))
                sock.sendall(request.encode())
                
                print("[NTRIP] Verbonden, data wordt doorgestuurd naar beide GPS boarden...")
                sock.settimeout(5)
                
                while self._running:
                    data = sock.recv(1024)
                    if not data: break
                    
                    if self.ser_main and self.ser_main.is_open:
                        self.ser_main.write(data)
                    if self.ser_heading and self.ser_heading.is_open:
                        self.ser_heading.write(data)
                        
            except Exception as e:
                print(f"[NTRIP ERROR] Herverbinden in 5s... ({e})")
                time.sleep(5)