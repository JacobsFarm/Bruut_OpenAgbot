import serial
import socket
import base64
import time
from threading import Thread

# --- CONFIGURATIE ---
BOARDS = {
    "Board 0": "/dev/ttyACM0",
    "Board 1": "/dev/ttyACM1"
}
BAUD = 115200

NTRIP = {
    "host": "caster.centipede.fr",
    "port": 2101,
    "mountpoint": "CVB8",
    "user": "centipede",
    "pass": "centipede"
}

# Globale status opslag
status_data = {
    "Board 0": {"fix": "Wachten...", "hz": 0.0, "packets": 0},
    "Board 1": {"fix": "Wachten...", "hz": 0.0, "packets": 0}
}

def ntrip_handler(ser_list):
    """Verstuurt Centipede data naar alle geopende seriële poorten"""
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
                for ser in ser_list:
                    ser.write(data)
        except:
            time.sleep(5)

def parse_ubx(board_name, ser):
    """Leest UBX data en berekent de fix en Hz"""
    last_time = time.time()
    nav_count = 0
    
    while True:
        try:
            char = ser.read(1)
            if char == b'\xb5': # Sync char 1
                if ser.read(1) == b'\x62': # Sync char 2
                    cls = ser.read(1)
                    id  = ser.read(1)
                    length = int.from_bytes(ser.read(2), 'little')
                    payload = ser.read(length)
                    ser.read(2) # Skip checksum
                    
                    if cls == b'\x01' and id == b'\x07': # NAV-PVT bericht
                        nav_count += 1
                        if len(payload) >= 22:
                            flags = payload[21]
                            rtk_status = (flags >> 6) & 0x03
                            if rtk_status == 2: status_data[board_name]["fix"] = "RTK FIXED"
                            elif rtk_status == 1: status_data[board_name]["fix"] = "RTK FLOAT"
                            else: status_data[board_name]["fix"] = "3D-FIX"
            
            # Hz Berekening per seconde
            now = time.time()
            if now - last_time >= 1.0:
                status_data[board_name]["hz"] = nav_count / (now - last_time)
                nav_count = 0
                last_time = now
        except:
            break

def display_status():
    """Print een mooie tabel in de terminal"""
    print("\n" * 10) # Maak ruimte
    while True:
        print("\033[H") # Cursor naar boven (reset scherm)
        print("--- AgBot Dual GPS Monitor ---")
        print(f"Centipede: {NTRIP['host']} [{NTRIP['mountpoint']}]")
        print("-" * 50)
        print(f"{'POORT':<15} | {'FIX STATUS':<15} | {'UPDATE RATE':<10}")
        print("-" * 50)
        for name, path in BOARDS.items():
            s = status_data[name]
            print(f"{path:<15} | {s['fix']:<15} | {s['hz']:>4.1f} Hz")
        print("-" * 50)
        print("Druk op Ctrl+C om te stoppen")
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        # Open poorten
        ser0 = serial.Serial(BOARDS["Board 0"], BAUD, timeout=0.01)
        ser1 = serial.Serial(BOARDS["Board 1"], BAUD, timeout=0.01)
        
        # Start Threads
        Thread(target=ntrip_handler, args=([ser0, ser1],), daemon=True).start()
        Thread(target=parse_ubx, args=("Board 0", ser0), daemon=True).start()
        Thread(target=parse_ubx, args=("Board 1", ser1), daemon=True).start()
        
        display_status()
    except KeyboardInterrupt:
        print("\nGestopt door gebruiker.")
    except Exception as e:
        print(f"\nFout: {e}")