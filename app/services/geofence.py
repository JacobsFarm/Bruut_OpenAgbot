"""
Geofence: de robot rijdt de sloot niet in, of hij nu een missie rijdt of met
de hand bestuurd wordt.

Twee bronnen van grenzen:

  KAART    data/kaart.json (formaat openagbot.kaart). De verboden gebieden van
           de hele boerderij: sloten en water met hun slootzone, wegen, dijken,
           gebouwen, verboden gebieden en nesten (alleen in hun periode). Wordt
           bij het opstarten geladen en geldt ALTIJD, ook zonder missie.
  MISSIE   het blok 'geofence' uit een veldmissie. Geldt zolang die missie
           loopt en voegt het toegestane gebied toe (binnen het veld blijven).

De GeofenceBewaker rekent op het ritme van de GNSS (25 Hz) de hoeken van robot
en werktuig uit en kijkt een remweg vooruit en achteruit langs de bocht die nu
gestuurd wordt. Het resultaat is een POORT voor de VehicleController:

  vooruit / achteruit   mag er in die richting gereden worden?
  reden                 waarom niet ("sloot Molensloot")
  max_kmh               snelheidsgrens (alleen tijdens overbruggen)

De VehicleController vraagt de poort in zijn regellus (50 Hz) op en zet de
wielen stil zodra de rijrichting dicht is. Daardoor maakt het niet uit WIE er
rijdt: waypoints, AB-lijn, veldmissie of de joystick gaan allemaal door
dezelfde poort. Een richting is dicht als de robot daar een verboden gebied
in zou rijden; de andere richting blijft open, zodat je er met de hand weer
uit kunt rijden. Sta je er toch helemaal in (kaart klopt niet, robot erin
gezet), dan kan de bewaking een minuut overbrugd worden: alleen langzaam.

Alles in pure Python, zonder shapely: een kaart heeft tientallen veelhoeken
met elk een paar honderd punten, en per veelhoek liggen de randen in banden
van 2 m, zodat een punt maar tegen een handvol randen getest wordt.
"""
import os
import json
import math
import time
import logging
import datetime
import threading
from collections import namedtuple

R_EARTH = 6371000.0
KAART_FORMAT = "openagbot.kaart"
KAART_FILE = os.path.join("data", "kaart.json")
BAND_M = 2.0

SOORT_TEKST = {
    "water": "sloot", "weg": "weg", "dijk": "dijk", "gebouw": "gebouw", "verboden": "verboden gebied",
    "nest": "nest", "hek": "hek", "boom": "boom", "marker": "marker", "gat": "gat in het veld",
}

Poort = namedtuple("Poort", "vooruit achteruit reden max_kmh")
OPEN = Poort(True, True, None, None)


class Frame:
    """Lokale meters rond een referentiepunt: x = oost, y = noord."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.kx = R_EARTH * math.radians(1.0) * math.cos(math.radians(self.lat0))
        self.ky = R_EARTH * math.radians(1.0)

    def xy(self, lat, lon):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def latlon(self, x, y):
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx


class Veelhoek:
    """Veelhoek met gaten in lokale meters. Even-oneven over alle ringen, dus een gat telt als buiten."""

    def __init__(self, ringen):
        self.randen = []
        for ring in ringen:
            n = len(ring)
            for i in range(n):
                (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
                if x1 != x2 or y1 != y2:
                    self.randen.append((x1, y1, x2, y2))
        xs = [r[0] for r in self.randen] or [0.0]
        ys = [r[1] for r in self.randen] or [0.0]
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
        # Randen per horizontale band: voor punt-in-veelhoek tellen alleen de
        # randen die de hoogte van het punt kruisen.
        self.banden = {}
        for r in self.randen:
            lo, hi = (r[1], r[3]) if r[1] <= r[3] else (r[3], r[1])
            for b in range(int(math.floor((lo - self.y0) / BAND_M)), int(math.floor((hi - self.y0) / BAND_M)) + 1):
                self.banden.setdefault(b, []).append(r)

    def bevat(self, x, y):
        if x < self.x0 or x > self.x1 or y < self.y0 or y > self.y1:
            return False
        binnen = False
        for x1, y1, x2, y2 in self.banden.get(int(math.floor((y - self.y0) / BAND_M)), ()):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                binnen = not binnen
        return binnen

    def afstand(self, x, y):
        """Kortste afstand van het punt tot de rand (m)."""
        best = float("inf")
        for x1, y1, x2, y2 in self.randen:
            dx, dy = x2 - x1, y2 - y1
            t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if d < best:
                best = d
        return best


class Zone:
    def __init__(self, veelhoek, soort, naam, id_, stoppen=True, van=None, tot=None):
        self.veelhoek = veelhoek
        self.soort = soort
        self.naam = naam or ""
        self.id = id_ or ""
        self.stoppen = stoppen
        self.van, self.tot = van, tot          # "MM-DD": alleen in die periode (nest)

    @property
    def tekst(self):
        soort = SOORT_TEKST.get(self.soort, self.soort)
        return soort if not self.naam or self.naam == soort else f"{soort} {self.naam}"

    def geldt(self, dag):
        """Geldt de zone op deze dag? Zonder (leesbare) periode: altijd."""
        if not self.van or not self.tot:
            return True
        try:
            a = tuple(int(v) for v in self.van.split("-"))
            b = tuple(int(v) for v in self.tot.split("-"))
        except ValueError:
            return True
        d = (dag.month, dag.day)
        return a <= d <= b if a <= b else (d >= a or d <= b)


def _ring(punten, wat):
    """[[lat, lon], ...] controleren; een gesloten ring mag zijn eerste punt herhalen."""
    if not isinstance(punten, list) or len(punten) < 3:
        raise ValueError(f"{wat}: een veelhoek heeft minstens 3 punten")
    uit = []
    for p in punten:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{wat}: punt {p!r} is geen [lat, lon]")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or (lat == 0.0 and lon == 0.0):
            raise ValueError(f"{wat}: punt {p!r} is geen geldige positie")
        uit.append((lat, lon))
    if len(uit) > 3 and uit[0] == uit[-1]:
        uit.pop()
    return uit


class Grenzen:
    """Verboden zones plus (optioneel) het gebied waarbinnen gebleven moet worden, in lokale meters."""

    def __init__(self, frame, zones, toegestaan=None, werkgebied=None):
        self.frame = frame
        self.zones = zones                 # [Zone]
        self.toegestaan = toegestaan or [] # [Veelhoek]: binnen minstens een ervan blijven
        self.werkgebied = werkgebied       # Veelhoek of None: daarbuiten nooit
        self._dag = None
        self._actief = []

    @staticmethod
    def eerste_punt(data):
        """Een punt van de kaart als referentie voor het lokale frame."""
        for bron in (data.get("werkgebied"), *[z.get("polygon") for z in data.get("verboden", [])],
                     *[t.get("polygon") for t in data.get("toegestaan", [])]):
            if bron:
                return float(bron[0][0]), float(bron[0][1])
        return None

    @classmethod
    def uit_dict(cls, data, frame=None):
        """Uit een kaart (openagbot.kaart) of het blok 'geofence' van een veldmissie. Gooit ValueError."""
        if not isinstance(data, dict):
            raise ValueError("geen JSON-object")
        ref = cls.eerste_punt(data)
        if frame is None:
            if ref is None:
                raise ValueError("de kaart heeft geen enkel gebied")
            frame = Frame(*ref)

        def veelhoek(blok, wat):
            ringen = [_ring(blok.get("polygon"), wat)] + [_ring(g, wat + " (gat)") for g in blok.get("gaten", [])]
            return Veelhoek([[frame.xy(lat, lon) for lat, lon in r] for r in ringen])

        zones = []
        for i, z in enumerate(data.get("verboden", [])):
            wat = f"verboden gebied {i + 1} ({z.get('naam') or z.get('soort') or '?'})"
            zones.append(Zone(veelhoek(z, wat), z.get("soort", "verboden"), z.get("naam"), z.get("id"),
                              stoppen=z.get("actie", "stoppen") != "mijden", van=z.get("van"), tot=z.get("tot")))
        toegestaan = [veelhoek(t, f"toegestaan gebied {i + 1}") for i, t in enumerate(data.get("toegestaan", []))]
        werkgebied = None
        if data.get("werkgebied"):
            werkgebied = Veelhoek([[frame.xy(lat, lon) for lat, lon in _ring(data["werkgebied"], "werkgebied")]])
        return cls(frame, zones, toegestaan, werkgebied)

    def actieve_zones(self):
        dag = datetime.date.today()
        if dag != self._dag:
            self._dag = dag
            self._actief = [z for z in self.zones if z.geldt(dag)]
        return self._actief


class GeofenceBewaker:
    def __init__(self, gps_system, config, kromming=None):
        self.logger = logging.getLogger(__name__)
        self.gps = gps_system
        self.kromming = kromming             # callable: 1/m van de gestuurde bocht, + = rechts

        v = config.get("vehicle", {})
        c = config.get("geofence", {})
        self.aan = bool(c.get("enabled", True))
        self.wielbasis = float(v.get("wheelbase_m", 1.2))
        self.half_robot = float(v.get("track_width_m", 1.0)) / 2.0 + float(c.get("robot_marge_m", 0.15))
        self.voor = self.wielbasis + float(c.get("overhang_voor_m", 0.25))
        self.achter = -float(c.get("overhang_achter_m", 0.25))
        self.werktuig_half = float(c.get("werktuig_halve_breedte_m", 0.0))
        self.werktuig_vooruit = float(c.get("werktuig_vooruit_m", -0.6))
        self.reactie_s = float(c.get("reactietijd_s", 0.3))
        self.rem_mps2 = max(0.2, float(c.get("rem_mps2", 1.5)))
        self.kijk_min_m = float(c.get("vooruitkijk_min_m", 0.3))
        self.marge_zonder_rtk = float(c.get("marge_zonder_rtk_m", 1.0))
        self.zonder_positie = c.get("zonder_positie", "rijden")     # rijden | stop
        self.toegestaan_marge = float(c.get("toegestaan_marge_m", 0.3))
        self.overbrug_kmh = float(c.get("overbrug_max_kmh", 1.5))
        self.overbrug_s = float(c.get("overbrug_s", 60.0))

        self._lock = threading.Lock()
        self.kaart = None                    # Grenzen uit data/kaart.json
        self.kaart_info = None               # naam, gemaakt, aantallen (voor de UI)
        self.kaart_fout = None
        self.missie = None                   # Grenzen van de lopende missie
        self.missie_half = 0.0               # halve werkbreedte van die missie
        self._missie_scherp = False          # toegestaan gebied telt zodra de robot er helemaal in staat

        self._poort = OPEN
        self._poort_tijd = 0.0
        self._overbrug_tot = 0.0
        self.toestand = "uit"                # uit | geen_kaart | geen_positie | vrij | dicht | overbrugd
        self.waarschuwing = None
        self.binnen = []                     # zones waar robot of werktuig nu in staat
        self.laatste_stop = None
        self.stops = 0
        self.rekentijd_ms = 0.0

        self.laad_kaart()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="geofence")
        self.thread.start()

    # ------------------------------------------------------------------
    #  Kaart en missie
    # ------------------------------------------------------------------
    def laad_kaart(self):
        """data/kaart.json lezen. Een onleesbare kaart is een FOUT: dan staat de poort dicht."""
        if not os.path.exists(KAART_FILE):
            with self._lock:
                self.kaart, self.kaart_info, self.kaart_fout = None, None, None
            return
        try:
            with open(KAART_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            grenzen = Grenzen.uit_dict(data)
        except Exception as e:
            self.logger.error(f"Geofence: {KAART_FILE} is onleesbaar: {e}")
            with self._lock:
                self.kaart, self.kaart_info = None, None
                self.kaart_fout = f"kaart onleesbaar: {e}"
            return
        with self._lock:
            self.kaart = grenzen
            self.kaart_fout = None
            self.kaart_info = {
                "naam": data.get("naam", ""), "gemaakt": data.get("gemaakt"),
                "verboden": len(grenzen.zones),
                "stop_zones": sum(1 for z in grenzen.zones if z.stoppen),
                "werkgebied": grenzen.werkgebied is not None,
                "slootzone_m": data.get("slootzone_m"),
            }
        self.logger.info(f"Geofence: kaart '{data.get('naam', '')}' geladen, {len(grenzen.zones)} gebieden.")

    def bewaar_kaart(self, data):
        """Nieuwe kaart controleren, wegschrijven en in gebruik nemen. Gooit ValueError bij een ongeldige kaart."""
        if not isinstance(data, dict) or data.get("format") != KAART_FORMAT:
            raise ValueError(f"geen kaartbestand (verwacht \"format\": \"{KAART_FORMAT}\")")
        Grenzen.uit_dict(data)               # eerst controleren, dan pas de oude kaart vervangen
        os.makedirs(os.path.dirname(KAART_FILE), exist_ok=True)
        tmp = KAART_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, KAART_FILE)
        self.laad_kaart()
        return self.kaart_info

    def wis_kaart(self):
        if os.path.exists(KAART_FILE):
            os.remove(KAART_FILE)
        self.laad_kaart()

    @staticmethod
    def lees_kaart():
        """De kaart zoals hij op schijf staat (voor de webinterface), of None."""
        if not os.path.exists(KAART_FILE):
            return None
        with open(KAART_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def zet_missie(self, geofence, halve_breedte_m=None):
        """Grenzen van een missie in gebruik nemen (None = geen missie meer). Gooit ValueError."""
        if not geofence:
            with self._lock:
                self.missie, self.missie_half, self._missie_scherp = None, 0.0, False
            return
        grenzen = Grenzen.uit_dict(geofence)
        with self._lock:
            self.missie = grenzen
            self.missie_half = float(halve_breedte_m or geofence.get("halve_breedte_m") or 0.0)
            self._missie_scherp = False

    # ------------------------------------------------------------------
    #  Overbruggen
    # ------------------------------------------------------------------
    def overbrug(self, seconden=None):
        """Bewaking tijdelijk overbruggen om met de hand uit een gebied te rijden (langzaam)."""
        duur = min(float(seconden or self.overbrug_s), 300.0)
        self._overbrug_tot = time.monotonic() + duur
        self.logger.warning(f"Geofence {duur:.0f} s OVERBRUGD (max {self.overbrug_kmh} km/h).")
        return duur

    def stop_overbrugging(self):
        self._overbrug_tot = 0.0

    @property
    def overbrugd_s(self):
        return max(0.0, self._overbrug_tot - time.monotonic())

    # ------------------------------------------------------------------
    #  De poort
    # ------------------------------------------------------------------
    def poort(self):
        """Voor de VehicleController. Reageert de bewaking niet meer, dan staat de poort dicht."""
        if not self.aan:
            return OPEN
        p = self._poort
        if (self.kaart is not None or self.missie is not None) and time.monotonic() - self._poort_tijd > 1.0:
            return Poort(False, False, "geofence-bewaking reageert niet", None)
        return p

    def _loop(self):
        epoch = -1
        laatste_log = 0.0
        while self.running:
            try:
                epoch = self.gps.wacht_op_epoch(epoch, timeout=0.2)
                t0 = time.perf_counter()
                self._stap()
                self.rekentijd_ms += ((time.perf_counter() - t0) * 1000.0 - self.rekentijd_ms) * 0.05
            except Exception as e:
                # Een fout in de bewaking mag niet stil een open poort achterlaten.
                self._zet(Poort(False, False, f"geofence-fout: {e}", None), "dicht")
                if time.monotonic() - laatste_log > 5.0:
                    laatste_log = time.monotonic()
                    self.logger.exception(f"Fout in de geofence-bewaking: {e}")
                time.sleep(0.2)

    def _zet(self, poort, toestand, waarschuwing=None, binnen=()):
        self.toestand = toestand
        self.waarschuwing = waarschuwing
        self.binnen = list(binnen)
        self._poort = poort
        self._poort_tijd = time.monotonic()

    def _hoeken(self, x, y, heading, marge, werktuig_half):
        """Hoeken en zijmiddens van de robot plus de einden van het werktuig, in lokale meters."""
        h = math.radians(heading)
        fx, fy = math.sin(h), math.cos(h)
        rx, ry = fy, -fx
        half = self.half_robot + marge
        mid = (self.voor + self.achter) / 2.0
        lokaal = [(self.achter - marge, -half), (self.achter - marge, half),
                  (self.voor + marge, -half), (self.voor + marge, half),
                  (mid, -half), (mid, half), (self.voor + marge, 0.0), (self.achter - marge, 0.0)]
        if werktuig_half > half - marge:
            w = werktuig_half + marge
            lokaal += [(self.werktuig_vooruit, -w), (self.werktuig_vooruit, w),
                       (self.werktuig_vooruit, -(w + half) / 2.0), (self.werktuig_vooruit, (w + half) / 2.0)]
        return [(x + fx * f + rx * r, y + fy * f + ry * r) for f, r in lokaal]

    @staticmethod
    def _verder(x, y, heading, afstand, kromming):
        """Positie en koers na 'afstand' meter (negatief = achteruit) langs de gestuurde bocht."""
        h = math.radians(heading)
        if abs(kromming) < 1e-4:
            return x + afstand * math.sin(h), y + afstand * math.cos(h), heading
        dh = afstand * kromming              # + = naar rechts = kompaskoers neemt toe
        r = 1.0 / kromming
        # Middelpunt van de bocht ligt r meter rechts van de robot.
        cx, cy = x + r * math.cos(h), y - r * math.sin(h)
        h2 = h + dh
        return cx - r * math.cos(h2), cy + r * math.sin(h2), math.degrees(h2)

    def _tel(self, punten, bronnen, scherp):
        """Aantal punten op een verboden plek, de eerste reden, en de geraakte zones."""
        fout, reden, geraakt, mijden = 0, None, [], None
        for bron, frame_punten in zip(bronnen, punten):
            if bron is None:
                continue
            zones = bron.actieve_zones()
            for (x, y) in frame_punten:
                slecht = None
                for z in zones:
                    if z.veelhoek.bevat(x, y):
                        if z.stoppen:
                            slecht = z.tekst
                            if z not in geraakt:
                                geraakt.append(z)
                            break
                        mijden = z.tekst
                if slecht is None and bron.werkgebied is not None and not bron.werkgebied.bevat(x, y):
                    slecht = "buiten het werkgebied van de kaart"
                if slecht is None and scherp and bron is self.missie and bron.toegestaan:
                    if not any(t.bevat(x, y) for t in bron.toegestaan):
                        if min(t.afstand(x, y) for t in bron.toegestaan) > self.toegestaan_marge:
                            slecht = "buiten het veld van de missie"
                if slecht is not None:
                    fout += 1
                    reden = reden or slecht
        return fout, reden, geraakt, mijden

    def _stap(self):
        if not self.aan:
            self._zet(OPEN, "uit")
            return
        if self.kaart_fout:
            self._zet(Poort(False, False, self.kaart_fout, None), "dicht")
            return
        with self._lock:
            kaart, missie, missie_half = self.kaart, self.missie, self.missie_half
        if kaart is None and missie is None:
            self._zet(OPEN, "geen_kaart")
            return
        overbrugd = self.overbrugd_s > 0.0
        if overbrugd:
            # Wel blijven rekenen, zodat de webinterface laat zien waar hij in staat.
            pass

        pos = self.gps.get_current_position()
        leeftijd = pos.get("positie_leeftijd_s")
        geldig = (pos.get("fix", 0) != 0 and not (pos.get("lat", 0.0) == 0.0 and pos.get("lon", 0.0) == 0.0)
                  and pos.get("heading_geldig", False) and (leeftijd is None or leeftijd <= 1.0))
        if not geldig:
            tekst = "geen GNSS-positie of -koers: de geofence kan niet bewaken"
            if overbrugd:
                self._zet(Poort(True, True, None, self.overbrug_kmh), "overbrugd", tekst)
            elif self.zonder_positie == "stop":
                self._zet(Poort(False, False, tekst, None), "dicht", tekst)
            else:
                self._zet(OPEN, "geen_positie", tekst)
            return

        marge = 0.0 if pos.get("fix") == 4 else self.marge_zonder_rtk
        v = abs(pos.get("speed_kmh", 0.0)) / 3.6
        kijk = max(self.kijk_min_m, v * self.reactie_s + v * v / (2.0 * self.rem_mps2))
        k = self.kromming() if self.kromming else 0.0
        heading = pos["heading"]
        werktuig_half = max(self.werktuig_half, missie_half if missie is not None else 0.0)

        bronnen = (kaart, missie)
        frames = [b.frame.xy(pos["lat"], pos["lon"]) if b is not None else None for b in bronnen]

        def punten(afstand):
            uit = []
            for b, xy in zip(bronnen, frames):
                if b is None:
                    uit.append(None)
                    continue
                x, y, h = self._verder(xy[0], xy[1], heading, afstand, k) if afstand else (xy[0], xy[1], heading)
                uit.append(self._hoeken(x, y, h, marge, werktuig_half))
            return uit

        nu = punten(0.0)
        # Het toegestane gebied van de missie telt pas als de robot er een keer helemaal in stond:
        # de aanloop naar het veld begint er meestal net buiten.
        if missie is not None and missie.toegestaan and not self._missie_scherp:
            if all(any(t.bevat(x, y) for t in missie.toegestaan) for x, y in nu[1]):
                self._missie_scherp = True
        scherp = self._missie_scherp

        n0, reden0, geraakt, mijden = self._tel(nu, bronnen, scherp)
        nv, reden_v, _, _ = self._tel(punten(kijk), bronnen, scherp)
        na, reden_a, _, _ = self._tel(punten(-kijk), bronnen, scherp)
        # Een richting is open als de robot daar nergens in komt, of er verder UIT komt dan hij nu staat.
        vooruit = nv == 0 or nv < n0
        achteruit = na == 0 or na < n0
        reden = None
        if not vooruit:
            reden = reden_v or reden0
        elif not achteruit:
            reden = reden_a or reden0
        binnen = [{"soort": z.soort, "naam": z.naam, "id": z.id, "tekst": z.tekst} for z in geraakt]
        waarschuwing = None
        if mijden:
            waarschuwing = f"raakt {mijden}"
        elif marge > 0.0:
            waarschuwing = f"geen RTK fixed: {marge:.1f} m extra afstand"

        if overbrugd:
            self._zet(Poort(True, True, None, self.overbrug_kmh), "overbrugd",
                      f"bewaking overbrugd ({reden or reden0})" if (reden or reden0) else "bewaking overbrugd", binnen)
            return
        was_dicht = not self._poort.vooruit
        self._zet(Poort(vooruit, achteruit, reden, None), "vrij" if vooruit and achteruit else "dicht",
                  waarschuwing, binnen)
        if not vooruit and not was_dicht:
            self.stops += 1
            self.laatste_stop = {
                "tijd": datetime.datetime.now().strftime("%H:%M:%S"), "reden": reden,
                "lat": pos["lat"], "lon": pos["lon"], "snelheid_kmh": round(pos.get("speed_kmh", 0.0), 2),
            }
            self.logger.warning(f"Geofence: vooruit DICHT, {reden} (remweg {kijk:.2f} m).")

    def omtrek(self):
        """Hoeken van robot en werktuig in lat/lon, om op de kaart te tekenen. None zonder positie."""
        pos = self.gps.get_current_position()
        if not pos.get("heading_geldig") or (pos.get("lat", 0.0) == 0.0 and pos.get("lon", 0.0) == 0.0):
            return None
        f = Frame(pos["lat"], pos["lon"])
        half = max(self.werktuig_half, self.missie_half if self.missie is not None else 0.0)
        p = self._hoeken(0.0, 0.0, pos["heading"], 0.0, half)
        robot = [f.latlon(*p[i]) for i in (0, 1, 3, 2)]
        werktuig = [f.latlon(*p[i]) for i in (8, 9)] if len(p) > 8 else None
        return {"robot": [[round(a, 8), round(b, 8)] for a, b in robot],
                "werktuig": None if werktuig is None else [[round(a, 8), round(b, 8)] for a, b in werktuig]}

    def status(self):
        p = self.poort()
        return {
            "aan": self.aan,
            "toestand": self.toestand if p is self._poort else "dicht",
            "vooruit": p.vooruit, "achteruit": p.achteruit, "reden": p.reden, "max_kmh": p.max_kmh,
            "waarschuwing": self.waarschuwing,
            "binnen": self.binnen,
            "kaart": self.kaart_info, "kaart_fout": self.kaart_fout,
            "missie_grenzen": self.missie is not None, "missie_scherp": self._missie_scherp,
            "overbrugd_s": round(self.overbrugd_s, 1),
            "laatste_stop": self.laatste_stop, "stops": self.stops,
            "rekentijd_ms": round(self.rekentijd_ms, 2),
        }

    def shutdown(self):
        self.running = False
