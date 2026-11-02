import threading
import serial
import time
import socket
import base64
import math
import struct
from collections import deque

R_EARTH = 6371000.0


class GpsSystem:
    """
    De 'Ogen' van de AgBot: één ArduSimple simpleRTK4 Dual (u-blox ZED-X20D).

    Dit is één ontvanger met TWEE antennes op één seriële poort. Dat vervangt
    de oude opstelling met twee losse borden, en levert drie dingen tegelijk:

      1. POSITIE   - RTK, centimeter-nauwkeurig ($GNGGA)
      2. KOERS     - uit de twee antennes van de module zelf ($GNTHS).
                     Let op: UBX-NAV-RELPOSNED is op dit board de vector naar
                     het NTRIP-basisstation, NIET tussen de antennes; daarvoor
                     is NAV-DAHEADING / THS.
                     Dit is een ECHTE neus-richting: hij klopt ook als de robot
                     stilstaat, langzaam draait of zijwaarts wegglijdt.
      3. SNELHEID  - grondsnelheid en course-over-ground ($GNVTG)

    Course over ground (VTG) is niet de richting van de NEUS maar van de
    BEWEGING: die wijkt af als de wielen in een bocht of op een helling
    wegschuiven, is onbruikbaar bij lage snelheid en draait 180 graden om bij
    achteruit rijden. THS is daarom altijd leidend en VTG alleen een
    noodvangnet. Het verschil tussen de twee is juist bruikbaar: het geeft
    de rijrichting (vooruit/achteruit) en de sliphoek.

    Verder levert deze klasse wat de navigators nodig hebben om op 25 Hz te
    regelen: een epoch-signaal per complete meting (wacht_op_epoch), de
    draaisnelheid van de neus, de leeftijd van positie, koers en
    RTK-correcties, en een positie die voor de latentie gecompenseerd is.

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
        # 460800 is wat configure_x20d.py op de UARTs zet (via USB maakt de
        # baudrate niet uit).
        self.gps_baudrate = hw_cfg.get("gps_baudrate", 460800)
        self.ntrip_cfg = config.get("ntrip", {})

        gnss_cfg = config.get("gnss", {})
        # Correctie als de antenne-baseline niet exact in de rijrichting ligt
        # (bv. antennes dwars gemonteerd: dan is dit -90 of +90).
        self.heading_offset_deg = float(gnss_cfg.get("heading_offset_deg", 0.0))
        # Waar zit het REGELPUNT van de robot t.o.v. de master-antenne (GPS1)?
        # De GGA-positie geldt namelijk voor die antenne, niet voor het midden
        # van de robot. Met gestuurde voorwielen is dat het midden van de
        # achteras (daar rekent de Ackermann-geometrie vanaf); de master-antenne
        # zit achter, dus meestal is alleen een kleine offset nodig.
        # Vooruit = +, naar rechts = +.
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
        # Tijd tussen de meting in de ontvanger en het moment dat de navigator
        # hem gebruikt (rekentijd ontvanger + seriële lijn). De positie wordt
        # over die tijd plus de leeftijd van de laatste zin vooruit geschoven
        # langs de koers, en de koers met de draaisnelheid. Bij 3 km/h scheelt
        # 50 ms al 4 cm - op 25 Hz is dat de helft van de meetfout die je zo
        # kwijtraakt.
        self.latentie_compensatie = bool(gnss_cfg.get("latency_compensation", True))
        self.latentie_s = float(gnss_cfg.get("latency_s", 0.03))
        # Hoogte van de antenne (fasecentrum GPS1) boven de grond. Kantelt de
        # robot voor-achter (pitch uit NAV-DAHEADING), dan staat de antenne
        # niet meer recht boven zijn voetpunt: h * sin(pitch) langs de
        # rijrichting, bij 1 m en 5 graden al 9 cm. 0 = geen correctie.
        self.antenne_hoogte_m = float(gnss_cfg.get("antenna_height_m", 0.0))
        # De antennes staan zelden precies even hoog: die scheefstand meet de
        # dubbele antenne als 'pitch' terwijl de robot vlak staat. Hij gaat
        # eraf. Te bepalen met extract_map_terrain.py (rijd heen en terug: een
        # helling keert dan om, de montage niet).
        self.pitch_offset_deg = float(gnss_cfg.get("pitch_offset_deg", 0.0))
        # Ruwheid van het veld: spreiding van de pitch over de laatste seconde.
        self._pitch_venster = deque(maxlen=50)   # (tijd, pitch)
        self.ruwheid_deg = None

        self.ser = None
        self._lock = threading.Lock()
        # Epoch = één complete meting (GGA + THS). De navigators wachten hierop
        # in plaats van op een eigen klok: zo rekenen ze op 25 Hz met de
        # verste data, zonder dat een meting half oud wordt in een wachtrij.
        self._epoch = 0
        self._epoch_cond = threading.Condition(self._lock)
        self._epoch_delen = set()

        # Positie zoals de ontvanger hem geeft (= op de master-antenne)
        self.antenne_positie = {"lat": 0.0, "lon": 0.0, "fix": 0, "hdop": 99.0,
                                "sats": 0, "alt_m": 0.0}

        self.current_heading = 0.0
        self.heading_bron = "geen"       # "THS" | "THS(geschat)" | "VTG" | "geen"
        self.heading_geldig = False
        self.heading_tijd = 0.0

        self.current_speed_kmh = 0.0
        self.course_over_ground = 0.0

        self.gga_tijd = 0.0              # ontvangstmoment van de laatste GGA met fix
        self.correctie_leeftijd_s = None # GGA-veld 13: hoe oud de RTK-correcties zijn
        # Uit opeenvolgende THS-metingen: hoe snel draait de neus (graden/s,
        # positief = naar rechts). Kan alleen met een echte neus-heading op 25 Hz.
        self.draaisnelheid_dps = 0.0
        self._vorige_ths = None          # (tijd, koers)
        # Course over ground vergeleken met de neus: +1 vooruit, -1 achteruit,
        # 0 = stil of onbekend. De sliphoek is hoeveel de beweging naast de neus
        # ligt als hij vooruit rijdt (wegglijden op een helling, in een bocht).
        self.rijrichting = 0
        self.sliphoek_deg = None

        self.laatste_gga_zin = None      # ruwe zin, voor de NTRIP-caster
        self._laatste_nmea_tijd = 0.0
        self._laatste_vtg_tijd = 0.0
        self._checksum_fouten = 0

        # Werkelijk gemeten frequenties (zo hoef je niet te gokken of de
        # ontvanger echt op 25 Hz staat, en of THS even vaak komt als GGA).
        self._gga_tijden = deque(maxlen=60)
        self._ths_tijden = deque(maxlen=60)

        # Voor de diagnostiek: komen er correcties binnen?
        self.ntrip_status = {"status": "start", "fout": None, "bytes": 0, "laatste_data": None}

        # UBX-NAV-DAHEADING (binair, tussen de NMEA door): afstand en
        # hoogteverschil tussen de antennes, heading-nauwkeurigheid en of de
        # baseline 'fixed' is. Alleen meten en loggen - gestuurd wordt op THS.
        # Bij het verbinden zetten we hem aan in het RAM van de ontvanger (na
        # een herstart van het board weer uit); komt er niets, dan vragen we
        # er elke seconde om.
        self.daheading_aan = bool(gnss_cfg.get("daheading", True))
        self.dah = None                  # laatste geldige meting, of None
        self.dah_tijd = 0.0
        self._dah_tijden = deque(maxlen=60)
        self.dah_config = "uit" if not self.daheading_aan else "nog niet verstuurd"
        self.dah_afwijkend = None        # tekst als het bericht een ander formaat heeft dan verwacht
        self._ubx_tellers = {}           # "01-45": aantal ontvangen, per UBX-bericht
        self._acks = {}                  # (klasse, id) -> "ACK" / "NAK" van de ontvanger
        self._buf = bytearray()
        self._schrijf_lock = threading.Lock()   # NTRIP en DAHEADING schrijven allebei naar de poort

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
            threading.Thread(target=self._lees_stroom, daemon=True).start()
            threading.Thread(target=self._start_ntrip, daemon=True).start()
            if self.daheading_aan:
                threading.Thread(target=self._daheading_bewaken, daemon=True).start()
        except Exception as e:
            print(f"[GNSS ERROR] Kan niet verbinden: {e}")
            self.ser = None

    def _schrijf(self, data):
        with self._schrijf_lock:
            if self.ser and self.ser.is_open:
                self.ser.write(data)

    def close(self):
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

    # ------------------------------------------------------------------ #
    #  Publieke API
    # ------------------------------------------------------------------ #
    FIX_SOORT = {0: "geen", 1: "gps", 2: "dgps", 4: "rtk_fixed", 5: "rtk_float", 6: "geschat"}

    def _momentopname(self, nu):
        """
        Aanroepen met de lock vast. Koers en de verschuiving langs de neus die
        voor elk punt op de robot gelden:
          - latentie: waar is hij NU, in plaats van op het moment van meten?
            (alleen met geldige koers; achteruit rijdend de andere kant op)
          - pitch: het voetpunt van de antenne ligt h * sin(pitch) voor (neus
            omhoog) of achter de antenne.
        """
        heading, bron, geldig = self._kies_heading(nu)
        pos_leeftijd = (nu - self.gga_tijd) if self.gga_tijd else None
        vooruit_extra, voorspeld_s = 0.0, 0.0
        if self.latentie_compensatie and geldig and pos_leeftijd is not None and pos_leeftijd < 0.5:
            voorspeld_s = pos_leeftijd + self.latentie_s
            richting = -1.0 if self.rijrichting < 0 else 1.0
            vooruit_extra = richting * self.current_speed_kmh / 3.6 * voorspeld_s
            heading_s = (nu - self.heading_tijd) + self.latentie_s
            if bron.startswith("THS") and heading_s < 0.5:
                heading = (heading + self.draaisnelheid_dps * heading_s) % 360.0
        pitch = self._verse_pitch(nu)
        pitch_corr = 0.0
        if self.antenne_hoogte_m > 0.0 and pitch is not None:
            pitch_corr = self.antenne_hoogte_m * math.sin(math.radians(pitch))
        return heading, bron, geldig, pos_leeftijd, vooruit_extra + pitch_corr, voorspeld_s, pitch, pitch_corr

    def _verse_pitch(self, nu):
        """Pitch uit NAV-DAHEADING, alleen als hij vers (< 0.2 s) en 'fixed' is."""
        d = self.dah
        if d is None or d["pitch_deg"] is None or d["oplossing"] != "fixed" or nu - self.dah_tijd > 0.2:
            return None
        return d["pitch_deg"]

    def punt_op_grond(self, vooruit_m, rechts_m):
        """
        (lat, lon) van een punt op de GROND, gemeten in het voertuigframe vanaf
        het voetpunt van antenne GPS1: vooruit = +, rechts = +. Gecorrigeerd
        voor latentie en pitch. Bedoeld voor bv. de camera: waar ligt de
        onkruidplant die nu midden in beeld is? Geeft None zonder fix of
        zonder geldige koers (dan weten we niet welke kant 'vooruit' is).
        """
        with self._lock:
            heading, _, geldig, _, extra, _, _, _ = self._momentopname(time.time())
            if not geldig or self.antenne_positie["fix"] == 0:
                return None
            pos = self._verplaats(self.antenne_positie, heading, vooruit_m + extra, rechts_m)
            return pos["lat"], pos["lon"]

    def get_current_position(self):
        """Alles wat de navigators nodig hebben, in één momentopname."""
        with self._lock:
            nu = time.time()
            (heading, bron, geldig, pos_leeftijd, vooruit_extra, voorspeld_s,
             pitch, pitch_corr) = self._momentopname(nu)
            pos = self._naar_regelpunt(self.antenne_positie, heading, geldig, vooruit_extra)
            # Voetpunt van de antenne op de grond: daar hoort hoogte_grond_m bij (niet bij het
            # regelpunt, dat kan 0,7 m verderop liggen). Zonder geldige koers: de antenne zelf.
            if geldig:
                grond = self._verplaats(self.antenne_positie, heading, vooruit_extra, 0.0)
            else:
                grond = {"lat": self.antenne_positie["lat"], "lon": self.antenne_positie["lon"]}
            # Hoogte van de grond onder de antenne (GGA geeft de antenne zelf).
            hoogte_grond = None
            if self.antenne_positie["fix"]:
                kanteling = math.cos(math.radians(pitch)) if pitch is not None else 1.0
                hoogte_grond = round(self.antenne_positie["alt_m"] - self.antenne_hoogte_m * kanteling, 3)

            return {
                "lat": pos["lat"],
                "lon": pos["lon"],
                "fix": self.antenne_positie["fix"],
                "fix_soort": self.FIX_SOORT.get(self.antenne_positie["fix"], "onbekend"),
                "hdop": self.antenne_positie["hdop"],
                "sats": self.antenne_positie["sats"],
                "alt_m": self.antenne_positie["alt_m"],
                "heading": heading,
                "heading_bron": bron,
                "heading_geldig": geldig,
                "speed_kmh": self.current_speed_kmh,
                "course_over_ground": self.course_over_ground,
                "draaisnelheid_dps": round(self.draaisnelheid_dps, 2),
                "rijrichting": self.rijrichting,
                "sliphoek_deg": None if self.sliphoek_deg is None else round(self.sliphoek_deg, 1),
                "positie_leeftijd_s": None if pos_leeftijd is None else round(pos_leeftijd, 3),
                "heading_leeftijd_s": round(nu - self.heading_tijd, 3) if self.heading_tijd else None,
                "correctie_leeftijd_s": self.correctie_leeftijd_s,
                "voorspeld_s": round(voorspeld_s, 3),
                "pitch_correctie_m": round(pitch_corr, 3),
                "hoogte_grond_m": hoogte_grond,
                "grond_lat": grond["lat"],
                "grond_lon": grond["lon"],
                "ruwheid_deg": self.ruwheid_deg,
                "antenne_lat": self.antenne_positie["lat"],
                "antenne_lon": self.antenne_positie["lon"],
                **self._dah_velden(nu),
            }

    def _dah_velden(self, nu):
        """NAV-DAHEADING voor de status en de ritlog; None zolang er niets binnenkwam."""
        d = self.dah
        if d is None:
            return {k: None for k in ("baseline_m", "antenne_hoogteverschil_m", "pitch_deg",
                                      "dah_heading", "dah_acc_heading", "dah_oplossing", "dah_leeftijd_s")}
        return {
            "baseline_m": d["baseline_m"],
            "antenne_hoogteverschil_m": d["hoogteverschil_m"],
            "pitch_deg": d["pitch_deg"],
            "dah_heading": d["heading"],
            "dah_acc_heading": d["acc_heading"],
            "dah_oplossing": d["oplossing"],
            "dah_leeftijd_s": round(nu - self.dah_tijd, 2),
        }

    def wacht_op_epoch(self, vorige, timeout=0.1):
        """
        Wacht tot er na epoch 'vorige' een nieuwe complete meting (GGA + THS)
        binnen is, hoogstens 'timeout' seconden. Geeft het nieuwe epochnummer;
        bij een timeout het oude, zodat de navigator toch zijn veiligheids-
        controles doet (geen data = stilstaan).
        """
        with self._epoch_cond:
            self._epoch_cond.wait_for(lambda: self._epoch != vorige, timeout)
            return self._epoch

    def _epoch_deel(self, soort):
        """Aanroepen met de lock vast. Een epoch is rond als GGA en THS er allebei zijn."""
        self._epoch_delen.add(soort)
        if {"GGA", "THS"} <= self._epoch_delen:
            self._epoch_delen.clear()
            self._epoch += 1
            self._epoch_cond.notify_all()

    @property
    def current_position(self):
        """Oude naam, nog gebruikt door de streamer (lat/lon/fix/hdop)."""
        return self.get_current_position()

    def get_diagnostics(self):
        """Gemeten datastromen - handig om te zien of configure_x20d.py goed staat."""
        with self._lock:
            return {
                "positie_hz": self._frequentie(self._gga_tijden),
                "heading_hz": self._frequentie(self._ths_tijden),
                "heading_bron": self.heading_bron,
                "heading_geldig": self.heading_geldig,
                "checksum_fouten": self._checksum_fouten,
                "data_leeftijd_s": round(time.time() - self._laatste_nmea_tijd, 2)
                if self._laatste_nmea_tijd else None,
                "ntrip_status": self.ntrip_status["status"],
                "ntrip_fout": self.ntrip_status["fout"],
                "ntrip_kb": round(self.ntrip_status["bytes"] / 1024, 1),
                "ntrip_leeftijd_s": round(time.time() - self.ntrip_status["laatste_data"], 1)
                if self.ntrip_status["laatste_data"] else None,
                "daheading_hz": self._frequentie(self._dah_tijden),
                "daheading_config": self.dah_config,
                "daheading_afwijkend": self.dah_afwijkend,
                "ubx_berichten": dict(self._ubx_tellers),
            }

    # ------------------------------------------------------------------ #
    #  Inlezen: NMEA-zinnen en binaire UBX-berichten door elkaar
    # ------------------------------------------------------------------ #
    def _lees_stroom(self):
        """
        Eén stroom, alle berichten. Op 25 Hz komt er flink wat over de lijn,
        dus elke zin gaat eerst langs de checksum: een verminkte koers is op
        de stuurregeling gevaarlijker dan even geen koers. Tussen de NMEA door
        komen binaire UBX-berichten (NAV-DAHEADING, ACK/NAK); die hebben geen
        regeleinde, dus we lezen bytes en knippen zelf.
        """
        while self._running and self.ser and self.ser.is_open:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
                if not data:
                    continue
                self._buf += data
                for pakket in self._pakketten():
                    if pakket[0] == "NMEA":
                        self._verwerk_nmea(pakket[1])
                    else:
                        self._verwerk_ubx(pakket[1], pakket[2], pakket[3])
            except Exception:
                time.sleep(0.05)

    def _pakketten(self):
        """Haalt complete NMEA-zinnen en UBX-frames (met geldige checksum) uit de buffer, in volgorde."""
        buf = self._buf
        while True:
            u = buf.find(b"\xb5\x62")
            n = buf.find(b"$")
            if u < 0 and n < 0:
                # Een losse 0xB5 aan het eind kan het begin van een UBX-frame zijn.
                del buf[:-1 if buf.endswith(b"\xb5") else len(buf)]
                return
            if n >= 0 and (u < 0 or n < u):
                eind = buf.find(b"\n", n)
                if eind < 0:
                    if len(buf) - n > 300:
                        del buf[:n + 1]      # rommel zonder regeleinde
                        continue
                    del buf[:n]
                    return
                zin = bytes(buf[n:eind]).decode("ascii", errors="ignore").strip()
                del buf[:eind + 1]
                yield ("NMEA", zin)
                continue
            if len(buf) < u + 6:
                del buf[:u]
                return
            klasse, mid, lengte = buf[u + 2], buf[u + 3], buf[u + 4] | (buf[u + 5] << 8)
            if lengte > 2048:
                del buf[:u + 2]              # valse sync, verder zoeken
                continue
            einde = u + 8 + lengte
            if len(buf) < einde:
                del buf[:u]
                return
            frame = bytes(buf[u:einde])
            del buf[:einde]
            if frame == self._ubx_frame(klasse, mid, frame[6:-2]):
                yield ("UBX", klasse, mid, frame[6:-2])

    def _verwerk_nmea(self, zin):
        if not zin.startswith("$"):
            return
        if not self._checksum_ok(zin):
            with self._lock:
                self._checksum_fouten += 1
            return

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

    # ------------------------------------------------------------------ #
    #  UBX: NAV-DAHEADING aanzetten, opvragen en uitlezen
    # ------------------------------------------------------------------ #
    UBX_ACK, UBX_NAK = (0x05, 0x01), (0x05, 0x00)
    UBX_NAV_DAHEADING = (0x01, 0x45)
    UBX_CFG_VALSET = (0x06, 0x8A)
    # CFG-MSGOUT-UBX_NAV_DAHEADING_<poort>, uit de HDG 2.01 interface description
    DAH_UITVOER = {"USB": 0x209103E2, "UART1": 0x209103E0}
    DAH_OPLOSSING = {0: "geen", 1: "float", 2: "fixed"}

    @staticmethod
    def _ubx_frame(klasse, mid, payload=b""):
        kop = bytes((klasse, mid, len(payload) & 0xFF, len(payload) >> 8))
        a = b = 0
        for x in kop + payload:
            a = (a + x) & 0xFF
            b = (b + a) & 0xFF
        return b"\xb5\x62" + kop + payload + bytes((a, b))

    def _verwerk_ubx(self, klasse, mid, payload):
        with self._lock:
            sleutel = f"{klasse:02X}-{mid:02X}"
            self._ubx_tellers[sleutel] = self._ubx_tellers.get(sleutel, 0) + 1
        if (klasse, mid) in (self.UBX_ACK, self.UBX_NAK) and len(payload) >= 2:
            self._acks[(payload[0], payload[1])] = "ACK" if mid == 0x01 else "NAK"
        elif (klasse, mid) == self.UBX_NAV_DAHEADING:
            self._parse_daheading(payload)

    def _parse_daheading(self, p):
        """
        UBX-NAV-DAHEADING versie 2 (HDG 2.01): vector van antenne 1 (GPS1,
        achter) naar antenne 2 (GPS2, voor) in mm noord/oost/omlaag, plus de
        heading en de nauwkeurigheid in 1e-5 graad en de vlaggen.
        """
        if len(p) < 60 or p[0] != 0x02:
            if self.dah_afwijkend is None:
                print(f"[GNSS] NAV-DAHEADING met onverwacht formaat: versie {p[0] if p else '-'}, "
                      f"{len(p)} bytes: {p[:64].hex()}")
            self.dah_afwijkend = f"versie {p[0] if p else '-'}, {len(p)} bytes: {p[:64].hex()}"
            return
        noord, oost, omlaag, lengte, heading = struct.unpack_from("<iiiii", p, 8)
        acc_heading = struct.unpack_from("<I", p, 48)[0]
        vlaggen = struct.unpack_from("<I", p, 56)[0]
        nu = time.time()
        with self._lock:
            self._dah_tijden.append(nu)
            if not vlaggen & 0x04:           # relPosValid: zonder dit zijn de getallen leeg
                return
            horizontaal = math.hypot(noord, oost)
            self.dah = {
                "baseline_m": round(lengte / 1000.0, 3),
                # + = antenne 2 (voor) ligt hoger dan antenne 1 (achter)
                "hoogteverschil_m": round(-omlaag / 1000.0, 3),
                # Helling van de ROBOT (+ = neus omhoog): baseline-helling min de montage.
                "pitch_deg": round(math.degrees(math.atan2(-omlaag, horizontaal)) - self.pitch_offset_deg, 2)
                if horizontaal else None,
                "heading": round(heading * 1e-5, 3) if vlaggen & 0x40 else None,
                "acc_heading": round(acc_heading * 1e-5, 3) if vlaggen & 0x40 else None,
                "oplossing": self.DAH_OPLOSSING.get((vlaggen >> 3) & 0x03, "?"),
            }
            self.dah_tijd = nu
            self._update_ruwheid(nu, self.dah["pitch_deg"] if self.dah["oplossing"] == "fixed" else None)

    def _update_ruwheid(self, nu, pitch):
        """
        Ruwheid = spreiding (1 sigma) van de pitch over de laatste seconde.
        Op een egale baan vandaag rond 0.5 graad, op hobbels boven 1 graad.
        Een helling zelf telt niet mee (die verandert langzaam), alleen het
        heen en weer gaan van de neus.
        """
        if pitch is None:
            return
        self._pitch_venster.append((nu, pitch))
        while self._pitch_venster and nu - self._pitch_venster[0][0] > 1.0:
            self._pitch_venster.popleft()
        if len(self._pitch_venster) >= 10:
            waarden = [p for _, p in self._pitch_venster]
            gem = sum(waarden) / len(waarden)
            self.ruwheid_deg = round(math.sqrt(sum((p - gem) ** 2 for p in waarden) / len(waarden)), 3)

    def _daheading_bewaken(self):
        """
        Zet NAV-DAHEADING aan op USB en UART1 (alleen RAM), en meldt per poort
        of de ontvanger dat accepteert. Komt er daarna niets binnen, dan
        vragen we er elke seconde om (een poll verandert geen config).
        """
        uitslag = []
        for poort, sleutel in self.DAH_UITVOER.items():
            self._acks.pop(self.UBX_CFG_VALSET, None)
            payload = bytes((0, 0x01, 0, 0)) + struct.pack("<IB", sleutel, 1)   # versie 0, laag RAM
            self._schrijf(self._ubx_frame(*self.UBX_CFG_VALSET, payload))
            eind = time.time() + 1.5
            while time.time() < eind and self.UBX_CFG_VALSET not in self._acks:
                time.sleep(0.05)
            uitslag.append(f"{poort}: {self._acks.get(self.UBX_CFG_VALSET, 'geen antwoord')}")
        self.dah_config = ", ".join(uitslag)
        print(f"[GNSS] NAV-DAHEADING aanzetten (RAM): {self.dah_config}")

        while self._running:
            time.sleep(1.0)
            if time.time() - self.dah_tijd > 2.0 and not self._dah_tijden_recent():
                try:
                    self._schrijf(self._ubx_frame(*self.UBX_NAV_DAHEADING))
                except Exception:
                    pass

    def _dah_tijden_recent(self):
        with self._lock:
            return bool(self._dah_tijden) and time.time() - self._dah_tijden[-1] < 2.0

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
                    self._epoch_deel("GGA")
                return

            lat = self._nmea_naar_decimaal(d[2], d[3])
            lon = self._nmea_naar_decimaal(d[4], d[5])
            # Veld 13: leeftijd van de differentiële correcties (leeg zonder).
            leeftijd = d[13].split("*")[0] if len(d) > 13 else ""
            with self._lock:
                self.antenne_positie = {
                    "lat": lat,
                    "lon": lon,
                    "fix": kwaliteit,          # 1=GPS, 2=DGPS, 4=RTK fixed, 5=RTK float
                    "hdop": float(d[8]) if d[8] else 99.0,
                    "sats": int(d[7]) if d[7] else 0,
                    "alt_m": float(d[9]) if d[9] else 0.0,
                }
                self.correctie_leeftijd_s = float(leeftijd) if leeftijd else None
                self.laatste_gga_zin = zin
                self.gga_tijd = time.time()
                self._gga_tijden.append(self.gga_tijd)
                self._epoch_deel("GGA")
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
            if len(d) < 3:
                return
            status = d[2].split("*")[0].strip().upper()
            # Bij 'V' is het koersveld meestal leeg: eerst de status bekijken,
            # anders blijft de vorige koers tot de timeout als geldig staan.
            koers = float(d[1]) if d[1] else None

            if koers is not None and status in self.THS_GELDIG:
                bron = "THS"
            elif koers is not None and status in self.THS_GESCHAT and self.accepteer_geschatte_heading:
                bron = "THS(geschat)"
            else:
                with self._lock:
                    if self.heading_bron.startswith("THS"):
                        self.heading_geldig = False
                    self._vorige_ths = None
                    self.draaisnelheid_dps = 0.0
                    self._epoch_deel("THS")
                return

            with self._lock:
                nu = time.time()
                koers = (koers + self.heading_offset_deg) % 360.0
                self._update_draaisnelheid(nu, koers)
                self.current_heading = koers
                self.heading_bron = bron
                self.heading_geldig = True
                self.heading_tijd = nu
                self._ths_tijden.append(nu)
                self._epoch_deel("THS")
        except Exception:
            pass

    def _update_draaisnelheid(self, nu, koers):
        """
        Draaisnelheid van de neus uit twee opeenvolgende THS-metingen, door een
        laagdoorlaatfilter: de zinnen komen in klontjes over USB binnen, dus
        losse tijdsverschillen zijn onrustig. Na een gat begint hij opnieuw.
        """
        if self._vorige_ths and 0.005 < nu - self._vorige_ths[0] <= 0.25:
            t0, k0 = self._vorige_ths
            ruw = self._norm180(koers - k0) / (nu - t0)
            self.draaisnelheid_dps += 0.3 * (ruw - self.draaisnelheid_dps)
        elif not self._vorige_ths or nu - self._vorige_ths[0] > 0.25:
            self.draaisnelheid_dps = 0.0
        self._vorige_ths = (nu, koers)

    @staticmethod
    def _norm180(hoek):
        return (hoek + 180.0) % 360.0 - 180.0

    def _update_rijrichting(self):
        """
        Aanroepen met de lock vast, na een nieuwe snelheid. Ligt de beweging
        (course over ground) binnen 60 graden van de neus, dan rijdt hij
        vooruit; meer dan 120 graden ernaast is achteruit. Daartussen (dwars
        wegglijden) en bij stilstand weten we het niet.
        """
        vers = self.heading_geldig and (time.time() - self.heading_tijd) <= self.heading_timeout_s
        if self.current_speed_kmh < 0.5 or not vers:
            if self.current_speed_kmh < 0.5:
                self.rijrichting = 0
            self.sliphoek_deg = None
            return
        verschil = self._norm180(self.course_over_ground - self.current_heading)
        if abs(verschil) < 60.0:
            self.rijrichting, self.sliphoek_deg = 1, verschil
        elif abs(verschil) > 120.0:
            self.rijrichting, self.sliphoek_deg = -1, self._norm180(verschil - 180.0)
        else:
            self.rijrichting, self.sliphoek_deg = 0, verschil

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
                    self._update_rijrichting()
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
                        self._update_rijrichting()
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
            # Course over ground is de richting van de BEWEGING, niet van de
            # antennelijn: heading_offset_deg hoort er dus niet bij. Reed hij
            # (volgens de laatste THS) achteruit, dan wijst de neus de andere
            # kant op.
            cog = self.course_over_ground + (180.0 if self.rijrichting < 0 else 0.0)
            return cog % 360.0, "VTG", True

        return self.current_heading, "geen", False

    def _naar_regelpunt(self, antenne, heading, heading_geldig, vooruit_extra=0.0):
        """
        Verschuift de gemeten antennepositie naar het regelpunt van de robot,
        plus 'vooruit_extra' meter langs de neus (latentie en pitch).

        Zonder betrouwbare koers kunnen we niet weten welke kant 'vooruit' op
        wijst; dan geven we de antennepositie ongewijzigd terug.
        """
        if not heading_geldig:
            return {"lat": antenne["lat"], "lon": antenne["lon"]}
        return self._verplaats(antenne, heading, self.antenne_offset_vooruit_m + vooruit_extra,
                               self.antenne_offset_rechts_m)

    @staticmethod
    def _verplaats(antenne, heading, vooruit, rechts):
        """Punt 'vooruit' / 'rechts' meter van de antenne, in het voertuigframe met deze koers."""
        if vooruit == 0.0 and rechts == 0.0:
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
        if not self.ntrip_cfg.get("host"):
            self.ntrip_status["status"] = "uit (geen ntrip-config)"
            return
        while self._running:
            sock = None
            try:
                sock, data = self._ntrip_verbind()
                print(f"[NTRIP] Verbonden met {self.ntrip_cfg['host']}/{self.ntrip_cfg['mountpoint']}, "
                      "correcties gaan naar de ZED-X20D...")
                self.ntrip_status.update(status="verbonden", fout=None)
                sock.settimeout(1.0)
                laatste_gga = 0.0
                laatste_data = time.time()

                while self._running:
                    if data:
                        laatste_data = time.time()
                        self.ntrip_status["bytes"] += len(data)
                        self.ntrip_status["laatste_data"] = laatste_data
                        self._schrijf(data)

                    # VRS- en 'NEAR'-mountpoints kiezen de dichtstbijzijnde
                    # basis op basis van onze eigen positie en sturen pas
                    # data na de eerste GGA. Zodra er een fix is gaat hij
                    # dus meteen weg, daarna elke gga_interval_s.
                    nu = time.time()
                    if self.ntrip_gga_interval_s > 0 and (nu - laatste_gga) >= self.ntrip_gga_interval_s:
                        with self._lock:
                            gga = self.laatste_gga_zin
                        if gga:
                            sock.sendall((gga + "\r\n").encode())
                            laatste_gga = nu

                    # Zonder fix (nog geen GGA) mag de caster zwijgen;
                    # met fix is 30 s stilte een dode verbinding.
                    if self.laatste_gga_zin is not None and nu - laatste_data > 30.0:
                        raise ConnectionError("30 s geen correcties ontvangen")
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        data = b""
                        continue
                    if not data:
                        raise ConnectionError("caster heeft de verbinding gesloten")
            except Exception as e:
                self.ntrip_status.update(status="herverbinden", fout=str(e))
                print(f"[NTRIP ERROR] {e} - herverbinden in 5 s")
            finally:
                if sock:
                    sock.close()
            time.sleep(5)

    def _ntrip_verbind(self):
        """
        Verbindt met de caster en controleert het antwoord. Geeft de socket en
        de eerste RTCM-bytes die al achter de header zaten.
        """
        c = self.ntrip_cfg
        auth = base64.b64encode(f"{c['user']}:{c['pass']}".encode()).decode()
        request = (
            f"GET /{c['mountpoint']} HTTP/1.0\r\n"
            f"Host: {c['host']}:{c['port']}\r\n"
            f"Ntrip-Version: Ntrip/2.0\r\n"
            f"Authorization: Basic {auth}\r\n"
            f"User-Agent: NTRIP BruutAgbot/2.0\r\n\r\n"
        )
        sock = socket.create_connection((c['host'], int(c['port'])), timeout=10)
        try:
            sock.sendall(request.encode())
            antwoord = b""
            # NTRIP 1 antwoordt 'ICY 200 OK\r\n', NTRIP 2 met HTTP-headers.
            while b"\r\n\r\n" not in antwoord and not antwoord.startswith(b"ICY 200 OK\r\n"):
                stuk = sock.recv(1024)
                if not stuk:
                    break
                antwoord += stuk
                if len(antwoord) > 8192:
                    break
            eerste = antwoord.split(b"\r\n", 1)[0].decode(errors="ignore")
            # Let op: een onbekend mountpoint geeft 'SOURCETABLE 200 OK'.
            if eerste.startswith("SOURCETABLE"):
                raise ConnectionError(f"mountpoint '{c['mountpoint']}' bestaat niet op deze caster")
            if " 200" not in eerste:
                if " 401" in eerste:
                    raise ConnectionError("gebruikersnaam/wachtwoord geweigerd (401)")
                raise ConnectionError(f"caster antwoordt: {eerste or '(niets)'}")
            if antwoord.startswith(b"ICY 200 OK\r\n"):
                # Daarna soms een lege regel, dan direct RTCM - en dat kan zelf
                # ook \r\n\r\n bevatten, dus daar niet op splitsen.
                rest = antwoord[len(b"ICY 200 OK\r\n"):]
                if rest.startswith(b"\r\n"):
                    rest = rest[2:]
            else:
                rest = antwoord.split(b"\r\n\r\n", 1)[1]
            return sock, rest
        except Exception:
            sock.close()
            raise
