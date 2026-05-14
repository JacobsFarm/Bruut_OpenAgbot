import serial
import socket
import base64
import time
import math
from threading import Thread

# --- CONFIGURATIE ---
GPS_VOOR = "/dev/ttyACM0"   # simpleRTK 4 Dual (1 Hz / UBX) 
GPS_ACHTER = "/dev/ttyACM1" # ZED-F9P (10 Hz / NMEA)
BAUD = 115200

NTRIP = {
    "host": "caster.centipede.fr",
    "port": 2101,
    "mountpoint": "CVB8",
    "user": "centipede",
    "pass": "centipede"
}

# Globale status
pos_voor = {"lat": 0.0, "lon": 0.0, "new": False}
pos_achter = {"lat": 0.0, "lon": 0.0}
last_heading = 0.0

def ntrip_handler(ser_list):
    """Stuurt RTK correcties naar beide boarden """
    auth = base64.b64encode(f'{NTRIP["user"]}:{NTRIP["pass"]}'.encode()).decode()
    headers = f'GET /{NTRIP["mountpoint"]} HTTP/1.0\r\nAuthorization: Basic {auth}\r\n\r\n'
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((NTRIP["host"], NTRIP["port"]))
            sock.sendall(headers.encode())
            while True:
                data = sock.recv(2048)
                if not data: break
                for ser in ser_list: ser.write(data)
        except:
            time.sleep(5)

def parse_ubx_voor(ser):
    """Leest het 1 Hz board en zet een vlag bij nieuwe data"""
    global pos_voor
    while True:
        try:
            if ser.read(1) == b'\xb5' and ser.read(1) == b'\x62':
                cls, id = ser.read(1), ser.read(1)
                length = int.from_bytes(ser.read(2), 'little')
                payload = ser.read(length)
                ser.read(2)
                
                if cls == b'\x01' and id == b'\x07' and len(payload) >= 32:
                    lon_int = int.from_bytes(payload[24:28], 'little', signed=True)
                    lat_int = int.from_bytes(payload[28:32], 'little', signed=True)
                    
                    pos_voor["lon"] = lon_int * 1e-7
                    pos_voor["lat"] = lat_int * 1e-7
                    pos_voor["new"] = True # Vlag: Er is een nieuwe 1Hz meting!
        except: break

def parse_nmea_achter(ser):
    """Leest constant de 10 Hz positie"""
    global pos_achter
    while True:
        try:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if line.startswith('$GNGGA'):
                parts = line.split(',')
                if len(parts) > 6 and parts[2] and parts[4]:
                    lat_raw = parts[2]
                    pos_achter["lat"] = int(lat_raw[:2]) + float(lat_raw[2:]) / 60.0
                    lon_raw = parts[4]
                    pos_achter["lon"] = int(lon_raw[:3]) + float(lon_raw[3:]) / 60.0
        except: break

def calculate_heading(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dLon = lon2 - lon1
    x = math.sin(dLon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dLon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def main_loop():
    global last_heading
    print("[*] Systeem gestart. Wachten op GPS fix...")
    while True:
        # Alleen berekenen als Board 0 (1 Hz) een nieuwe positie heeft
        if pos_voor["new"]:
            if pos_voor["lat"] != 0 and pos_achter["lat"] != 0:
                last_heading = calculate_heading(pos_achter["lat"], pos_achter["lon"], 
                                                 pos_voor["lat"], pos_voor["lon"])
                
                print("\033[H") # Reset console
                print(f"--- AgBot Gesynchroniseerde Heading ---")
                print(f"Update Moment: {time.strftime('%H:%M:%S')}")
                print(f"Achter (10Hz): {pos_achter['lat']:.8f}")
                print(f"Voor   (1Hz) : {pos_voor['lat']:.8f}")
                print("-" * 40)
                print(f"HEADING: {last_heading:>6.2f}°")
                
                # Pijl indicator
                dirs = ["↑ N", "↗ NO", "→ O", "↘ ZO", "↓ Z", "↙ ZW", "← W", "↖ NW"]
                print(f"RICHTING: {dirs[round(last_heading/45)%8]}")
                print("-" * 40)
            
            pos_voor["new"] = False # Reset de vlag
        
        time.sleep(0.01)

if __name__ == "__main__":
    try:
        s_voor = serial.Serial(GPS_VOOR, BAUD, timeout=0.1)
        s_achter = serial.Serial(GPS_ACHTER, BAUD, timeout=0.1)
        Thread(target=ntrip_handler, args=([s_voor, s_achter],), daemon=True).start()
        Thread(target=parse_ubx_voor, args=(s_voor,), daemon=True).start()
        Thread(target=parse_nmea_achter, args=(s_achter,), daemon=True).start()
        main_loop()
    except KeyboardInterrupt: print("\nGestopt.")
