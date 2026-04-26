import threading
import serial
import time
import socket
import base64

class GpsSystem:
    def __init__(self, config):
        self.gps_port = config['hardware']['gps_port']
        self.gps_baudrate = config['hardware']['gps_baudrate']
        self.ntrip_cfg = config['ntrip']
        
        self.ser = None
        self.current_position = {"lat": 0.0, "lon": 0.0, "fix": 0, "hdop": 99.0}
        
        self._running = False
        self.connect()

    def connect(self):
        try:
            self.ser = serial.Serial(self.gps_port, self.gps_baudrate, timeout=1)
            print(f"[GPS] Verbonden op {self.gps_port}")
            self._running = True
            
            # Start achtergrond threads
            threading.Thread(target=self._lees_gps_data, daemon=True).start()
            threading.Thread(target=self._start_ntrip, daemon=True).start()
        except Exception as e:
            print(f"[GPS ERROR] Kan niet verbinden: {e}")

    def _lees_gps_data(self):
        while self._running and self.ser and self.ser.is_open:
            try:
                raw_bytes = self.ser.readline()
                if not raw_bytes: continue
                raw_text = raw_bytes.decode("ascii", errors="ignore").strip()
                
                if raw_text.startswith("$GNGGA") or raw_text.startswith("$GPGGA"):
                    self._parse_gga(raw_text)
            except Exception as e:
                time.sleep(1)

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
                
                print("[NTRIP] Verbonden, data wordt doorgestuurd naar GPS...")
                sock.settimeout(5)
                
                while self._running:
                    data = sock.recv(1024)
                    if not data: break
                    if self.ser and self.ser.is_open:
                        self.ser.write(data)
                        
            except Exception as e:
                print(f"[NTRIP ERROR] Herverbinden in 5s... ({e})")
                time.sleep(5)