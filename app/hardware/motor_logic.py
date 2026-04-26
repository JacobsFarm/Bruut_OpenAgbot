import serial
import time
import threading

class MotorController:
    def __init__(self, port="/dev/ttyACM1", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.arduino = None
        self.laatste_zend_tijd = 0
        self.vertraging = 0.05 # 20Hz limiet
        self.lock = threading.Lock()
        
        self.connect()

    def connect(self):
        try:
            self.arduino = serial.Serial(self.port, self.baudrate, timeout=0.1)
            time.sleep(2)
            print(f"[MOTOR] Succesvol verbonden met {self.port}")
            self.stop() # Veiligheid: direct stoppen bij connectie
        except Exception as e:
            print(f"[MOTOR ERROR] Kan niet verbinden: {e}")
            self.arduino = None

    def stuur_motoren(self, dac_links, dac_rechts, dwing_verzenden=False):
        with self.lock:
            # Limiteer tussen 700 (0.77V) en 3100 (3.4V)
            dac_links = max(700, min(3100, int(dac_links)))
            dac_rechts = max(700, min(3100, int(dac_rechts)))
            
            huidige_tijd = time.time()
            if dwing_verzenden or (huidige_tijd - self.laatste_zend_tijd) >= self.vertraging:
                if self.arduino and self.arduino.is_open:
                    commando = f"{dac_links},{dac_rechts}\n"
                    print(f"🤖 [ARDUINO] Ik stuur: {commando.strip()}") # <-- VOEG DEZE TOE
                    self.arduino.write(commando.encode('utf-8'))
                    self.laatste_zend_tijd = huidige_tijd
                else:
                    print("⚠️ [ARDUINO] Poort is niet open! Commando genegeerd.") # <-- VOEG DEZE TOE

    def stop(self):
        """Noodstop / alles naar rust (700)"""
        self.stuur_motoren(700, 700, dwing_verzenden=True)