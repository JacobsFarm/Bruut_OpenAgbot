import threading
import socket
import time
import serial
import base64
import customtkinter as ctk

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
GPS_PORT        = "COM4"                  # Serial port for GPS (e.g., "COM4" for Windows, "/dev/ttyACM0" for Linux)
GPS_BAUDRATE    = 115200                  # Baudrate for the GPS serial connection

NTRIP_HOST      = "caster.centipede.fr"   # NTRIP Caster Host URL or IP
NTRIP_PORT      = 2101                    # NTRIP Caster Port
NTRIP_MOUNTPT   = "NEAR"                  # NTRIP Mountpoint
NTRIP_USER      = "centipede"             # NTRIP Username
NTRIP_PASS      = "centipede"             # NTRIP Password

class NtripClient(threading.Thread):
    def __init__(self, gps_serial, status_callback, debug_callback):
        super().__init__(daemon=True)
        self.gps_serial = gps_serial
        self.status_cb = status_callback
        self.debug_cb = debug_callback
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            try:
                self._connect()
            except Exception as e:
                self.debug_cb(f"[NTRIP ERROR] {e}")
                self.status_cb("NTRIP connection failed. Retrying in 5s...")
                time.sleep(5)

    def _connect(self):
        self.debug_cb(f"[NTRIP] Connecting to {NTRIP_HOST}:{NTRIP_PORT}...")
        auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
        request = (
            f"GET /{NTRIP_MOUNTPT} HTTP/1.0\r\n"
            f"Host: {NTRIP_HOST}:{NTRIP_PORT}\r\n"
            f"Ntrip-Version: Ntrip/2.0\r\n"
            f"Authorization: Basic {auth}\r\n"
            f"User-Agent: FieldRobotRTK/1.0\r\n\r\n"
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((NTRIP_HOST, NTRIP_PORT))
        sock.sendall(request.encode())

        response = sock.recv(1024).decode(errors="ignore")
        if "200 OK" not in response and "ICY 200 OK" not in response:
            raise ConnectionError(f"Rejected by server. Response: {response[:50]}")

        self.status_cb("NTRIP connected ✓")
        self.debug_cb("[NTRIP] Connected! Corrections are being forwarded to GPS.")
        sock.settimeout(5)

        bytes_received = 0
        while self.running:
            data = sock.recv(1024)
            if not data:
                break
            if self.gps_serial and self.gps_serial.is_open:
                self.gps_serial.write(data)
                bytes_received += len(data)
                
        self.debug_cb(f"[NTRIP] Connection lost. Total forwarded: {bytes_received} bytes")
        sock.close()

    def stop(self):
        self.running = False

class GpsReader(threading.Thread):
    def __init__(self, gps_serial, update_callback, debug_callback):
        super().__init__(daemon=True)
        self.ser = gps_serial
        self.update_cb = update_callback
        self.debug_cb = debug_callback
        self.running = False
        self.position = None

    def run(self):
        self.running = True
        last_data_time = time.time()
        
        while self.running:
            try:
                raw_bytes = self.ser.readline()
                
                if not raw_bytes:
                    if time.time() - last_data_time > 2.0:
                        self.debug_cb("[GPS WARNING] No data received in the last 2 seconds...")
                        last_data_time = time.time()
                    continue

                last_data_time = time.time()
                raw_text = raw_bytes.decode("ascii", errors="ignore").strip()
                
                if raw_text.startswith("$"):
                    self.debug_cb(f"[DATA] {raw_text}")
                else:
                    self.debug_cb(f"[UNKNOWN DATA] {raw_bytes[:20]}...")

                if raw_text.startswith("$GNGGA") or raw_text.startswith("$GPGGA"):
                    self._process_gga(raw_text)

            except serial.SerialException as e:
                self.debug_cb(f"[SERIAL ERROR] {e}")
                time.sleep(1)
            except Exception as e:
                self.debug_cb(f"[PROCESSING ERROR] {e}")

    def _process_gga(self, sentence):
        try:
            parts = sentence.split(",")
            if len(parts) < 10: return
            
            quality = int(parts[6]) if parts[6] else 0
            if quality == 0: 
                self.debug_cb("[GPS STATUS] No valid FIX (quality 0). Waiting for satellites...")
                return
                
            lat = self._nmea_to_decimal(parts[2], parts[3])
            lon = self._nmea_to_decimal(parts[4], parts[5])
            hdop = float(parts[8]) if parts[8] else 99.0
            
            self.position = (lat, lon, quality, hdop)
            self.update_cb(lat, lon, quality, hdop)
            
        except Exception as e:
            self.debug_cb(f"[GGA PARSE ERROR] {e} in sentence: {sentence}")

    def _nmea_to_decimal(self, value, direction):
        if not value: return 0.0
        degrees = int(float(value) / 100)
        minutes = float(value) - degrees * 100
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"): decimal = -decimal
        return decimal

    def stop(self):
        self.running = False

class WaypointLoggerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("RTK Waypoint Logger - DEBUG")
        self.geometry("600x800")
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.gps_ser = None
        self.gps_reader = None
        self.ntrip = None
        self.current_position = None

        self._build_gui()
        self._connect_hardware()

    def _build_gui(self):
        ctk.CTkLabel(self, text="RTK Logger & Debugger", font=("Arial", 22, "bold")).pack(pady=10)

        self.lbl_status = ctk.CTkLabel(self, text="Starting up...", font=("Arial", 13), fg_color=("gray85","gray20"), corner_radius=6)
        self.lbl_status.pack(fill="x", padx=20, pady=5)

        frame_gps = ctk.CTkFrame(self)
        frame_gps.pack(fill="x", padx=20, pady=10)
        
        self.lbl_lat = ctk.CTkLabel(frame_gps, text="Lat: --.--------", font=("Courier", 16))
        self.lbl_lat.pack(pady=(10,0))
        self.lbl_lon = ctk.CTkLabel(frame_gps, text="Lon: --.--------", font=("Courier", 16))
        self.lbl_lon.pack(pady=0)
        self.lbl_fix = ctk.CTkLabel(frame_gps, text="Fix: None | HDOP: --", font=("Arial", 14, "bold"))
        self.lbl_fix.pack(pady=(10,10))

        frame_buttons = ctk.CTkFrame(self, fg_color="transparent")
        frame_buttons.pack(pady=5)
        
        ctk.CTkButton(frame_buttons, text="📍 Save Point", width=160, font=("Arial", 14, "bold"), command=self._save_point).pack(side="left", padx=5)
        ctk.CTkButton(frame_buttons, text="Start NTRIP", width=160, command=self._start_ntrip).pack(side="left", padx=5)
        ctk.CTkButton(frame_buttons, text="💾 Export", width=120, fg_color="green", hover_color="darkgreen", command=self._export_list).pack(side="left", padx=5)

        ctk.CTkLabel(self, text="Debug Console (Raw Data):", font=("Arial", 12, "bold")).pack(anchor="w", padx=20, pady=(10,0))
        self.txt_debug = ctk.CTkTextbox(self, height=150, font=("Courier", 10), fg_color=("gray90", "gray10"))
        self.txt_debug.pack(fill="x", padx=20, pady=(0,10))

        ctk.CTkLabel(self, text="Saved Waypoints:", font=("Arial", 12, "bold")).pack(anchor="w", padx=20, pady=(10,0))
        self.txt_points = ctk.CTkTextbox(self, height=150, font=("Courier", 12))
        self.txt_points.pack(fill="both", expand=True, padx=20, pady=(0,20))

    def _connect_hardware(self):
        self._log_debug(f"Trying to connect to {GPS_PORT} @ {GPS_BAUDRATE} baud...")
        try:
            self.gps_ser = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1)
            self.gps_reader = GpsReader(self.gps_ser, self._gps_update, self._log_debug)
            self.gps_reader.start()
            self._set_status(f"GPS port opened: {GPS_PORT} ✓")
            self._log_debug("Port open. Waiting for data...")
        except serial.SerialException as e:
            self._set_status(f"Serial Error on {GPS_PORT}")
            self._log_debug(f"ERROR: Could not open port {GPS_PORT}. Is it in use by U-Center or another program? Details: {e}")
        except Exception as e:
            self._set_status("Unknown hardware error")
            self._log_debug(f"UNKNOWN ERROR: {e}")

    def _start_ntrip(self):
        if not self.gps_ser or not self.gps_ser.is_open:
            self._set_status("No GPS port open, cannot start NTRIP.")
            return
        if self.ntrip:
            self.ntrip.stop()
            self._log_debug("Restarting NTRIP...")
            
        self.ntrip = NtripClient(self.gps_ser, self._set_status, self._log_debug)
        self.ntrip.start()

    def _save_point(self):
        if self.current_position:
            lat, lon, quality, hdop = self.current_position
            line = f"{lat:.8f}, {lon:.8f}\n"
            self.txt_points.insert("end", line)
            count = len(self.txt_points.get('1.0', 'end').splitlines()) - 1
            self._set_status(f"Point saved! ({count} total)")
            self._log_debug(f"[ACTION] Point saved: {lat}, {lon}")
        else:
            self._set_status("No valid GPS fix to save!")
            self._log_debug("[ACTION] Cannot save: No valid FIX received from GPS yet.")

    def _export_list(self):
        data = self.txt_points.get("1.0", "end").strip()
        if not data:
            self._set_status("No points to export.")
            return
        
        filename = f"waypoints_{int(time.time())}.txt"
        with open(filename, "w") as f:
            f.write(data)
        self._set_status(f"Saved as {filename} ✓")

    def _gps_update(self, lat, lon, quality, hdop):
        self.current_position = (lat, lon, quality, hdop)
        quality_text = {0:"No fix", 1:"GPS", 2:"DGPS", 4:"RTK Fixed", 5:"RTK Float"}.get(quality, str(quality))
        
        self.after(0, self.lbl_lat.configure, {"text": f"Lat: {lat:.8f}"})
        self.after(0, self.lbl_lon.configure, {"text": f"Lon: {lon:.8f}"})
        
        color = "green" if quality == 4 else ("orange" if quality == 5 else "red")
        self.after(0, self.lbl_fix.configure, {"text": f"Fix: {quality_text} | HDOP: {hdop:.1f}", "text_color": color})

    def _set_status(self, text):
        self.after(0, self.lbl_status.configure, {"text": text})

    def _log_debug(self, text):
        def update():
            current_text = self.txt_debug.get("1.0", "end-1c")
            lines = current_text.splitlines()
            if len(lines) > 50:
                self.txt_debug.delete("1.0", "2.0")
            
            self.txt_debug.insert("end", text + "\n")
            self.txt_debug.see("end")
            
        self.after(0, update)

    def on_close(self):
        if self.ntrip: self.ntrip.stop()
        if self.gps_reader: self.gps_reader.stop()
        if self.gps_ser and self.gps_ser.is_open: self.gps_ser.close()
        self.destroy()

if __name__ == "__main__":
    app = WaypointLoggerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
