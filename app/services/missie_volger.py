"""
MissieVolger: rijdt een veldmissie (formaat openagbot.veldmissie, gemaakt in
openagbot-fieldsim) als EEN doorlopend pad in plaats van van punt naar punt.

Een missie is een lijst segmenten in rijvolgorde: 'rondje' (kopakker), 'baan'
(recht), 'bocht' en 'overgang' (Dubins-bogen), en bij een boerderijmissie
'transport' en 'doorgang'. Elk segment heeft zijn eigen snelheid en zegt of
het werktuig omlaag hoort.

  - Voortgang = de projectie van de robot op het pad, alleen vooruit en
    gezocht in een venster rond de vorige plek. Een rondje dat vlak langs een
    eerder rondje loopt kan daardoor niet verspringen.
  - Rechte banen stuurt de LijnRegelaar (Stanley met integrator, net als de
    AB-banen). Bochten, rondjes en overgangen gaan met pure pursuit op een
    punt 'lookahead' meter verder LANGS HET PAD.
  - Snelheid per segment, en op tijd afremmen voor een langzamer segment.
  - Een doorgang met 'bevestigen' (oversteek over een weg): stoppen aan het
    begin en wachten op vrijgave.
  - De voortgang staat in data/missie_voortgang.json, zodat een missie na een
    stop (accu, storing, geofence) hervat kan worden.

De geofence van de missie gaat bij de start naar de GeofenceBewaker en geldt
tot de missie stopt; de kaart (data/kaart.json) geldt daarnaast altijd.

Missies staan in data/missies/<naam>.json.
"""
import os
import re
import json
import math
import time
import logging
import threading

from app.services.gnss_navigatie import GnssBewaker, LijnRegelaar, norm180
from app.services.geofence import Frame

try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

MISSIE_FORMAT = "openagbot.veldmissie"
MISSIES_DIR = os.path.join("data", "missies")
VOORTGANG_FILE = os.path.join("data", "missie_voortgang.json")
NAAM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,60}$")


def controleer_naam(naam):
    if not NAAM_RE.match(naam or ""):
        raise ValueError("naam van een missie: alleen letters, cijfers, - en _ (max 60 tekens)")
    return naam


def controleer_missie(data):
    """Controleert een missiebestand. Gooit ValueError met een leesbare reden."""
    if not isinstance(data, dict) or data.get("format") != MISSIE_FORMAT:
        raise ValueError(f"geen missiebestand (verwacht \"format\": \"{MISSIE_FORMAT}\")")
    segmenten = data.get("segmenten")
    if not isinstance(segmenten, list) or not segmenten:
        raise ValueError("de missie heeft geen segmenten")
    for i, sg in enumerate(segmenten):
        punten = sg.get("punten") if isinstance(sg, dict) else None
        if not isinstance(punten, list) or len(punten) < 2:
            raise ValueError(f"segment {i}: minstens 2 punten nodig")
        for p in punten:
            try:
                lat, lon = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                raise ValueError(f"segment {i}: punt {p!r} is geen [lat, lon]")
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or (lat == 0.0 and lon == 0.0):
                raise ValueError(f"segment {i}: punt {p!r} is geen geldige positie")
        if float(sg.get("snelheid_kmh", 0.0)) <= 0.0:
            raise ValueError(f"segment {i}: snelheid_kmh ontbreekt")
    return data


def onveilig(data):
    """Reden waarom deze missie niet gereden mag worden (afgekeurd door de controle vooraf), of None."""
    slecht = [sg.get("label", f"segment {i}") for i, sg in enumerate(data.get("segmenten", []))
              if sg.get("veilig") is False]
    if slecht or data.get("veiligheid", {}).get("ok") is False:
        wat = ", ".join(slecht[:3]) or "de route"
        return f"de veiligheidscontrole van de planner keurt deze missie af ({wat} raakt een verboden gebied)"
    return None


def samenvatting(naam, data):
    """Korte gegevens van een missie voor de lijst in de webinterface."""
    segmenten = data.get("segmenten", [])
    cijfers = data.get("cijfers", {}) or {}
    velden = [v.get("naam") or v.get("id") for v in data.get("velden", [])]
    if not velden and data.get("veld"):
        velden = [data["veld"].get("naam") or data["veld"].get("id")]
    return {
        "naam": naam,
        "soort": data.get("soort", "veld"),
        "gemaakt": data.get("gemaakt"),
        "velden": velden,
        "segmenten": len(segmenten),
        "lengte_m": cijfers.get("length_m"),
        "tijd_min": cijfers.get("time_min"),
        "werkbreedte_m": data.get("werkbreedte_m"),
        "geofence": bool(data.get("geofence")),
        "afgekeurd": onveilig(data),
    }


class MissieOpslag:
    """De missies in data/missies/."""

    @staticmethod
    def pad(naam):
        return os.path.join(MISSIES_DIR, controleer_naam(naam) + ".json")

    @classmethod
    def lijst(cls):
        uit = []
        if not os.path.isdir(MISSIES_DIR):
            return uit
        for bestand in sorted(os.listdir(MISSIES_DIR)):
            if not bestand.endswith(".json"):
                continue
            naam = bestand[:-5]
            try:
                with open(os.path.join(MISSIES_DIR, bestand), "r", encoding="utf-8") as f:
                    uit.append(samenvatting(naam, json.load(f)))
            except Exception as e:
                uit.append({"naam": naam, "fout": str(e)})
        return uit

    @classmethod
    def lees(cls, naam):
        pad = cls.pad(naam)
        if not os.path.exists(pad):
            return None
        with open(pad, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def bewaar(cls, naam, data):
        controleer_missie(data)
        pad = cls.pad(naam)
        os.makedirs(MISSIES_DIR, exist_ok=True)
        tmp = pad + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, pad)
        return samenvatting(naam, data)

    @classmethod
    def wis(cls, naam):
        pad = cls.pad(naam)
        if os.path.exists(pad):
            os.remove(pad)
            return True
        return False


class Pad:
    """Het rijpad van een missie als een polylijn met booglengte, in lokale meters."""

    def __init__(self, data):
        segmenten = data["segmenten"]
        lat0, lon0 = segmenten[0]["punten"][0][:2]
        self.frame = Frame(lat0, lon0)
        self.px, self.py, self.ps = [], [], []
        self.iseg = [0]                  # iseg[i]: segment van het stuk dat EINDIGT in punt i
        self.segmenten = []
        doorgangen = {d.get("id"): d for d in data.get("doorgangen", [])}
        for k, sg in enumerate(segmenten):
            s0 = self.ps[-1] if self.ps else 0.0
            for p in sg["punten"]:
                x, y = self.frame.xy(float(p[0]), float(p[1]))
                if not self.px:
                    self.px.append(x); self.py.append(y); self.ps.append(0.0)
                    continue
                d = math.hypot(x - self.px[-1], y - self.py[-1])
                if d < 0.01:
                    continue
                self.px.append(x); self.py.append(y); self.ps.append(self.ps[-1] + d)
                self.iseg.append(k)
            doorgang = doorgangen.get(sg.get("doorgang")) or {}
            self.segmenten.append({
                "nr": k, "type": sg.get("type", ""), "label": sg.get("label", f"segment {k}"),
                "omlaag": sg.get("werktuig") == "omlaag",
                "kmh": float(sg["snelheid_kmh"]),
                "s0": s0, "s1": self.ps[-1],
                "bevestigen": bool(sg.get("bevestigen")),
                "doorgang": sg.get("doorgang"),
                "breedte_m": doorgang.get("breedte_m"),
                "veld": sg.get("veld"),
            })
        if len(self.px) < 2:
            raise ValueError("het pad van de missie heeft geen lengte")
        self.lengte = self.ps[-1]

    def punt(self, s):
        """(x, y) op booglengte s; voorbij het eind recht door in de laatste richting."""
        n = len(self.ps)
        if s <= 0.0:
            return self.px[0], self.py[0]
        if s >= self.lengte:
            dx, dy = self.px[-1] - self.px[-2], self.py[-1] - self.py[-2]
            l = math.hypot(dx, dy)
            extra = s - self.lengte
            return self.px[-1] + dx / l * extra, self.py[-1] + dy / l * extra
        lo, hi = 0, n - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.ps[mid] <= s:
                lo = mid
            else:
                hi = mid
        t = (s - self.ps[lo]) / (self.ps[hi] - self.ps[lo])
        return self.px[lo] + t * (self.px[hi] - self.px[lo]), self.py[lo] + t * (self.py[hi] - self.py[lo])

    def index(self, s):
        """Nummer van het stuk [i, i+1] waar s op ligt."""
        lo, hi = 0, len(self.ps) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.ps[mid] <= s:
                lo = mid
            else:
                hi = mid
        return lo

    def projecteer(self, x, y, s_vorige, terug_m, vooruit_m):
        """
        Dichtstbijzijnde punt op het pad tussen s_vorige - terug_m en
        s_vorige + vooruit_m. Geeft (s, afwijking naar rechts in m, koers van
        het stuk in kompasgraden, nummer van het stuk).
        """
        i = self.index(max(0.0, s_vorige - terug_m))
        eind = min(self.lengte, s_vorige + vooruit_m)
        best = None
        while i < len(self.ps) - 1:
            x1, y1 = self.px[i], self.py[i]
            dx, dy = self.px[i + 1] - x1, self.py[i + 1] - y1
            l2 = dx * dx + dy * dy
            t = ((x - x1) * dx + (y - y1) * dy) / l2
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if best is None or d < best[0] - 1e-9:
                best = (d, i, t)
            if self.ps[i + 1] >= eind:
                break
            i += 1
        d, i, t = best
        dx, dy = self.px[i + 1] - self.px[i], self.py[i + 1] - self.py[i]
        l = math.hypot(dx, dy)
        rechts = ((x - self.px[i]) * dy - (y - self.py[i]) * dx) / l
        return self.ps[i] + t * l, rechts, math.degrees(math.atan2(dx, dy)) % 360.0, i

    def segment_op(self, s, vanaf=0):
        k = vanaf
        while k < len(self.segmenten) - 1 and s >= self.segmenten[k]["s1"] - 1e-6:
            k += 1
        return k


class MissieVolger:
    def __init__(self, gps_system, vehicle_controller, config, geofence=None):
        self.logger = logging.getLogger(__name__)
        self.gps = gps_system
        self.vehicle = vehicle_controller
        self.geofence = geofence
        self.drive_logger = DriveLogger() if DriveLogger else None

        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)
        self.half_robot = config.get("vehicle", {}).get("track_width_m", 1.0) / 2.0 + 0.15
        self.max_angle = getattr(vehicle_controller, "max_center_angle",
                                 config.get("steering", {}).get("max_angle_degrees", 45.0))
        nav = config.get("navigation", {})
        c = config.get("missie", {})
        self.lookahead_m = float(c.get("lookahead_m", 1.5))
        self.lookahead_baan_m = float(nav.get("lookahead_distance_m", 2.0))
        self.max_afwijking_m = float(c.get("max_afwijking_m", 1.5))
        self.aanloop_max_m = float(c.get("aanloop_max_m", 30.0))
        self.aanloop_kmh = float(c.get("aanloop_snelheid_kmh", 2.0))
        self.oppak_m = float(c.get("oppak_afstand_m", 0.5))
        self.hervat_terug_m = float(c.get("hervat_terug_m", 2.0))
        self.eind_marge_m = float(c.get("eind_marge_m", 0.3))
        self.min_baan_m = float(c.get("min_baan_m", 4.0))
        self.baan_uitloop_m = float(c.get("baan_uitloop_m", 0.4))
        self.rem_mps2 = 0.8 * float(config.get("vehicle", {}).get("decel_mps2", 0.8))
        self.max_kmh = None                  # bovengrens uit de webinterface (None = snelheden van de missie)

        self.bewaker = GnssBewaker(config)
        self.regelaar = LijnRegelaar(config, self.wheelbase, self.max_angle)

        self.naam = None
        self.missie = None
        self.pad = None
        self.missie_nr = 0                   # telt per start, zodat de kaart een nieuw spoor herkent
        self.s = 0.0
        self.segment = 0
        self.afwijking = 0.0
        self.opgepakt = False
        self.werktuig_omlaag = False
        self.vrijgegeven = set()             # segmentnummers waarvoor al vrijgave is gegeven
        self._spoor = []                     # [lat, lon, 1 = werktuig omlaag]
        self._spoor_lock = threading.Lock()

        self.is_active = False
        self.thread = None
        self.state = "IDLE"                  # IDLE | AANLOOP | RIJDEN | WACHT_OP_GNSS | WACHT_OP_VRIJGAVE | KLAAR | FOUT
        self.status_message = "Geen missie"

    # ------------------------------------------------------------------
    #  Laden, starten, stoppen
    # ------------------------------------------------------------------
    def laad(self, naam):
        """Missie uit data/missies/ klaarzetten. Gooit ValueError als dat niet kan."""
        if self.is_active:
            raise ValueError("er rijdt al een missie; stop die eerst")
        data = MissieOpslag.lees(naam)
        if data is None:
            raise ValueError(f"missie '{naam}' staat niet op de robot")
        controleer_missie(data)
        self.pad = Pad(data)
        self.missie = data
        self.naam = naam
        self.s, self.segment, self.afwijking = 0.0, 0, 0.0
        self.state, self.status_message = "IDLE", f"Missie '{naam}' geladen"
        return self.pad

    def voortgang_op_schijf(self, naam=None):
        """Bewaarde voortgang van deze missie (zelfde bestand, nog niet klaar), of None."""
        try:
            with open(VOORTGANG_FILE, "r", encoding="utf-8") as f:
                v = json.load(f)
        except Exception:
            return None
        naam = naam or self.naam
        if v.get("naam") != naam or v.get("klaar"):
            return None
        data = self.missie if naam == self.naam else MissieOpslag.lees(naam)
        if data is None or v.get("gemaakt") != data.get("gemaakt"):
            return None
        return v

    def _bewaar_voortgang(self, klaar=False):
        if self.pad is None:
            return
        try:
            tmp = VOORTGANG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"naam": self.naam, "gemaakt": self.missie.get("gemaakt"),
                           "s_m": round(self.s, 2), "totaal_m": round(self.pad.lengte, 2),
                           "segment": self.segment, "klaar": klaar,
                           "tijd": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
            os.replace(tmp, VOORTGANG_FILE)
        except Exception as e:
            self.logger.error(f"Voortgang niet bewaard: {e}")

    def start(self, naam, hervat=False, max_kmh=None):
        """Start (of hervat) een missie. Geeft None, of de reden waarom het niet kan."""
        if self.is_active:
            self.stop()
        try:
            self.laad(naam)
        except ValueError as e:
            self.state, self.status_message = "FOUT", str(e)
            return str(e)
        reden = onveilig(self.missie)
        if reden:
            self.state, self.status_message = "FOUT", reden
            return reden

        s_start = 0.0
        if hervat:
            v = self.voortgang_op_schijf()
            if v is None:
                return "geen voortgang van deze missie om te hervatten"
            s_start = max(0.0, min(float(v["s_m"]), self.pad.lengte) - self.hervat_terug_m)

        pos = self.gps.get_current_position()
        if pos.get("fix", 0) == 0 or (pos.get("lat", 0.0) == 0.0 and pos.get("lon", 0.0) == 0.0):
            return "geen GNSS-positie: de afstand tot het startpunt is onbekend"
        x, y = self.pad.frame.xy(pos["lat"], pos["lon"])
        sx, sy = self.pad.punt(s_start)
        afstand = math.hypot(x - sx, y - sy)
        if afstand > self.aanloop_max_m:
            reden = (f"de robot staat {afstand:.0f} m van het {'hervatpunt' if hervat else 'startpunt'} "
                     f"(max {self.aanloop_max_m:.0f} m): rij er eerst met de hand naartoe")
            self.state, self.status_message = "FOUT", reden
            return reden

        if self.geofence is not None:
            self.geofence.stop_overbrugging()
            try:
                self.geofence.zet_missie(self.missie.get("geofence"),
                                         (self.missie.get("robot") or {}).get("halve_breedte_m"))
            except ValueError as e:
                reden = f"geofence van de missie is ongeldig: {e}"
                self.state, self.status_message = "FOUT", reden
                return reden

        self.max_kmh = max_kmh
        self.s = s_start
        self.segment = self.pad.segment_op(s_start)
        self.opgepakt = False
        self.afwijking = 0.0
        self.werktuig_omlaag = False
        self.vrijgegeven = set()
        with self._spoor_lock:
            self._spoor = []
        self.missie_nr += 1
        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="Veldmissie")
        self.is_active = True
        self.state = "AANLOOP"
        self.status_message = f"Naar het {'hervatpunt' if hervat else 'startpunt'} ({afstand:.1f} m)"
        self.thread = threading.Thread(target=self._loop, daemon=True, name="missievolger")
        self.thread.start()
        self.logger.info(f"Veldmissie '{naam}' gestart op s = {s_start:.1f} m van {self.pad.lengte:.0f} m.")
        return None

    def stop(self):
        """Stopt de missie; de voortgang blijft bewaard om te hervatten."""
        was_actief = self.is_active
        self.is_active = False
        if self.thread and self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=1.0)
        self.vehicle.stop()
        if was_actief and self.state not in ("KLAAR", "FOUT"):
            self.state = "IDLE"
            self.status_message = f"Gestopt op {self.s:.0f} van {self.pad.lengte:.0f} m"

    def vrijgeven(self):
        """Vrijgave voor de doorgang waar de robot op wacht."""
        if self.state != "WACHT_OP_VRIJGAVE":
            return False
        self.vrijgegeven.add(self._wacht_segment)
        return True

    # ------------------------------------------------------------------
    #  Regellus
    # ------------------------------------------------------------------
    def _loop(self):
        try:
            self._run()
        except Exception as e:
            self.state = "FOUT"
            self.status_message = f"Fout in de missievolger: {e}"
            self.logger.exception(f"Onverwachte fout in de missievolger: {e}")
        finally:
            self.is_active = False
            self.werktuig_omlaag = False
            self.vehicle.stop()
            self._bewaar_voortgang(klaar=self.state == "KLAAR")
            if self.geofence is not None:
                self.geofence.zet_missie(None)
            if self.drive_logger:
                self.drive_logger.stop_log()

    def _snelheid(self, seg):
        """Snelheid nu: die van het segment, op tijd afgeremd voor wat er komt."""
        pad = self.pad
        v = seg["kmh"] / 3.6
        # Vooruitkijken: een langzamer segment of een stop voor een doorgang met vrijgave.
        k = seg["nr"] + 1
        while k < len(pad.segmenten):
            volgend = pad.segmenten[k]
            afstand = volgend["s0"] - self.s
            if afstand > 15.0:
                break
            doel = 0.0 if (volgend["bevestigen"] and k not in self.vrijgegeven) else volgend["kmh"] / 3.6
            v = min(v, math.sqrt(doel * doel + 2.0 * self.rem_mps2 * max(0.0, afstand)))
            k += 1
        # Naar stilstand aan het eind van het pad.
        v = min(v, math.sqrt(2.0 * self.rem_mps2 * max(0.05, pad.lengte - self.s)))
        kmh = v * 3.6
        if self.max_kmh is not None:
            kmh = min(kmh, self.max_kmh)
        return kmh

    def _run(self):
        pad = self.pad
        epoch = -1
        vorige = time.time()
        laatste_bewaard = time.time()
        self._wacht_segment = None
        while self.is_active:
            epoch = self.gps.wacht_op_epoch(epoch, timeout=0.1)
            nu = time.time()
            dt, vorige = nu - vorige, nu

            fout = self.vehicle.drive_fault
            if fout:
                self.state, self.status_message = "FOUT", f"Gestopt - aandrijving: {fout}"
                self.logger.error(f"Veldmissie gestopt, aandrijving: {fout}")
                break
            grens = self.vehicle.blokkade
            if grens:
                self.state, self.status_message = "FOUT", f"Gestopt - {grens}"
                self.logger.error(f"Veldmissie gestopt, {grens}")
                break

            pos = self.gps.get_current_position()
            x, y = pad.frame.xy(pos.get("lat", 0.0), pos.get("lon", 0.0))
            heading = pos.get("heading", 0.0)

            # 1. Waar zijn we op het pad?
            if self.opgepakt:
                s_nu, afwijking, koers, i = pad.projecteer(x, y, self.s, 1.0, 6.0)
                self.s = max(self.s, s_nu)
            else:
                s_nu, afwijking, koers, i = pad.projecteer(x, y, self.s, 0.0, 6.0)
                if abs(afwijking) < self.oppak_m and math.hypot(x - pad.punt(s_nu)[0], y - pad.punt(s_nu)[1]) < self.oppak_m:
                    self.opgepakt = True
                    self.s = max(self.s, s_nu)
            self.afwijking = afwijking
            self.segment = pad.segment_op(self.s, self.segment)
            seg = pad.segmenten[self.segment]

            # 2. Klaar?
            if self.opgepakt and self.s >= pad.lengte - self.eind_marge_m:
                self.state = "KLAAR"
                self.status_message = f"Missie klaar ({pad.lengte:.0f} m)"
                self.logger.info("Veldmissie voltooid.")
                break

            # 3. Te ver van het pad: iets klopt er niet (glijden, verkeerde missie).
            grens_m = self.max_afwijking_m
            if seg["type"] == "doorgang" and seg["breedte_m"]:
                grens_m = min(grens_m, max(0.2, float(seg["breedte_m"]) / 2.0 - self.half_robot))
            if self.opgepakt and abs(afwijking) > grens_m:
                self.state = "FOUT"
                self.status_message = (f"Gestopt - {abs(afwijking):.2f} m naast het pad in '{seg['label']}' "
                                       f"(max {grens_m:.2f} m)")
                self.logger.error(self.status_message)
                break

            # 4. Wachten op vrijgave aan het begin van een doorgang (oversteek).
            wacht = None
            for k in (self.segment, self.segment + 1):
                if k < len(pad.segmenten):
                    sg = pad.segmenten[k]
                    if sg["bevestigen"] and k not in self.vrijgegeven and -0.3 <= sg["s0"] - self.s <= 0.4:
                        wacht = k
            if wacht is not None and self.opgepakt:
                self._wacht_segment = wacht
                self.state = "WACHT_OP_VRIJGAVE"
                self.status_message = f"Wacht op vrijgave: {pad.segmenten[wacht]['label']}"
                self.werktuig_omlaag = False
                self.vehicle.drive(0.0, 0.0)
                continue

            # 5. Snelheid: segment, afremmen, en wat de GNSS toelaat.
            gevraagd = self._snelheid(seg) if self.opgepakt else min(self.aanloop_kmh, seg["kmh"])
            snelheid, melding = self.bewaker.beoordeel(pos, gevraagd)
            if snelheid <= 0.0:
                if self.state != "WACHT_OP_GNSS":
                    self.logger.warning(f"Veldmissie wacht: {melding}")
                self.state, self.status_message = "WACHT_OP_GNSS", melding
                self.werktuig_omlaag = False
                self.vehicle.drive(0.0, 0.0)
                continue

            # 6. Sturen.
            v_kmh = pos.get("speed_kmh", 0.0)
            rest_baan = seg["s1"] - self.s
            recht = (self.opgepakt and seg["type"] == "baan" and seg["s1"] - seg["s0"] >= self.min_baan_m
                     and rest_baan > self.baan_uitloop_m and pad.iseg[i + 1] == seg["nr"])
            if recht:
                stuur = self.regelaar.stuur(
                    heading, koers, afwijking, v_kmh, pos.get("draaisnelheid_dps", 0.0), self.lookahead_baan_m,
                    lijn_id=(self.missie_nr, seg["nr"]), dt=dt, leer_id=(self.missie_nr, round(koers / 5.0)))
                regelaar = self.regelaar.soort
            else:
                tx, ty = pad.punt(self.s + self.lookahead_m)
                afstand = math.hypot(tx - x, ty - y)
                peil = math.degrees(math.atan2(tx - x, ty - y)) % 360.0
                stuur = self.regelaar.pure_pursuit(peil, heading, afstand)
                koers = peil
                regelaar = "pad_pursuit"

            self.state = "RIJDEN" if self.opgepakt else "AANLOOP"
            self.werktuig_omlaag = self.opgepakt and seg["omlaag"]
            self.vehicle.drive(snelheid, stuur, timeout_s=self.vehicle.nav_timeout_s)
            if self.opgepakt:
                self.status_message = (
                    f"{seg['label']} ({self.segment + 1}/{len(pad.segmenten)}): {self.s:.0f} van {pad.lengte:.0f} m, "
                    f"afwijking {afwijking:+.2f} m" + (f" | {melding}" if melding else ""))
            else:
                self.status_message = f"Naar het pad: nog {math.hypot(x - pad.punt(self.s)[0], y - pad.punt(self.s)[1]):.1f} m"

            # 7. Spoor, voortgang, log.
            with self._spoor_lock:
                if not self._spoor or math.hypot(x - self._spoor_xy[0], y - self._spoor_xy[1]) >= 0.25:
                    self._spoor.append([round(pos["lat"], 8), round(pos["lon"], 8), 1 if self.werktuig_omlaag else 0])
                    self._spoor_xy = (x, y)
            if nu - laatste_bewaard > 5.0:
                laatste_bewaard = nu
                self._bewaar_voortgang()
            if self.drive_logger:
                try:
                    self.drive_logger.log_regel(
                        wp_idx=self.segment, modus=f"missie_{seg['type']}", lat=pos["lat"], lon=pos["lon"],
                        fix=pos.get("fix", 0), hdop=pos.get("hdop", 99.0), heading_echt=heading,
                        heading_doel=koers, heading_fout=norm180(koers - heading), stuurhoek=stuur,
                        doel_kmh=snelheid, echt_kmh=v_kmh, dist_wp=pad.lengte - self.s,
                        lookahead=self.lookahead_m, dt=dt, motor=self.vehicle.log_snapshot(),
                        xte=afwijking, regelaar=regelaar, gnss=pos)
                except Exception as e:
                    self.logger.error(f"Fout bij loggen: {e}")

    # ------------------------------------------------------------------
    #  Voor de webinterface
    # ------------------------------------------------------------------
    def spoor_vanaf(self, vanaf, max_punten=5000):
        with self._spoor_lock:
            vanaf = max(0, min(vanaf, len(self._spoor)))
            return vanaf, self._spoor[vanaf:vanaf + max_punten]

    def status(self):
        pad = self.pad
        uit = {
            "actief": self.is_active, "state": self.state, "bericht": self.status_message,
            "naam": self.naam, "missie_nr": self.missie_nr,
            "werktuig_omlaag": self.werktuig_omlaag, "max_kmh": self.max_kmh,
            "lookahead_m": self.lookahead_m,
        }
        if pad is not None:
            seg = pad.segmenten[min(self.segment, len(pad.segmenten) - 1)]
            rest_s = 0.0
            for sg in pad.segmenten[seg["nr"]:]:
                kmh = sg["kmh"] if self.max_kmh is None else min(sg["kmh"], self.max_kmh)
                rest_s += max(0.0, sg["s1"] - max(self.s, sg["s0"])) / (kmh / 3.6)
            uit.update({
                "s_m": round(self.s, 1), "totaal_m": round(pad.lengte, 1),
                "procent": round(100.0 * self.s / pad.lengte, 1),
                "segment": seg["nr"], "segmenten": len(pad.segmenten),
                "segment_label": seg["label"], "segment_type": seg["type"],
                "segment_kmh": seg["kmh"],
                "afwijking_m": round(self.afwijking, 3), "opgepakt": self.opgepakt,
                "resterend_min": round(rest_s / 60.0, 1),
            })
        return uit
