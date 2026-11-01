"""
Terreinlog: per gereden stukje (standaard elke 0.25 m) de hoogte van de grond,
de helling in de rijrichting (pitch) en de ruwheid, voor de veldkaarten van
Single_script_code/terrein_kaart.py.

Er wordt altijd gelogd zodra de robot rijdt, ook bij handmatig rijden: de
kaart wordt beter naarmate er meer over het veld gereden is. Eén bestand per
dag in data/terrein/, aangevuld als de app opnieuw start.

Alleen met RTK fixed: met float of zonder RTK zit de hoogte er decimeters
naast, en dat zou de hoogtekaart bederven.
"""
import csv
import math
import os
import time
from datetime import datetime

KOLOMMEN = ["tijd", "lat", "lon", "hoogte_grond_m", "hoogte_antenne_m", "pitch_deg",
            "ruwheid_deg", "heading", "kmh", "fix", "baseline_m", "hoogteverschil_m"]


class TerreinLogger:
    def __init__(self, stap_m=0.25, map_pad=os.path.join("data", "terrein")):
        self.stap_m = max(0.05, stap_m)
        self.map_pad = map_pad
        self._bestand = None
        self._schrijver = None
        self._dag = None
        self._vorige = None          # (lat, lon) van het laatst gelogde punt
        self._fout_gemeld = False

    def voeg_toe(self, pos):
        if not pos or pos.get("fix") != 4 or not pos.get("heading_geldig"):
            return
        lat, lon = pos["lat"], pos["lon"]
        if self._vorige is not None and self._afstand(self._vorige, (lat, lon)) < self.stap_m:
            return
        try:
            self._open()
            self._schrijver.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                f"{lat:.9f}", f"{lon:.9f}",
                pos.get("hoogte_grond_m"), pos.get("alt_m"),
                pos.get("pitch_deg"), pos.get("ruwheid_deg"),
                round(pos.get("heading", 0.0), 2), round(pos.get("speed_kmh", 0.0), 2),
                pos.get("fix"), pos.get("baseline_m"), pos.get("antenne_hoogteverschil_m"),
            ])
            self._bestand.flush()
            self._vorige = (lat, lon)
        except Exception as e:
            if not self._fout_gemeld:
                print(f"[TERREIN] Kan niet loggen: {e}")
                self._fout_gemeld = True

    def _open(self):
        dag = time.strftime("%Y%m%d")
        if self._dag == dag and self._bestand:
            return
        if self._bestand:
            self._bestand.close()
        os.makedirs(self.map_pad, exist_ok=True)
        pad = os.path.join(self.map_pad, f"terrein_{dag}.csv")
        nieuw = not os.path.exists(pad)
        self._bestand = open(pad, "a", newline="", encoding="utf-8")
        self._schrijver = csv.writer(self._bestand)
        if nieuw:
            self._schrijver.writerow(KOLOMMEN)
        self._dag = dag

    @staticmethod
    def _afstand(a, b):
        noord = math.radians(b[0] - a[0]) * 6371000.0
        oost = math.radians(b[1] - a[1]) * 6371000.0 * math.cos(math.radians(a[0]))
        return math.hypot(noord, oost)

    def close(self):
        if self._bestand:
            self._bestand.close()
            self._bestand = None
