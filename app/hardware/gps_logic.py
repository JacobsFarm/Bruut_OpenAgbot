import threading
import serial
import time
import socket
import base64
import math
from collections import deque

R_EARTH = 6371000.0


class GpsSystem:
    """
    De 'Ogen' van de AgBot: één ArduSimple simpleRTK4 Dual (u-blox ZED-X20D).

    Dit is één ontvanger met TWEE antennes op één seriële poort. Dat vervangt
    de oude opstelling met twee losse borden, en levert drie dingen tegelijk:

      1. POSITIE   - RTK, centimeter-nauwkeurig, tot 25 Hz  ($GNGGA)
      2. KOERS     - uit de moving baseline tussen de twee antennes ($GNTHS).
                     Dit is een ECHTE neus-richting: hij klopt ook als de robot
                     stilstaat, langzaam draait of zijwaarts wegglijdt.
      3. SNELHEID  - grondsnelheid en course-over-ground ($GNVTG)

    Waarom dat voor skid steer het belangrijkste onderdeel is: een skid steer
    slipt per definitie zijwaarts in elke bocht. De richting waarin de robot
    BEWEEGT (course over ground uit VTG) is dan niet de richting waarin zijn
    NEUS wijst. De vorige opzet gebruikte de antenne-koers alleen bij stilstand
    en schakelde daarboven over op course-over-ground - precies verkeerd om.
    Hier is THS altijd leidend, en VTG alleen een noodvangnet.

    Koersconventie: THS geeft de hoek met de klok mee vanaf het ware noorden,
    langs de lijn van de MASTER-antenne (GPS1, achter) naar de SLAVE-antenne
    (GPS2, voor). Dat is exact hetzelfde kompasstelsel als de navigators
    gebruiken. Staat de baseline niet in de rijrichting, corrigeer dat dan met
    'heading_offset_deg' in de config.
    """

    # Statusletters uit de NMEA THS-zin.
    THS_GELDIG = ("A",)      # Autonomous: echte meting
    THS_GESCHAT = ("E",)     # Estimated (dead reckoning): bruikbaar, minder zeker
    # V (invalid), M (manual) en S (simulator) verwerpen we.

    def __init__(self, config):
        hw_cfg = config.get("hardware", {})
        self.gps_port = hw_cfg.get("gps_port", "/dev/ttyACM0")
        self.gps_baudrate = hw_cfg.get("gps_baudrate", 115200)
        self.ntrip_cfg = config.get("ntrip", {})

        gnss_cfg = config.get("gnss", {})
        # Correctie als de antenne-baseline niet exact in de rijrichting ligt
        # (bv. antennes dwars gemonteerd: dan is dit -90 of +90).
        self.heading_offset_deg = float(gnss_cfg.get("heading_offset_deg", 0.0))
        # Waar zit het REGELPUNT van de robot t.o.v. de master-antenne (GPS1)?
        # De GGA-positie geldt namelijk voor die antenne, niet voor het midden
        # van de robot. Bij skid steer draait de robot om het midden van zijn
        # as; reken je met de antennepositie, dan lijkt elke draai op de plek
        # een verplaatsing. Vooruit = +, naar rechts = +.
        self.antenne_offset_vooruit_m = float(gnss_cfg.get("antenna_offset_forward_m", 0.0))
        self.antenne_offset_rechts_m = float(gnss_cfg.get("antenna_offset_right_m", 0.0))
        # Hoe lang blijft een koers bruikbaar zonder nieuwe THS-zin?
        self.heading_timeout_s = float(gnss_cfg.get("heading_timeout_s", 1.0))
        # Onder deze snelheid zegt course-over-ground niets; dan geen VTG-terugval.
        self.vtg_fallback_min_kmh = float(gnss_cfg.get("vtg_fallback_min_kmh", 1.5))
        self.accepteer_geschatte_heading = bool(gnss_cfg.get("accept_estimated_heading", True))
        # GGA terugsturen naar de NTRIP-caster (nodig voor VRS/NEAR-mountpoints,
        # die de dichtstbijzijnde basis kiezen op basis van jouw positie).
        self.ntrip_gga_interval_s = float(self.ntrip_cfg.get("gga_interval_s", 10.0))

        self.ser = None
        self._lock = threading.Lock()

        # Positie zoals de ontvanger hem geeft (= op de master-antenne)
        self.antenne_positie = {"lat": 0.0, "lon": 0.0, "fix": 0, "hdop": 99.0,
                                "sats": 0, "alt_m": 0.0}
        # Positie omgerekend naar het regelpunt van de robot
        self.current_position = dict(self.antenne_positie)

        self.current_heading = 0.0
        self.heading_bron = "geen"       # "THS" | "THS(geschat)" | "VTG" | "geen"
        self.heading_geldig = False
        self.heading_tijd = 0.0

        self.current_speed_kmh = 0.0
        self.course_over_ground = 0.0

        self.laatste_gga_zin = None      # ruwe zin, voor de NTRIP-caster
        self._laatste_nmea_tijd = 0.0
        self._laatste_vtg_tijd = 0.0
        self._checksum_fouten = 0

        # Werkelijk gemeten frequenties (zo hoef je niet te gokken of de
        # ontvanger echt op 25 Hz staat).
        self._gga_tijden = deque(maxlen=60)
        self._ths_tijden = deque(maxlen=60)

        self._running = False
        self.connect()

    # ------------------------------------------------------------------ #
    #  Verbinding
    # ------------------------------------------------------------------ #
    def connect(self):
        try:
            self.ser = serial.Serial(self.gps_port, self.gps_baudrate, timeout=1)
            print(f"[GNSS] ZED-X20D verbonden op {self.gps_port} @ {self.gps_baudrate}")

            self._running = True
            threading.Thread(target=self._lees_nmea, daemon=True).start()
            threading.Thread(target=self._start_ntrip, daemon=True).start()
        except Exception as e:
            print(f"[GNSS ERROR] Kan niet verbinden: {e}")
            self.ser = None

    def close(self):
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

    # ------------------------------------------------------------------ #
    #  Publieke API
    # ------------------------------------------------------------------ #
    def get_current_position(self):
        """Alles wat de navigators nodig hebben, in één momentopname."""
        with self._lock:
            nu = time.time()
            heading, bron, geldig = self._kies_heading(nu)
            pos = self._naar_regelpunt(self.antenne_positie, heading, geldig)

            return {
                "lat": pos["lat"],
                "lon": pos["lon"],
                "fix": self.antenne_positie["fix"],
                "hdop": self.antenne_positie["hdop"],
                "sats": self.antenne_positie["sats"],
                "alt_m": self.antenne_positie["alt_m"],
                "heading": heading,
                "heading_bron": bron,
                "heading_geldig": geldig,
                "speed_kmh": self.current_speed_kmh,
                "course_over_ground": self.course_over_ground,
                "antenne_lat": self.antenne_positie["lat"],
                "antenne_lon": self.antenne_positie["lon"],
            }

    def get_diagnostics(self):
        """Gemeten datastromen - handig om te zien of de .ucf goed staat."""
        with self._lock:
            return {
                "positie_hz": self._frequentie(self._gga_tijden),
                "heading_hz": self._frequentie(self._ths_tijden),
                "heading_bron": self.heading_bron,
                "heading_geldig": self.heading_geldig,
                "checksum_fouten": self._checksum_fouten,
                "data_leeftijd_s": round(time.time() - self._laatste_nmea_tijd, 2)
                if self._laatste_nmea_tijd else None,
            }

    # ------------------------------------------------------------------ #
    #  NMEA inlezen
    # ------------------------------------------------------------------ #
    def _lees_nmea(self):
        """
        Eén stroom, alle berichten. Op 25 Hz komt er flink wat over de lijn,
        dus elke zin gaat eerst langs de checksum: een verminkte koers is op
        een skid steer gevaarlijker dan even geen koers.
        """
        while self._running and self.ser and self.ser.is_open:
            try:
                ruw = self.ser.readline()
                if not ruw:
                    continue
                zin = ruw.decode("ascii", errors="ignore").strip()
                if not zin.startswith("$"):
                    continue
                if not self._checksum_ok(zin):
                    with self._lock:
                        self._checksum_fouten += 1
                    continue

                self._laatste_nmea_tijd = time.time()
                soort = zin[3:6] if len(zin) > 6 else ""

                if soort == "GGA":
                    self._parse_gga(zin)
                elif soort == "THS":
                    self._parse_ths(zin)
                elif soort == "VTG":
                    self._parse_vtg(zin)
                elif soort == "RMC":
                    self._parse_rmc(zin)
            except Exception:
                time.sleep(0.05)

    @staticmethod
    def _checksum_ok(zin):
        """NMEA-checksum: XOR van alles tussen '$' en '*'."""
        ster = zin.rfind("*")
        if ster < 0 or ster + 3 > len(zin):
            return False
        som = 0
        for teken in zin[1:ster]:
            som ^= ord(teken)
        try:
            return som == int(zin[ster + 1:ster + 3], 16)
        except ValueError:
            return False

    def _parse_gga(self, zin):
        """Positie, fixkwaliteit, HDOP. Met CFG-NMEA-HIGHPREC extra decimalen."""
        try:
            d = zin.split(",")
            if len(d) < 10:
                return
            kwaliteit = int(d[6]) if d[6] else 0
            if kwaliteit <= 0:
                with self._lock:
                    self.antenne_positie["fix"] = 0
                return

            lat = self._nmea_naar_decimaal(d[2], d[3])
            lon = self._nmea_naar_decimaal(d[4], d[5])
            with self._lock:
                self.antenne_positie = {
                    "lat": lat,
                    "lon": lon,
                    "fix": kwaliteit,          # 1=GPS, 2=DGPS, 4=RTK fixed, 5=RTK float
                    "hdop": float(d[8]) if d[8] else 99.0,
                    "sats": int(d[7]) if d[7] else 0,
                    "alt_m": float(d[9]) if d[9] else 0.0,
                }
                self.laatste_gga_zin = zin
                self._gga_tijden.append(time.time())
        except Exception:
            pass

    def _parse_ths(self, zin):
        """
        $GNTHS,<koers>,<status>*hh - de ware neus-richting uit de twee antennes.

        Dit is de hoofdbron voor de koers. Status 'A' is een echte meting, 'E'
        een geschatte (dead reckoning) waarde; al het andere verwerpen we.
        """
        try:
            d = zin.split(",")
            if len(d) < 3 or not d[1]:
                return
            status = d[2].split("*")[0].strip().upper()
            koers = float(d[1])

            if status in self.THS_GELDIG:
                bron = "THS"
            elif status in self.THS_GESCHAT and self.accepteer_geschatte_heading:
                bron = "THS(geschat)"
            else:
                with self._lock:
                    if self.heading_bron.startswith("THS"):
                        self.heading_geldig = False
                return

            with self._lock:
                self.current_heading = (koers + self.heading_offset_deg) % 360.0
                self.heading_bron = bron
                self.heading_geldig = True
                self.heading_tijd = time.time()
                self._ths_tijden.append(self.heading_tijd)
        except Exception:
            pass

    def _parse_vtg(self, zin):
        """$GNVTG: grondsnelheid en course over ground (koers van de BEWEGING)."""
        try:
            d = zin.split(",")
            if len(d) >= 8 and d[7]:
                with self._lock:
                    self.current_speed_kmh = float(d[7])
                    if d[1]:
                        self.course_over_ground = float(d[1])
                    self._laatste_vtg_tijd = time.time()
        except Exception:
            pass

    def _parse_rmc(self, zin):
        """
        $GNRMC: reservebron voor de snelheid (in knopen), voor het geval VTG
        in de ontvanger uitgeschakeld staat. Zolang VTG binnenkomt laten we
        die met rust - anders schrijven twee bronnen door elkaar heen.
        """
        try:
            d = zin.split(",")
            if len(d) >= 8 and d[2] == "A" and d[7]:
                with self._lock:
                    if (time.time() - self._laatste_vtg_tijd) > 2.0:
                        self.current_speed_kmh = float(d[7]) * 1.852
                        if len(d) >= 9 and d[8]:
                            self.course_over_ground = float(d[8])
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Koers kiezen en positie omrekenen
    # ------------------------------------------------------------------ #
    def _kies_heading(self, nu):
        """
        THS gaat altijd voor. Alleen als die te oud of ongeldig is, en de robot
        hard genoeg rijdt om er iets aan te hebben, vallen we terug op course
        over ground. Rijdt hij daarvoor te langzaam, dan houden we de laatst
        bekende koers vast maar melden we hem als ONGELDIG - dan kunnen de
        navigators zelf besluiten te stoppen.
        """
        vers = (nu - self.heading_tijd) <= self.heading_timeout_s
        if self.heading_geldig and vers:
            return self.current_heading, self.heading_bron, True

        if self.current_speed_kmh >= self.vtg_fallback_min_kmh:
            return (self.course_over_ground + self.heading_offset_deg) % 360.0, "VTG", True

        return self.current_heading, "geen", False

    def _naar_regelpunt(self, antenne, heading, heading_geldig):
        """
        Verschuift de gemeten antennepositie naar het regelpunt van de robot.

        Zonder betrouwbare koers kunnen we niet weten welke kant 'vooruit' op
        wijst; dan geven we de antennepositie ongewijzigd terug.
        """
        vooruit = self.antenne_offset_vooruit_m
        rechts = self.antenne_offset_rechts_m
        if not heading_geldig or (vooruit == 0.0 and rechts == 0.0):
            return {"lat": antenne["lat"], "lon": antenne["lon"]}
        if antenne["lat"] == 0.0 and antenne["lon"] == 0.0:
            return {"lat": 0.0, "lon": 0.0}

        b = math.radians(heading)
        noord = vooruit * math.cos(b) - rechts * math.sin(b)
        oost = vooruit * math.sin(b) + rechts * math.cos(b)

        lat = antenne["lat"] + math.degrees(noord / R_EARTH)
        lon = antenne["lon"] + math.degrees(
            oost / (R_EARTH * math.cos(math.radians(antenne["lat"])))
        )
        return {"lat": lat, "lon": lon}

    @staticmethod
    def _frequentie(tijden):
        if len(tijden) < 2:
            return 0.0
        duur = tijden[-1] - tijden[0]
        return round((len(tijden) - 1) / duur, 1) if duur > 0 else 0.0

    @staticmethod
    def _nmea_naar_decimaal(waarde, richting):
        if not waarde:
            return 0.0
        graden = int(float(waarde) / 100)
        minuten = float(waarde) - graden * 100
        decimaal = graden + minuten / 60.0
        if richting in ("S", "W"):
            decimaal = -decimaal
        return decimaal

    # ------------------------------------------------------------------ #
    #  NTRIP (RTK-correcties)
    # ------------------------------------------------------------------ #
    def _start_ntrip(self):
        """
        Haalt RTCM-correcties op en stuurt ze naar de ontvanger.

        Eén ontvanger betekent ook maar één correctiestroom: de X20D deelt de
        correctie intern met beide antennes. De koers uit de moving baseline
        werkt trouwens ook ZONDER RTK - je verliest bij een wegvallende caster
        dus je centimeterpositie, niet je richting.
        """
        while self._running:
            try:
                auth = base64.b64encode(
                    f"{self.ntrip_cfg['user']}:{self.ntrip_cfg['pass']}".encode()
                ).decode()
                request = (
                    f"GET /{self.ntrip_cfg['mountpoint']} HTTP/1.0\r\n"
                    f"Host: {self.ntrip_cfg['host']}:{self.ntrip_cfg['port']}\r\n"
                    f"Ntrip-Version: Ntrip/2.0\r\n"
                    f"Authorization: Basic {auth}\r\n"
                    f"User-Agent: NTRIP BruutAgbot/2.0\r\n\r\n"
                )
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((self.ntrip_cfg['host'], self.ntrip_cfg['port']))
                sock.sendall(request.encode())

                print("[NTRIP] Verbonden, correcties gaan naar de ZED-X20D...")
                sock.settimeout(5)
                laatste_gga = 0.0

                while self._running:
                    # VRS- en 'NEAR'-mountpoints kiezen de dichtstbijzijnde
                    # basis op basis van onze eigen positie; die moeten we dus
                    # periodiek terugsturen.
                    nu = time.time()
                    if self.ntrip_gga_interval_s > 0 and (nu - laatste_gga) >= self.ntrip_gga_interval_s:
                        with self._lock:
                            gga = self.laatste_gga_zin
                        if gga:
                            try:
                                sock.sendall((gga + "\r\n").encode())
                            except Exception:
                                break
                        laatste_gga = nu

                    data = sock.recv(1024)
                    if not data:
                        break
                    if self.ser and self.ser.is_open:
                        self.ser.write(data)
            except Exception as e:
                print(f"[NTRIP ERROR] Herverbinden in 5s... ({e})")
                time.sleep(5)
