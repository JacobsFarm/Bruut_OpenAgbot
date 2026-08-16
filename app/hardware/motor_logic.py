import serial
import time
import threading


class MotorController:
    """
    De verbinding met de Arduino + MCP4728 DAC.

    Skid steer: kanaal A stuurt de LINKER hubmotoren, kanaal B de RECHTER.
    Beide kanten zijn puur 'gas geven' (vooruit); sturen gebeurt door het
    snelheidsverschil tussen links en rechts, niet door een stuurmotor.

    Het protocol naar de Arduino is één regel per commando: "links,rechts\\n".
    """

    def __init__(self, port="/dev/ttyACM1", baudrate=115200,
                 dac_stop=700, dac_max=3100, min_interval_sec=0.05):
        self.port = port
        self.baudrate = baudrate
        self.dac_stop = int(dac_stop)
        self.dac_max = int(dac_max)

        self.arduino = None
        self.laatste_zend_tijd = 0.0
        self.vertraging = min_interval_sec  # 20Hz limiet: de Arduino kan niet sneller
        self.lock = threading.Lock()

        self.connect()

    def connect(self):
        try:
            self.arduino = serial.Serial(self.port, self.baudrate, timeout=0.1)
            time.sleep(2)
            print(f"[MOTOR] Succesvol verbonden met {self.port}")
            self.stop()  # Veiligheid: direct stoppen bij connectie
        except Exception as e:
            print(f"[MOTOR ERROR] Kan niet verbinden: {e}")
            self.arduino = None

    def stuur_motoren(self, dac_links, dac_rechts, dwing_verzenden=False):
        """Stuur beide kanten in één commando; ze moeten altijd samen aankomen."""
        with self.lock:
            dac_links = max(self.dac_stop, min(self.dac_max, int(dac_links)))
            dac_rechts = max(self.dac_stop, min(self.dac_max, int(dac_rechts)))

            huidige_tijd = time.time()
            if dwing_verzenden or (huidige_tijd - self.laatste_zend_tijd) >= self.vertraging:
                if self.arduino and self.arduino.is_open:
                    commando = f"{dac_links},{dac_rechts}\n"
                    self.arduino.write(commando.encode('utf-8'))
                    self.laatste_zend_tijd = huidige_tijd
                else:
                    print("⚠️ [ARDUINO] Poort is niet open! Commando genegeerd.")

    def stop(self):
        """Noodstop / beide kanten naar rust (DAC 700)."""
        self.stuur_motoren(self.dac_stop, self.dac_stop, dwing_verzenden=True)

    def close(self):
        self.stop()
        with self.lock:
            if self.arduino and self.arduino.is_open:
                self.arduino.close()
