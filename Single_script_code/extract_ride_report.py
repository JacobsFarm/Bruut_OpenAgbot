"""
Alles uit een ritlog in een keer: rapport (PDF en HTML), kaarten en grafieken.

Vervangt Extract_route_data.py, Extract_route_maps.py, extract_drive_analysis.py
en extract_map_terrain.py. Leest data/logs/rit_*.csv en maakt per rit een map
data/logs/<naam>/ met:
  <naam>_rapport.pdf      het complete rapport, om te printen of door te sturen
  <naam>_rapport.html     hetzelfde rapport plus de interactieve kaart op de
                          luchtfoto (route, hoogte, helling, ruwheid aan/uit te klikken)
  <naam>_rapport.txt      het rapport als tekst, om in een chat te plakken voor advies
  <naam>_kaart.jpg        gereden route op de luchtfoto, banen gekleurd naar de afwijking
  <naam>_terrein.jpg      hoogte met hoogtelijnen, helling en ruwheid
  <naam>_aandrijving.jpg  snelheid, trekkracht, accu, vermogen, temperaturen, verbruik
  <naam>_verloop.jpg      afwijking van de lijn, snelheid en stuurhoek over de rit

De onderdelen:
  telemetrie()   lijnvolging per baan en per kopakkerbocht, koers, snelheid,
                 stuurhoek, GPS; alles per modus gescheiden (zie hieronder)
  aandrijving()  trekkracht (berekend uit de motorstroom), vermogen, verbruik,
                 interne weerstand van de accu
  terrein()      hoogte, helling en ruwheid uit de RTK-hoogte of de pitch
Heeft de log de kolommen voor een onderdeel niet (oude rit), dan wordt dat
onderdeel overgeslagen en staat dat bij de aandachtspunten.

Gebruik (vanuit de hoofdmap van het project):
    python Single_script_code/extract_ride_report.py                 # nieuwste rit
    python Single_script_code/extract_ride_report.py data/logs/rit_AB_Missie_20261102_171014.csv
    python Single_script_code/extract_ride_report.py --alle          # alle ritten zonder rapport
    python Single_script_code/extract_ride_report.py --alle --opnieuw
    python Single_script_code/extract_ride_report.py --lambda 0.064 --kast-rendement 0.85
    python Single_script_code/extract_ride_report.py --geen-luchtfoto

Nodig: matplotlib, numpy, pandas, scipy, pillow, requests, folium en reportlab
(zitten allemaal in Anaconda).
"""
import argparse
import base64
import bisect
import csv
import glob
import html
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

# Kolommen zoals de logger (app/services/logger.py) ze wegschrijft:
#   Tijdstip, Modus, WP_Doel, Lat, Lon, Fix, HDOP,
#   Heading_Echt, Heading_Doel, Heading_Fout,
#   Stuurhoek, Doel_kmh, Echt_kmh,
#   Afstand_tot_WP_m, Lookahead_m, Loop_Tijd_s,
#   plus de aandrijfkolommen uit app/hardware/motor_logic.py (LOG_COLUMNS).
#   Ritten van voor de VESC's hebben DAC_Links en DAC_Rechts in plaats daarvan.
#
# Let op, de betekenis van twee kolommen hangt af van de modus:
#
#   Heading_Fout      TRACKING     -> cross-track error in METERS
#                     TURNING      -> resterende koersdraai in GRADEN
#                     pure_pursuit -> koersfout in GRADEN
#   Afstand_tot_WP_m  TRACKING     -> resterende meters op deze baan
#                     TURNING      -> afstand tot het kopakkerpad
#                     pure_pursuit -> afstand tot het waypoint
#
# Daarom wordt in dit rapport ALLES per modus gescheiden. Gooi je TRACKING en
# TURNING op een hoop, dan meet je vooral hoeveel bochten er in de rit zaten:
# tijdens een 180-graden kopakkerbocht is een grote koersfout immers normaal.

AB_MODES = ("TRACKING", "TURNING")
WP_MODES = ("pure_pursuit",)

# Drempels
XTE_INSTABILITY_M = 0.20        # cross-track error die je "onrustig" noemt
XTE_SETTLED_M = 0.10            # hieronder heet de baan opgepakt...
SETTLE_S = 2.0                  # ...als hij er zo lang onder blijft
HEADING_INSTABILITY_DEG = 10.0
STUTTER_S = 0.15
STRAIGHT_STEER_DEG = 1.0        # |stuurhoek| hieronder = rechtuit (scheeftrek-test)

G = 9.81
SPEC_TREKKRACHT_N = 50 * G      # setup/information/Specs hardware/specs_hub_motor.json: 50 kgf per motor
NOMINAAL_V_PER_CEL = 3.6
KLEUR_L, KLEUR_R = "#1f77b4", "#d62728"

R_AARDE = 6371000.0
TEGEL_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
STRAAT_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
TEGEL_CACHE = os.path.join(PROJECT_ROOT, "data", "kaarttegels")
LUCHTFOTO = True                # --geen-luchtfoto zet hem uit

MAANDEN = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december")


class Overgeslagen(Exception):
    """Onderdeel past niet bij deze log (bv. een oude rit zonder VESC-kolommen)."""


# ==========================================
# HULPFUNCTIES
# ==========================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """Afstand in meters tussen twee GPS-coordinaten."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R_AARDE * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def angle_difference(h1, h2):
    """Kortste verschil tussen twee koersen (-180 .. +180)."""
    return (h2 - h1 + 180) % 360 - 180


def percentile(values, p):
    """De p-de percentiel van een (ongesorteerde) lijst."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) - 1) * p / 100
    low = int(idx)
    high = min(low + 1, len(s) - 1)
    return s[low] + (s[high] - s[low]) * (idx - low)


def kwantiel(v, q):
    v = sorted(x for x in v if x is not None)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def avg(values, default=0.0):
    return (sum(values) / len(values)) if values else default


def optional_float(raw, key):
    """Kolom als float, of None als hij in deze log ontbreekt of leeg is."""
    try:
        return float(raw[key])
    except (KeyError, ValueError, TypeError):
        return None


def getal(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def parse_time(value):
    """Parset 'HH:MM:SS.mmm' (of zonder ms) naar een datetime; anders None."""
    for fmt_ in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt_)
        except (ValueError, TypeError):
            continue
    return None


def fmt(x, n=1):
    """Getal met spatie als duizendtalscheiding; '-' als er niets is."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    return f"{x:,.{n}f}".replace(",", " ")


def xy(lat, lon, lat0, lon0):
    """WGS84 -> meters oost/noord ten opzichte van (lat0, lon0)."""
    return (math.radians(lon - lon0) * R_AARDE * math.cos(math.radians(lat0)), math.radians(lat - lat0) * R_AARDE)


def _meters_naar_latlon(xm, ym, lat0, lon0):
    return (lat0 + math.degrees(ym / R_AARDE), lon0 + math.degrees(xm / (R_AARDE * math.cos(math.radians(lat0)))))


def bewaar(fig, pad, dpi):
    """Figuur als JPG; Windows geeft soms even Errno 22 op een bestand dat net vrijkomt."""
    for poging in range(4):
        try:
            fig.savefig(pad, dpi=dpi, bbox_inches="tight", pad_inches=0.15, pil_kwargs={"quality": 90})
            break
        except OSError:
            if poging == 3:
                raise
            time.sleep(1.0)
    plt.close(fig)
    return pad


def laad_config():
    """
    Voertuig, sturing, navigatie, VESC en accu uit data/config.json (anders config.example.json).

    Belangrijk: max_angle_degrees is de limiet per WIEL. De VehicleController
    klemt de gevraagde stuurhoek echter op de MIDDENHOEK van de vooras, en die
    ligt lager omdat het binnenwiel bij Ackermann scherper staat. Meet je de
    verzadiging tegen de wiellimiet, dan lijkt het alsof de robot nooit aan zijn
    eind zit terwijl hij in werkelijkheid volop tegen de aanslag stuurt.
    """
    cfg, bron = {}, "standaardwaarden"
    for naam in ("config.json", "config.example.json"):
        pad = os.path.join(PROJECT_ROOT, "data", naam)
        if os.path.exists(pad):
            try:
                with open(pad, encoding="utf-8") as f:
                    cfg = json.load(f)
                bron = naam
            except (OSError, ValueError):
                cfg = {}
            break
    stuur, voertuig, nav = cfg.get("steering", {}), cfg.get("vehicle", {}), cfg.get("navigation", {})
    vesc, accu = cfg.get("vesc", {}), cfg.get("battery", {})
    c = {
        "source": bron,
        "max_angle": stuur.get("max_angle_degrees", 50.0),
        "wheelbase": voertuig.get("wheelbase_m", 1.2),
        "track_width": voertuig.get("track_width_m", 1.0),
        "nav_lookahead": nav.get("lookahead_distance_m"),
        "turn_timeout": nav.get("turn_timeout_s", 90.0),
        "poolparen": float(vesc.get("pole_pairs", 10)),
        "overbrenging": float(vesc.get("gear_ratio", 5.0)),
        "omtrek_m": float(vesc.get("wheel_circumference_m", 1.277)),
        "max_erpm": float(vesc.get("max_erpm", 3700)),
        "cellen": int(accu.get("cells", 14)),
        "capaciteit_ah": float(accu.get("capacity_ah", 5.0)),
        "weerstand_config": float(accu.get("internal_resistance_ohm", 0.2)),
    }
    tangens = math.tan(math.radians(c["max_angle"]))
    if tangens > 1e-6:
        radius = c["wheelbase"] / tangens + c["track_width"] / 2.0
        c["max_center_angle"] = math.degrees(math.atan(c["wheelbase"] / radius))
    else:
        c["max_center_angle"] = c["max_angle"]
    return c


def lees_log(pad):
    """Alle regels van de ritlog als dicts; de kop- en afsluitregels (EINDE RIT) vallen eruit."""
    with open(pad, encoding="utf-8", errors="ignore", newline="") as f:
        return [{k: v for k, v in r.items() if k is not None} for r in csv.DictReader(f)
                if (r.get("Modus") or "").strip() not in ("", "EINDE RIT")]


# ==========================================
# TELEMETRIE: lijnvolging, koers, snelheid, sturing, GPS
# ==========================================

def read_rows(raw_rows):
    """De regels als getallen; regels met een kapot getal vallen weg."""
    rows = []
    for raw in raw_rows:
        try:
            rows.append({
                "t": parse_time(raw.get("Tijdstip", "")),
                "modus": raw["Modus"].strip(),
                "idx": int(float(raw["WP_Doel"])),
                "lat": float(raw["Lat"]),
                "lon": float(raw["Lon"]),
                "fix": int(float(raw["Fix"])),
                "hdop": float(raw["HDOP"]),
                "h_echt": float(raw["Heading_Echt"]),
                "h_doel": float(raw["Heading_Doel"]),
                "h_fout": float(raw["Heading_Fout"]),
                "stuur": float(raw["Stuurhoek"]),
                "doel_kmh": float(raw["Doel_kmh"]),
                "echt_kmh": float(raw["Echt_kmh"]),
                # Oude ritten: DAC-kolommen; nieuwe: VESC-kolommen.
                "dac_l": optional_float(raw, "DAC_Links"),
                "dac_r": optional_float(raw, "DAC_Rechts"),
                "erpm_l": optional_float(raw, "ERPM_Doel_L"),
                "erpm_r": optional_float(raw, "ERPM_Doel_R"),
                "stroom_l": optional_float(raw, "Motorstroom_L_A"),
                "stroom_r": optional_float(raw, "Motorstroom_R_A"),
                "wiel_kmh_l": optional_float(raw, "Wiel_kmh_L"),
                "wiel_kmh_r": optional_float(raw, "Wiel_kmh_R"),
                "fet_l": optional_float(raw, "Temp_FET_L_C"),
                "fet_r": optional_float(raw, "Temp_FET_R_C"),
                "model_l": optional_float(raw, "Motortemp_model_L_C"),
                "model_r": optional_float(raw, "Motortemp_model_R_C"),
                "odo_l": optional_float(raw, "Afstand_L_m"),
                "odo_r": optional_float(raw, "Afstand_R_m"),
                "accu_v": optional_float(raw, "Accu_V"),
                "accu_w": optional_float(raw, "Accu_W"),
                "accu_pct": optional_float(raw, "Accu_pct"),
                "verbruikt_wh": optional_float(raw, "Verbruikt_Wh"),
                "terug_wh": optional_float(raw, "Teruggeleverd_Wh"),
                "afstand": float(raw["Afstand_tot_WP_m"]),
                "lookahead": float(raw["Lookahead_m"]),
                "loop_t": float(raw["Loop_Tijd_s"]),
                # Nieuwere ritten: de echte lijnafwijking (m, met teken) staat in
                # Afwijking_m; Heading_Fout is dan bij stanley een koersfout in graden.
                "xte": optional_float(raw, "Afwijking_m"),
            })
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return rows


def segmenteer(rows):
    """
    Knipt de rit op in stukken: elke baan en elke kopakkerbocht apart. Een nieuw
    segment begint zodra de modus wisselt, of zodra het baannummer verandert.
    """
    segmenten = []
    for r in rows:
        if (not segmenten or r["modus"] != segmenten[-1]["modus"]
                or r["idx"] != segmenten[-1]["idx"]):
            segmenten.append({"modus": r["modus"], "idx": r["idx"], "rows": [r]})
        else:
            segmenten[-1]["rows"].append(r)
    return segmenten


def tijden_s(rows):
    """Seconden sinds de eerste regel: uit de tijdstempels (ook over middernacht), anders Loop_Tijd_s opgeteld."""
    if rows and all(r["t"] for r in rows):
        t0 = rows[0]["t"]
        return [((r["t"] - t0).total_seconds() + 86400) % 86400 for r in rows]
    uit, acc = [], 0.0
    for r in rows:
        acc += r["loop_t"]
        uit.append(acc)
    return uit


def duur_s(rows):
    """Duur van een reeks regels: liefst uit de tijdstempels, anders uit Loop_Tijd_s."""
    stempels = [r["t"] for r in rows if r["t"]]
    if len(stempels) >= 2:
        return (max(stempels) - min(stempels)).total_seconds()
    return sum(r["loop_t"] for r in rows)


def xte_waarde(r):
    """Lijnafwijking in meter: Afwijking_m (nieuwe ritten), anders Heading_Fout (oude ritten)."""
    return r["xte"] if r["xte"] is not None else r["h_fout"]


def gem_heading(rows):
    """Gemiddelde koers (graden) van een reeks regels, cirkelgemiddelde."""
    sx = sum(math.sin(math.radians(r["h_echt"])) for r in rows)
    cx = sum(math.cos(math.radians(r["h_echt"])) for r in rows)
    return math.degrees(math.atan2(sx, cx)) % 360


def analyseer_baan(seg):
    """
    Cijfers voor een enkele baan.

    'Oppakken' is de afwijking op de eerste regel: hoe scheef hij de baan
    binnenkomt. Daarna zoeken we het moment waarop hij de lijn te pakken heeft
    en houdt: SETTLE_S seconden lang allemaal binnen XTE_SETTLED_M. Kijk je
    alleen naar de eerste regel onder de drempel, dan telt een NULDOORGANG al
    als opgepakt terwijl hij op dat moment vol tegen de stuuraanslag dwars door
    de lijn schiet. Het venster gaat op de tijd, niet op het aantal regels: de
    log loopt op het ritme van de GNSS (25 Hz), oudere ritten op 10 Hz.

    'Uitslag' is de grootste afwijking tijdens dat oppakken: schiet hij door
    naar de andere kant van de lijn, dan zie je dat hier.
    """
    xte = [abs(xte_waarde(r)) for r in seg["rows"]]
    t = tijden_s(seg["rows"])

    settle_i = None
    for i in range(len(xte)):
        eind = bisect.bisect_left(t, t[i] + SETTLE_S, lo=i)
        venster = xte[i:max(eind, i + 1)]
        if all(v < XTE_SETTLED_M for v in venster):
            settle_i = i
            break

    na = xte[settle_i:] if settle_i is not None else []
    aanloop = xte[:settle_i] if settle_i else xte
    afstanden = [r["afstand"] for r in seg["rows"]]
    return {
        "baan": seg["idx"],
        "duur": duur_s(seg["rows"]),
        "lengte": max(afstanden) - min(afstanden) if afstanden else 0.0,
        "oppakken": xte[0] if xte else 0.0,
        "uitslag": max(aanloop) if aanloop else (xte[0] if xte else 0.0),
        "settle_s": (t[settle_i] - t[0]) if settle_i is not None else None,
        "gem": avg(na),
        "max": max(na) if na else 0.0,
        "xte_na": na,
        "xte_alles": xte,
        "signed_na": [xte_waarde(r) for r in seg["rows"][settle_i:]] if settle_i is not None else [],
        "heading": gem_heading(seg["rows"]),
    }


def analyseer_bocht(segmenten, i, timeout_s):
    """
    Cijfers voor de kopakkerbocht op positie i in de segmentenlijst.

    De koersfout is hier het verschil tussen de werkelijke koers en de koers
    naar het volgende punt op het BEREKENDE kopakkerpad - dus hoe goed hij zijn
    eigen bochtpad volgt, niet hoe ver hij nog moet draaien.

    'van' en 'naar' worden uit de buren in de segmentenlijst gehaald, niet uit
    een aparte banenlijst: een rit die met een bocht begint (robot stond al
    voorbij het eind van de eerste baan) zou anders alles een plek opschuiven.
    """
    seg = segmenten[i]
    fouten = [abs(angle_difference(r["h_doel"], r["h_echt"])) for r in seg["rows"]]
    d = duur_s(seg["rows"])

    van = next((segmenten[j]["idx"] for j in range(i - 1, -1, -1)
                if segmenten[j]["modus"] == "TRACKING"), None)
    naar = next((segmenten[j]["idx"] for j in range(i + 1, len(segmenten))
                 if segmenten[j]["modus"] == "TRACKING"), None)

    return {
        "van": van,
        "naar": naar,
        "duur": d,
        "gem": avg(fouten),
        "max": max(fouten) if fouten else 0.0,
        "timeout": d >= timeout_s - 2.0,
        # Gemiddelde afstand tot het bochtpad. Loopt dit ver op, dan begon de
        # bocht terwijl de robot niet op de lijn stond: het pad wordt namelijk
        # vanaf de lijn berekend, niet vanaf de robot.
        "afstand_pad": avg([r["afstand"] for r in seg["rows"]]),
    }


def telemetrie(raw_rows, cfg):
    """Het tekstrapport over lijnvolging, koers, snelheid, sturing, accu en GPS, plus de cijfers per baan en bocht."""
    rows = read_rows(raw_rows)
    if not rows:
        raise Overgeslagen("geen bruikbare regels in deze log")

    max_center = cfg["max_center_angle"]
    steer_sat_threshold = max(1.0, max_center - 0.1)

    modus_counts = {}
    for r in rows:
        modus_counts[r["modus"]] = modus_counts.get(r["modus"], 0) + 1

    is_ab = any(m in modus_counts for m in AB_MODES)
    is_wp = any(m in modus_counts for m in WP_MODES)
    if is_ab and not is_wp:
        log_type = "AB-lijn missie"
    elif is_wp and not is_ab:
        log_type = "Waypoint route (pure pursuit)"
    else:
        log_type = "Onbekend / gemengd"

    total_rows = len(rows)
    segmenten = segmenteer(rows)
    banen = [analyseer_baan(s) for s in segmenten if s["modus"] == "TRACKING"]
    bochten = [analyseer_bocht(segmenten, i, cfg["turn_timeout"])
               for i, s in enumerate(segmenten) if s["modus"] == "TURNING"]

    # Regels waarop de STUURKWALITEIT beoordeeld mag worden: het rechte werk.
    # Bij AB is dat TRACKING, bij de waypointroute alles.
    stuurwerk = [r for r in rows if r["modus"] != "TURNING"]

    # --- Afstand en tijd ---
    coords = [(r["lat"], r["lon"]) for r in rows if r["lat"] != 0.0 and r["lon"] != 0.0]
    total_distance_m = sum(
        haversine_distance(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        for i in range(1, len(coords))
    )
    total_time_sec = duur_s(rows)
    minutes = int(total_time_sec // 60)
    seconds = total_time_sec % 60

    # --- Fix / HDOP ---
    fix_counts = {}
    for r in rows:
        fix_counts[r["fix"]] = fix_counts.get(r["fix"], 0) + 1
    fixed_pct = (fix_counts.get(4, 0) / total_rows) * 100
    float_pct = (fix_counts.get(5, 0) / total_rows) * 100
    nofix_pct = (sum(c for fx, c in fix_counts.items() if fx < 2) / total_rows) * 100

    modes_str = ", ".join(f"{m}: {c} ({100 * c / total_rows:.1f}%)"
                          for m, c in sorted(modus_counts.items()))

    lines = []
    lines.append("[RIT OVERZICHT]")
    lines.append(f"- Type log          : {log_type}")
    lines.append(f"- Totaal regels     : {total_rows}")
    lines.append(f"- Rijtijd           : {minutes}m {seconds:.1f}s ({total_time_sec:.1f} s)")
    lines.append(f"- Afstand gereden   : {total_distance_m:.1f} m ({total_distance_m / 1000:.3f} km)")
    lines.append(f"- Modi              : {modes_str}")
    lines.append(f"- Lookahead (gem.)  : {avg([r['lookahead'] for r in rows]):.2f} m")
    if is_ab:
        volgorde = " -> ".join(str(b["baan"]) for b in banen)
        lines.append(f"- Banen gereden     : {volgorde}")
        lines.append(f"                      ({len(banen)} banen, {len(bochten)} kopakkerbochten)")
        werk_s = sum(b["duur"] for b in banen)
        bocht_s = sum(b["duur"] for b in bochten)
        if werk_s + bocht_s > 0:
            lines.append(f"- Tijdverdeling     : {100 * werk_s / (werk_s + bocht_s):.0f} % baan, "
                         f"{100 * bocht_s / (werk_s + bocht_s):.0f} % kopakker "
                         f"({werk_s:.0f} s / {bocht_s:.0f} s)")
    else:
        idxs = sorted({r["idx"] for r in rows})
        lines.append(f"- Waypoints         : {idxs} (max {max(idxs)})")
    lines.append("")

    # ---------- AB: per baan en per bocht ----------
    if is_ab and banen:
        lines.append("[PER BAAN]  (cross-track error tijdens het volgen van de lijn)")
        lines.append("  nr  baan    duur   lengte   oppakken   uitslag   op lijn na"
                     "    daarna gem/max")
        for i, b in enumerate(banen, 1):
            settle = f"{b['settle_s']:.1f} s" if b["settle_s"] is not None else "nooit"
            lines.append(
                f"  {i:2d}  {b['baan']:4d}  {b['duur']:6.1f}s  {b['lengte']:5.1f} m   "
                f"{b['oppakken']:6.2f} m  {b['uitslag']:6.2f} m   {settle:>8s}    "
                f"{b['gem']:.3f} / {b['max']:.3f} m"
            )
        slechtste = max(banen, key=lambda b: b["gem"])
        lines.append(f"- Slechtste baan    : baan {slechtste['baan']} "
                     f"(gem {slechtste['gem']:.3f} m, max {slechtste['max']:.3f} m)")

        scheef = [b for b in banen if b["oppakken"] > 0.5]
        if scheef:
            lines.append(f"- Scheef opgepakt   : {len(scheef)}x meer dan 0.50 m naast de lijn "
                         f"(baan {', '.join(str(b['baan']) for b in scheef)})")
            lines.append("  Meestal is dit de START van de missie: stond de robot niet op de")
            lines.append("  AB-lijn, dan telt het hele aanrijden mee als cross-track error.")

        # Doorschieten: hij zat verder van de lijn af TIJDENS het oppakken dan
        # toen hij begon. Dat is geen meetfout maar een te agressieve inslinger.
        door = [b for b in banen if b["uitslag"] > max(0.5, b["oppakken"] * 1.2)]
        if door:
            lines.append(f"- Doorgeschoten     : {len(door)}x verder van de lijn tijdens het "
                         f"oppakken dan bij binnenkomst")
            for b in door:
                lines.append(f"    baan {b['baan']}: binnen op {b['oppakken']:.2f} m, "
                             f"uitgeslagen tot {b['uitslag']:.2f} m")
            lines.append("  Pure pursuit zit dan vol tegen de stuuraanslag en blijft daar tot de")
            lines.append("  koers is omgeslagen - dwars door de lijn heen. Een grotere lookahead")
            lines.append("  dempt dit; het speelt vooral als hij ver naast de lijn start.")
        lines.append("")

    if is_ab and bochten:
        lines.append("[PER KOPAKKERBOCHT]  (afwijking van het berekende bochtpad)")
        lines.append("  nr  van -> naar    duur   koersfout gem/max   afstand tot pad")
        for i, t in enumerate(bochten, 1):
            van = "start" if t["van"] is None else str(t["van"])
            naar = "eind" if t["naar"] is None else str(t["naar"])
            vlag = "  << TIMEOUT" if t["timeout"] else ("  << naast de lijn begonnen"
                                                       if t["afstand_pad"] > 1.0 else "")
            lines.append(
                f"  {i:2d}  {van:>5s} -> {naar:<5s} {t['duur']:6.1f}s   "
                f"{t['gem']:5.1f} / {t['max']:5.1f} gr        {t['afstand_pad']:.2f} m{vlag}"
            )
        duren = [t["duur"] for t in bochten]
        lines.append(f"- Bochtduur         : gem {avg(duren):.1f}s, "
                     f"snelste {min(duren):.1f}s, traagste {max(duren):.1f}s")

        scheve_bochten = [t for t in bochten if t["afstand_pad"] > 1.0]
        if scheve_bochten:
            lines.append(f"- LET OP            : {len(scheve_bochten)}x begon de bocht meer dan "
                         f"1 m naast het berekende pad.")
            lines.append("  Het kopakkerpad wordt vanaf de LIJN berekend, niet vanaf de robot.")
            lines.append("  Stond hij er niet op toen de bocht begon, dan moet hij zich er eerst")
            lines.append("  naartoe worstelen - vandaar de lange, rommelige bocht.")
        if any(t["timeout"] for t in bochten):
            lines.append(f"- LET OP            : {sum(1 for t in bochten if t['timeout'])}x liep de "
                         f"bocht in de timeout van {cfg['turn_timeout']:.0f}s.")
            lines.append("  De robot heeft daar rondgedraaid tot de noodrem van de bochtlogica")
            lines.append("  hem op de volgende baan zette.")
        lines.append("")

    # ---------- Lijnvolging ----------
    if is_ab and banen:
        xte_na = [v for b in banen for v in b["xte_na"]]
        xte_alles = [v for b in banen for v in b["xte_alles"]]
        signed_na = [v for b in banen for v in b["signed_na"]]
        nieuw_formaat = any(r["xte"] is not None for r in rows)
        links = sum(1 for v in signed_na if v < 0)
        rechts = sum(1 for v in signed_na if v > 0)
        bias = ("RECHTS van de lijn" if rechts > links * 1.2 else
                "LINKS van de lijn" if links > rechts * 1.2 else
                "Geen duidelijke bias")
        # Afwijking_m heeft een vast teken ten opzichte van de AB-lijn, niet ten opzichte
        # van de rijrichting. Daarom per rijrichting kijken: zelfde teken in beide
        # richtingen = de lijn ligt ernaast, tegengesteld teken = vaste zijwaartse fout in de robot.
        richting_txt = None
        if nieuw_formaat:
            ref = banen[0]["heading"]
            per_richting = ([], [])
            for b in banen:
                per_richting[0 if abs(angle_difference(ref, b["heading"])) < 90 else 1].extend(b["signed_na"])
            delen = [f"richting {naam} ({gem:.0f}°) {avg(v):+.3f} m"
                     for naam, v, gem in (("A", per_richting[0], ref),
                                          ("B", per_richting[1], (ref + 180) % 360)) if v]
            richting_txt = " / ".join(delen)
        onrustig = sum(1 for v in xte_na if v > XTE_INSTABILITY_M)

        lines.append("[LIJNVOLGING (cross-track error)]")
        lines.append("  Dit is de kwaliteitsmaat: alleen de meters NADAT hij de baan heeft")
        lines.append(f"  opgepakt (binnen {XTE_SETTLED_M} m). Het aanrijden zit er niet in.")
        lines.append(f"- XTE gemiddeld     : {avg(xte_na):.3f} m")
        lines.append(f"- XTE maximum       : {max(xte_na) if xte_na else 0:.3f} m")
        lines.append(f"- XTE P90           : {percentile(xte_na, 90):.3f} m")
        lines.append(f"- XTE P95           : {percentile(xte_na, 95):.3f} m")
        if richting_txt:
            lines.append(f"- XTE gemiddeld/richt: {richting_txt}")
            lines.append("  Zelfde teken in beide richtingen: de lijn ligt ernaast. Tegengesteld teken: een")
            lines.append("  vaste zijwaartse fout in de robot (antenne-offset rechts, koersoffset).")
        else:
            lines.append(f"- XTE bias          : {bias}  (links {links}x / rechts {rechts}x)")
        lines.append(f"- Instabiliteit     : {(onrustig / max(len(xte_na), 1)) * 100:.1f} % "
                     f"(XTE > {XTE_INSTABILITY_M} m)")
        lines.append(f"- Incl. aanrijden   : gem {avg(xte_alles):.3f} m, "
                     f"max {max(xte_alles) if xte_alles else 0:.3f} m "
                     f"(ter vergelijking, hier zit het oprijden naar de lijn in)")
        lines.append("  Tip: kleinere lookahead = strakker (maar meer slingeren), groter = soepeler.")
        lines.append("")
    elif is_wp:
        afstanden = [r["afstand"] for r in rows]
        lines.append("[DOELVOLGING (afstand tot waypoint)]")
        lines.append("  (Geen cross-track error: de waypoint-navigator mikt op het punt,")
        lines.append("   niet op een lijn ertussen.)")
        lines.append(f"- Afstand tot doel gem. : {avg(afstanden):.2f} m")
        lines.append(f"- Afstand tot doel max. : {max(afstanden):.2f} m")
        lines.append("")

    # ---------- Koers ----------
    koers = [angle_difference(r["h_doel"], r["h_echt"]) for r in stuurwerk]
    if koers:
        koers_bias = avg(koers)
        bias_txt = ("RECHTS (koerst te ver met de klok mee)" if koers_bias > 0.5 else
                    "LINKS (koerst te ver tegen de klok in)" if koers_bias < -0.5 else
                    "Geen duidelijke bias")
        groot = sum(1 for h in koers if abs(h) > HEADING_INSTABILITY_DEG)
        lines.append("[KOERS & ORIENTATIE]")
        if is_ab:
            lines.append("  Alleen tijdens het volgen van de baan. Kopakkerbochten tellen niet")
            lines.append("  mee: daar draait hij expres 180 graden, dus een grote momentane")
            lines.append("  koersfout is daar normaal en zegt niets over de stuurkwaliteit.")
        lines.append(f"- Koersfout gem.    : {avg([abs(h) for h in koers]):.1f}°")
        lines.append(f"- Koersfout max.    : {max(abs(h) for h in koers):.1f}°")
        lines.append(f"- Koers-bias        : {koers_bias:+.2f}° → {bias_txt}")
        lines.append(f"- Grote afwijking   : {(groot / len(koers)) * 100:.1f} % "
                     f"(> {HEADING_INSTABILITY_DEG}°)")
        lines.append("")

    # ---------- Snelheid ----------
    lines.append("[SNELHEID & EFFICIENTIE]")

    def snelheidsregel(naam, groep):
        if not groep:
            return
        doel = avg([r["doel_kmh"] for r in groep])
        echt = avg([r["echt_kmh"] for r in groep])
        pct = (echt / doel * 100) if doel > 0.01 else 0.0
        lines.append(f"- {naam:<17s} : doel {doel:.2f}, echt {echt:.2f} km/h  ({pct:.0f} % gehaald)")

    snelheidsregel("Hele rit", rows)
    if is_ab:
        snelheidsregel("Tijdens de baan", [r for r in rows if r["modus"] == "TRACKING"])
        snelheidsregel("In de bocht", [r for r in rows if r["modus"] == "TURNING"])
    stil = sum(1 for r in rows if r["doel_kmh"] > 0.1 and r["echt_kmh"] < 0.1)
    lines.append(f"- Snelheidsfout gem.: "
                 f"{avg([abs(r['doel_kmh'] - r['echt_kmh']) for r in rows]):.2f} km/h")
    lines.append(f"- Stilstand         : {(stil / total_rows) * 100:.1f} % (doel > 0 maar staat stil)")
    lines.append("")

    # ---------- Stuursysteem ----------
    stuur_abs = [abs(r["stuur"]) for r in rows]
    sat_totaal = sum(1 for v in stuur_abs if v >= steer_sat_threshold)
    lines.append("[STUURSYSTEEM]")
    lines.append(f"- Stuurhoek gem.    : {avg(stuur_abs):.1f}°")
    lines.append(f"- Stuurhoek max.    : {max(stuur_abs):.1f}°")
    lines.append(f"- Stuurlimiet       : {(sat_totaal / total_rows) * 100:.1f} % van de tijd "
                 f"(|hoek| >= {steer_sat_threshold:.1f}°)")
    lines.append(f"  De limiet is de MIDDENHOEK ({max_center:.1f}°), niet de wiellimiet "
                 f"({cfg['max_angle']:.1f}°):")
    lines.append("  de VehicleController klemt daarop, want het binnenwiel staat bij Ackermann")
    lines.append("  scherper dan het virtuele midden van de vooras.")
    if is_ab:
        for naam, modus in (("tijdens de baan", "TRACKING"), ("in de bocht", "TURNING")):
            groep = [abs(r["stuur"]) for r in rows if r["modus"] == modus]
            if groep:
                n = sum(1 for v in groep if v >= steer_sat_threshold)
                lines.append(f"  - {naam:<16s}: {100 * n / len(groep):.1f} % aan de limiet")
    # Aandrijving: oude ritten hebben DAC-kolommen, nieuwe de VESC-kolommen.
    vesc = [r for r in rows if None not in (r["erpm_l"], r["erpm_r"], r["stroom_l"], r["stroom_r"])]
    dac = [r for r in rows if None not in (r["dac_l"], r["dac_r"])]
    if vesc:
        # Bij de VESC's ligt het toerental per wiel vast; belasting en
        # scheeftrek lees je daarom af aan de motorstroom, niet aan het commando.
        lines.append(f"- eRPM-verschil gem.: {avg([abs(r['erpm_l'] - r['erpm_r']) for r in vesc]):.0f}  "
                     f"(differentieel)")
        lines.append(f"- Motorstroom gem.  : links {avg([r['stroom_l'] for r in vesc]):.1f} A, "
                     f"rechts {avg([r['stroom_r'] for r in vesc]):.1f} A")
    elif dac:
        lines.append(f"- DAC-verschil gem. : {avg([abs(r['dac_l'] - r['dac_r']) for r in dac]):.1f}  "
                     f"(stuurintensiteit)")
        lines.append(f"- DAC-belasting gem.: {avg([(r['dac_l'] + r['dac_r']) / 2 for r in dac]):.1f}  "
                     f"(motorbelasting)")

    # Scheeftrek-test: rijdt hij met de wielen recht ook echt recht, of trekt
    # een van de twee hubmotoren? Alleen zinvol als hij ook echt rijdt.
    def rechtuit(groep):
        return [r for r in groep if abs(r["stuur"]) < STRAIGHT_STEER_DEG and r["echt_kmh"] > 0.5]

    if len(rechtuit(vesc)) >= 20:
        recht = rechtuit(vesc)
        verschil = avg([r["stroom_l"] - r["stroom_r"] for r in recht])
        oordeel = "symmetrisch" if abs(verschil) < 1.0 else "SCHEEF - een kant werkt harder"
        lines.append(f"- Scheeftrek-test   : rechtuit (n={len(recht)}) motorstroom links-rechts "
                     f"{verschil:+.1f} A -> {oordeel}")
    elif len(rechtuit(dac)) >= 20:
        recht = rechtuit(dac)
        verschil = avg([r["dac_l"] - r["dac_r"] for r in recht])
        oordeel = "symmetrisch" if abs(verschil) < 15 else "SCHEEF - een kant trekt harder"
        lines.append(f"- Scheeftrek-test   : rechtuit (n={len(recht)}) links-rechts "
                     f"{verschil:+.1f} DAC -> {oordeel}")
    else:
        lines.append("- Scheeftrek-test   : te weinig rechtuit-samples "
                     f"(|stuurhoek| < {STRAIGHT_STEER_DEG}° en rijdend)")
    lines.append("")

    # ---------- Accu & wielen (alleen ritten met de VESC-kolommen) ----------
    accu = [r for r in rows if None not in (r["accu_v"], r["verbruikt_wh"], r["terug_wh"])]
    if len(accu) >= 2:
        eerste, laatste = accu[0], accu[-1]
        verbruikt = laatste["verbruikt_wh"] - eerste["verbruikt_wh"]
        terug = laatste["terug_wh"] - eerste["terug_wh"]
        lines.append("[ACCU & WIELEN]")
        lines.append(f"- Spanning          : {eerste['accu_v']:.1f} V -> {laatste['accu_v']:.1f} V "
                     f"(laagste {min(r['accu_v'] for r in accu):.1f} V)")
        if eerste["accu_pct"] is not None and laatste["accu_pct"] is not None:
            lines.append(f"- Lading (schatting): {eerste['accu_pct']:.0f} % -> {laatste['accu_pct']:.0f} %")
        lines.append(f"- Energie deze rit  : {verbruikt - terug:.1f} Wh netto "
                     f"({verbruikt:.1f} Wh verbruikt, {terug:.1f} Wh teruggeleverd)")
        vermogen = [r["accu_w"] for r in accu if r["accu_w"] is not None]
        if vermogen:
            lines.append(f"- Vermogen          : gem. {avg(vermogen):.0f} W, piek {max(vermogen):.0f} W")
        odo = [r for r in accu if r["odo_l"] is not None and r["odo_r"] is not None]
        if len(odo) >= 2:
            meters = ((odo[-1]["odo_l"] - odo[0]["odo_l"]) + (odo[-1]["odo_r"] - odo[0]["odo_r"])) / 2
            per_km = f", {(verbruikt - terug) / (meters / 1000):.0f} Wh/km" if meters > 10 else ""
            lines.append(f"- Afgelegd (wielen) : {meters:.0f} m{per_km}")
        # Wielsnelheid tegen GPS: een blijvend verschil is slip of een verkeerde wielomtrek.
        rijdend = [r for r in accu if None not in (r["wiel_kmh_l"], r["wiel_kmh_r"]) and r["echt_kmh"] > 0.5]
        if len(rijdend) >= 20:
            wiel = avg([(abs(r["wiel_kmh_l"]) + abs(r["wiel_kmh_r"])) / 2 for r in rijdend])
            gps = avg([r["echt_kmh"] for r in rijdend])
            lines.append(f"- Wielen vs GPS     : {wiel:.2f} vs {gps:.2f} km/h "
                         f"({100 * (wiel - gps) / wiel:+.1f} %: slip of wielomtrek)")
        temps = [r for r in accu if None not in (r["fet_l"], r["fet_r"], r["model_l"], r["model_r"])]
        if temps:
            lines.append(f"- Temperatuur max.  : FET {max(r['fet_l'] for r in temps):.0f} / "
                         f"{max(r['fet_r'] for r in temps):.0f} °C, motor (model) "
                         f"{max(r['model_l'] for r in temps):.0f} / {max(r['model_r'] for r in temps):.0f} °C")
        lines.append("")

    # ---------- GPS & systeem ----------
    loop_tijden = [r["loop_t"] for r in rows]
    stotter = sum(1 for v in loop_tijden if v > STUTTER_S)
    lines.append("[GPS & SYSTEEM]")
    lines.append(f"- RTK Fixed (4)     : {fixed_pct:.1f} %")
    lines.append(f"- RTK Float (5)     : {float_pct:.1f} %")
    lines.append(f"- Geen/zwakke fix   : {nofix_pct:.1f} % (fix < 2)")
    lines.append(f"- HDOP gemiddeld    : {avg([r['hdop'] for r in rows]):.2f}  (ideaal < 1.0)")
    lines.append(f"- Loop-tijd gem.    : {avg(loop_tijden):.3f} s")
    lines.append(f"- Loop-tijd max.    : {max(loop_tijden):.3f} s")
    lines.append(f"- CPU-hapering      : {(stotter / total_rows) * 100:.1f} % "
                 f"(loop > {int(STUTTER_S * 1000)} ms)")
    lines.append("")

    lines.append("[INSTELLINGEN (uit config)]")
    lines.append(f"- Bron config       : {cfg['source']}")
    lines.append(f"- Max stuurhoek wiel: {cfg['max_angle']}°")
    lines.append(f"- Max middenhoek    : {max_center:.1f}°  (de echte limiet)")
    lines.append(f"- Wielbasis         : {cfg['wheelbase']} m")
    lines.append(f"- Spoorbreedte      : {cfg['track_width']} m")
    lines.append(f"- Min. draaicirkel  : "
                 f"{cfg['wheelbase'] / math.tan(math.radians(max_center)):.2f} m")
    if cfg["nav_lookahead"] is not None:
        lines.append(f"- Lookahead (config): {cfg['nav_lookahead']} m")

    return {"tekst": "\n".join(lines), "rows": rows, "banen": banen, "bochten": bochten,
            "is_ab": is_ab, "is_wp": is_wp}


def parse_rapport(tekst):
    """Het tekstrapport terug in secties: titel, uitleg en regels (kv / sub / note)."""
    secties, huidig = [], None
    for ln in tekst.split("\n"):
        s = ln.rstrip()
        if not s.strip():
            continue
        m = re.match(r"^\[([^\]]+)\]\s*(?:\((.*)\))?\s*$", s)
        if m:
            huidig = {"titel": m.group(1), "sub": m.group(2) or "", "regels": []}
            secties.append(huidig)
            continue
        if huidig is None:
            continue
        if huidig["titel"] in ("PER BAAN", "PER KOPAKKERBOCHT") and (re.match(r"^\s+nr\s", s) or re.match(r"^\s+\d+\s{2}", s)):
            continue                                   # tabel: komt uit de data zelf
        m = re.match(r"^- ([^:]+?)\s*:\s(.*)$", s)
        if m:
            huidig["regels"].append(("kv", m.group(1).strip(), m.group(2).strip()))
            continue
        m = re.match(r"^\s+- ([^:]+?)\s*:\s(.*)$", s)
        if m:
            huidig["regels"].append(("sub", m.group(1).strip(), m.group(2).strip()))
            continue
        huidig["regels"].append(("note", s.strip(), ""))
    return secties


def verloop_grafiek(rows, max_center, uit_pad):
    """Afwijking van de lijn, snelheid en stuurhoek over de rit, met de kopakkerbochten grijs."""
    t = tijden_s(rows)
    nan = float("nan")
    xte = [xte_waarde(r) if r["modus"] == "TRACKING" else nan for r in rows]
    fig, ax = plt.subplots(3, 1, figsize=(13, 8), sharex=True, constrained_layout=True)
    ax[0].plot(t, xte, lw=0.7, color="#1f77b4")
    ax[0].axhline(0, color="k", lw=0.5)
    ax[0].set_ylim(-0.3, 0.3)
    ax[0].set_ylabel("afwijking van de lijn (m)")
    ax[0].set_title("Lijnvolging (alleen op de baan; as afgekapt op ±30 cm)")
    ax[1].plot(t, [r["doel_kmh"] for r in rows], lw=0.8, color="grey", label="doel")
    ax[1].plot(t, [r["echt_kmh"] for r in rows], lw=0.7, color="#d62728", label="echt (GNSS)")
    ax[1].set_ylabel("km/h")
    ax[1].legend(loc="upper right", ncol=2)
    ax[1].set_title("Snelheid")
    ax[2].plot(t, [r["stuur"] for r in rows], lw=0.7, color="#2ca02c")
    for v in (max_center, -max_center):
        ax[2].axhline(v, color="red", lw=0.7, ls=":")
    ax[2].set_ylabel("stuurhoek (graden)")
    ax[2].set_xlabel("tijd in de rit (s)")
    ax[2].set_title(f"Stuurhoek (rode lijn = limiet middenhoek {max_center:.1f}°)")
    i = 0
    while i < len(rows):
        if rows[i]["modus"] == "TURNING":
            j = i
            while j + 1 < len(rows) and rows[j + 1]["modus"] == "TURNING":
                j += 1
            for a in ax:
                a.axvspan(t[i], t[j], color="grey", alpha=0.18, lw=0)
            i = j + 1
        else:
            i += 1
    for a in ax:
        a.grid(alpha=0.3)
    return bewaar(fig, uit_pad, 110)


# ==========================================
# LUCHTFOTO (Esri World Imagery, bewaard in data/kaarttegels)
# ==========================================

def _tegel_xy(lat, lon, z):
    """WGS84 -> (fractionele) tegelcoordinaten in Web Mercator."""
    n = 2 ** z
    return (lon + 180.0) / 360.0 * n, (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n


def _tegel_latlon(tx, ty, z):
    n = 2 ** z
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n)))), tx / n * 360.0 - 180.0


def satelliet(lat_z, lat_n, lon_w, lon_o, max_zoom=19):
    """
    Luchtfoto van het gebied, als (beeld, (lat_z, lat_n, lon_w, lon_o)).
    De tegels worden bewaard in data/kaarttegels, zodat het daarna ook offline
    werkt. Geeft None als er geen internet is en de tegels niet in de cache staan.
    """
    if not LUCHTFOTO:
        return None
    from PIL import Image
    try:
        import requests
    except ImportError:
        requests = None

    z = max_zoom
    while True:
        x0, y0 = _tegel_xy(lat_n, lon_w, z)
        x1, y1 = _tegel_xy(lat_z, lon_o, z)
        if (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1) <= 80 or z <= 14:
            break
        z -= 1
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    os.makedirs(TEGEL_CACHE, exist_ok=True)
    mozaiek = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            pad = os.path.join(TEGEL_CACHE, f"{z}_{tx}_{ty}.jpg")
            if not os.path.exists(pad):
                if requests is None:
                    return None
                try:
                    r = requests.get(TEGEL_URL.format(z=z, x=tx, y=ty), timeout=10,
                                     headers={"User-Agent": "BruutAgbot-ritrapport/1.0"})
                    r.raise_for_status()
                    with open(pad, "wb") as f:
                        f.write(r.content)
                except Exception as e:
                    print(f"    geen luchtfoto ({e}); kaart zonder achtergrond")
                    return None
            mozaiek.paste(Image.open(pad).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    # Bijsnijden op het gebied (hele pixels) en de echte randen terugrekenen.
    px0, py0 = int((x0 - tx0) * 256), int((y0 - ty0) * 256)
    px1, py1 = int((x1 - tx0) * 256) + 1, int((y1 - ty0) * 256) + 1
    beeld = np.asarray(mozaiek.crop((px0, py0, px1, py1)))
    lat_n2, lon_w2 = _tegel_latlon(tx0 + px0 / 256.0, ty0 + py0 / 256.0, z)
    lat_z2, lon_o2 = _tegel_latlon(tx0 + px1 / 256.0, ty0 + py1 / 256.0, z)
    return beeld, (lat_z2, lat_n2, lon_w2, lon_o2)


def luchtfoto_onder(assen, lat0, lon0, xmin, xmax, ymin, ymax):
    """Legt de luchtfoto onder elke as (in meters rond lat0/lon0); True als dat lukte."""
    lat_z, lon_w = _meters_naar_latlon(xmin, ymin, lat0, lon0)
    lat_n, lon_o = _meters_naar_latlon(xmax, ymax, lat0, lon0)
    foto = satelliet(lat_z, lat_n, lon_w, lon_o)
    if foto is None:
        return False
    beeld, (fz, fn, fw, fo) = foto
    fx0, fy0 = xy(fz, fw, lat0, lon0)
    fx1, fy1 = xy(fn, fo, lat0, lon0)
    for ax in assen:
        ax.imshow(beeld, extent=(fx0, fx1, fy0, fy1), origin="upper", zorder=0)
    return True


# ==========================================
# ROUTEKAART
# ==========================================

def route_kaart(rows, uit_pad, titel):
    """Gereden route op de luchtfoto: banen gekleurd naar de afwijking van de lijn, kopakker als dunne lijn."""
    pp = [r for r in rows if r["lat"] != 0.0 and r["lon"] != 0.0]
    if len(pp) < 2:
        raise Overgeslagen("geen GPS-posities in deze log")
    lat0 = avg([r["lat"] for r in pp])
    lon0 = avg([r["lon"] for r in pp])
    x, y = (np.array(v) for v in zip(*[xy(r["lat"], r["lon"], lat0, lon0) for r in pp]))
    marge = 5.0
    xmin, xmax, ymin, ymax = x.min() - marge, x.max() + marge, y.min() - marge, y.max() + marge
    hoog = min(14.0, max(4.0, 11.0 * (ymax - ymin) / (xmax - xmin)))
    fig, ax = plt.subplots(figsize=(13, hoog + 1.5))
    foto = luchtfoto_onder([ax], lat0, lon0, xmin, xmax, ymin, ymax)

    # Het hele pad als dunne lijn, onderbroken waar de log een gat heeft.
    sprong = np.r_[False, np.hypot(np.diff(x), np.diff(y)) > 5.0]
    ax.plot(np.where(sprong, np.nan, x), y, color="white" if foto else "#555", lw=0.9, alpha=0.8,
            zorder=1, label="gereden pad (ook kopakker)")

    baan = np.array([r["modus"] == "TRACKING" for r in pp])
    if baan.any():
        v = np.array([abs(xte_waarde(r)) * 100 for r in pp])[baan]
        sc = ax.scatter(x[baan], y[baan], c=v, s=5, cmap="RdYlGn_r", vmin=0,
                        vmax=max(10.0, float(np.percentile(v, 98))), zorder=2, edgecolors="none")
        fig.colorbar(sc, ax=ax, label="afwijking van de lijn (cm)", shrink=0.8)
        # Baannummer midden op elke baan.
        i = 0
        while i < len(pp):
            if pp[i]["modus"] != "TRACKING":
                i += 1
                continue
            j = i
            while j + 1 < len(pp) and pp[j + 1]["modus"] == "TRACKING" and pp[j + 1]["idx"] == pp[i]["idx"]:
                j += 1
            if j - i > 50:
                k = (i + j) // 2
                ax.text(x[k], y[k], f"baan {pp[i]['idx']}", fontsize=8, ha="center", va="center", zorder=4,
                        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.8})
            i = j + 1
    else:
        v = np.array([r["echt_kmh"] for r in pp])
        sc = ax.scatter(x, y, c=v, s=5, cmap="viridis", zorder=2, edgecolors="none")
        fig.colorbar(sc, ax=ax, label="snelheid (km/h)", shrink=0.8)

    ax.scatter(x[0], y[0], c="#1e88e5", s=110, marker="o", edgecolors="black", zorder=5, label="start")
    ax.scatter(x[-1], y[-1], c="black", s=110, marker="X", edgecolors="white", zorder=5, label="eind")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_xlabel("oost (m)")
    ax.set_ylabel("noord (m)")
    ax.set_title(f"Route: {titel}" + ("  (luchtfoto: Esri World Imagery)" if foto else ""), fontsize=11)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    return bewaar(fig, uit_pad, 150)


# ==========================================
# AANDRIJVING: trekkracht, vermogen, verbruik, accu
# ==========================================
# De TREKKRACHT wordt NIET gemeten maar uitgerekend uit de motorstroom:
#     koppel motor = 1.5 x poolparen x lambda x I_q
#     kracht wiel  = koppel motor x overbrenging x rendement kast / straal band
#   - lambda (flux linkage, Wb) komt uit de log zelf: bij middelhoog toerental en
#     weinig stroom geldt  lambda = (duty x Accu_V / wortel 3) / (hoeksnelheid
#     elektrisch). Dat geeft per rit nagenoeg hetzelfde (1 nov 2026: 0.064 Wb).
#     Weet je hem uit de VESC Tool (Motor Setup Wizard), geef hem dan op met --lambda.
#   - rendement van de kast staat op 0.9 (gokje, wijzigen met --kast-rendement).
# Het is dus een goede schatting, geen meting. IJken kan met een trekproef: een
# weegschaal of krachtmeter tussen robot en een vaste paal, wiel op vast
# toerental, dan stroom en kracht vergelijken.
# De fabrikant geeft 50 kgf trekkracht per hubmotor (490 N); die staat als lijn in de grafiek.

def rit_dataframe(raw_rows):
    """Ritlog als DataFrame met een tijdas in seconden."""
    d = pd.DataFrame(raw_rows)
    if "WP_Doel" not in d or "Tijdstip" not in d:
        raise Overgeslagen("onbekend logformaat")
    d = d[pd.to_numeric(d["WP_Doel"], errors="coerce").notna()].copy()
    for kolom in d.columns[3:]:
        d[kolom] = pd.to_numeric(d[kolom], errors="coerce")
    t = pd.to_datetime(d["Tijdstip"], format="%H:%M:%S.%f", errors="coerce").ffill()
    sec = (t - t.iloc[0]).dt.total_seconds().to_numpy()
    sec[sec < 0] += 86400.0                      # rit over middernacht
    d["t"] = sec
    return d.reset_index(drop=True)


def schat_lambda(d, i_max=4.0):
    """Flux linkage (Wb) uit duty, accuspanning en toerental; weinig stroom = weinig weerstandsval."""
    kandidaten = []
    for z in "LR":
        erpm, duty, stroom = d[f"ERPM_{z}"], d[f"Duty_{z}"], d[f"Motorstroom_{z}_A"].abs()
        ok = (erpm > 1500) & (duty > 0.1) & (d["Accu_V"] > 20)
        for grens in (i_max, 1e9):               # eerst alleen lage stroom, anders alles
            m = ok & (stroom <= grens)
            if m.sum() >= 50:
                w = erpm[m] * 2 * math.pi / 60.0
                kandidaten.append(((duty[m] * d["Accu_V"][m] / math.sqrt(3.0)) / w).median())
                break
    return float(np.median(kandidaten)) if kandidaten else None


def gladder(x, n=12):
    return pd.Series(x).rolling(n, center=True, min_periods=1).median().to_numpy()


def bereken_kracht(d, cfg, lam, eta):
    """Voegt de trekkracht per wiel toe; geeft (Nm per ampere motor, bandstraal)."""
    r_band = cfg["omtrek_m"] / (2 * math.pi)
    kt_motor = 1.5 * cfg["poolparen"] * lam
    for z in "LR":
        i = d[f"Motorstroom_{z}_A"].fillna(0.0)
        d[f"Kracht_{z}_N"] = kt_motor * i * cfg["overbrenging"] * eta / r_band
    d["Kracht_N"] = d["Kracht_L_N"] + d["Kracht_R_N"]
    d["v_ms"] = (d["Wiel_kmh_L"].fillna(0) + d["Wiel_kmh_R"].fillna(0)) / 2 / 3.6
    return kt_motor, r_band


def spanningsval(d):
    """Lineaire fit V = V0 - R x I over de accustroom: (V0, R, aantal punten)."""
    m = (d["Accu_A"] > 2.0) & (d["Accu_V"] > 20)
    if m.sum() < 100:
        return None
    r, v0 = np.polyfit(d.loc[m, "Accu_A"], d.loc[m, "Accu_V"], 1)
    return v0, -r, int(m.sum())


def aandrijving_figuur(d, cfg, lam, vd, uit_pad, titel):
    t = d["t"].to_numpy()
    fig, ax = plt.subplots(4, 2, figsize=(16, 17), constrained_layout=True)
    fig.suptitle(titel, fontsize=14)

    a = ax[0, 0]
    a.plot(t, gladder(d["Wiel_kmh_L"]), color=KLEUR_L, label="wiel L")
    a.plot(t, gladder(d["Wiel_kmh_R"]), color=KLEUR_R, label="wiel R")
    a.plot(t, d["Echt_kmh"], color="grey", lw=0.8, label="GNSS")
    a.set_ylabel("snelheid (km/h)"); a.set_title("Snelheid en duty")
    b = a.twinx()
    b.plot(t, gladder(d["Duty_L"]), color="black", lw=0.8, ls="--", label="duty L")
    b.axhline(0.95, color="orange", lw=0.8)
    b.set_ylim(0, 1.05); b.set_ylabel("duty (1 = vol)")
    a.legend(loc="upper left", ncol=3)

    a = ax[0, 1]
    a.plot(t, gladder(d["Kracht_L_N"]), color=KLEUR_L, label="wiel L")
    a.plot(t, gladder(d["Kracht_R_N"]), color=KLEUR_R, label="wiel R")
    a.axhline(SPEC_TREKKRACHT_N, color="green", ls=":", label="spec 50 kgf per motor")
    a.set_ylabel("trekkracht (N)"); a.set_title(f"Trekkracht per wiel (geschat, lambda {lam:.3f} Wb)")
    k = a.secondary_yaxis("right", functions=(lambda n: n / G, lambda kg: kg * G))
    k.set_ylabel("kgf"); a.legend(loc="upper left", ncol=3)

    a = ax[1, 0]
    a.plot(t, d["Accu_V"], color="tab:green")
    a.set_ylabel("accuspanning (V)"); a.set_title("Accu: spanning en stroom")
    b = a.twinx()
    b.plot(t, gladder(d["Accu_A"]), color="tab:purple", lw=0.8)
    b.set_ylabel("accustroom (A)")
    for v, tekst in ((cfg["cellen"] * 3.0, "leeg 3.0 V/cel"), (cfg["cellen"] * 3.3, "bijna leeg 3.3 V/cel")):
        a.axhline(v, color="red", lw=0.7, ls=":")
        a.text(t[0], v, tekst, color="red", fontsize=8, va="bottom")

    a = ax[1, 1]
    a.plot(t, gladder(d["Accu_W"]), color="tab:purple", label="totaal uit accu")
    a.plot(t, gladder(d["Accustroom_L_A"] * d["Accu_V"]), color=KLEUR_L, lw=0.9, label="wiel L")
    a.plot(t, gladder(d["Accustroom_R_A"] * d["Accu_V"]), color=KLEUR_R, lw=0.9, label="wiel R")
    a.set_ylabel("vermogen (W)"); a.set_title("Elektrisch vermogen uit de accu")
    a.legend(loc="upper left", ncol=3)

    a = ax[2, 0]
    m = (d["Accu_A"] > 0.5) & (d["Accu_V"] > 20)
    a.scatter(d.loc[m, "Accu_A"], d.loc[m, "Accu_V"], s=3, alpha=0.3, color="tab:green")
    if vd:
        v0, r, n = vd
        x = np.array([0, d["Accu_A"].max()])
        a.plot(x, v0 - r * x, color="black",
               label=f"fit: {v0:.1f} V - {r:.3f} ohm x I  ({n} punten)")
        a.axhline(cfg["cellen"] * 3.0, color="red", lw=0.7, ls=":")
        a.legend()
    a.set_xlabel("accustroom (A)"); a.set_ylabel("accuspanning (V)")
    a.set_title(f"Spanningsval = interne weerstand (config: {cfg['weerstand_config']:.2f} ohm)")

    a = ax[2, 1]
    s = d["Wiel_kmh_L"].to_numpy()
    sc = a.scatter(np.r_[s, d["Wiel_kmh_R"].to_numpy()],
                   np.r_[d["Kracht_L_N"].to_numpy(), d["Kracht_R_N"].to_numpy()],
                   s=3, alpha=0.3, c=np.r_[t, t], cmap="viridis")
    a.axhline(SPEC_TREKKRACHT_N, color="green", ls=":")
    a.set_xlabel("wielsnelheid (km/h)"); a.set_ylabel("trekkracht per wiel (N)")
    a.set_title("Kracht tegen snelheid (kleur = tijd in de rit)")
    fig.colorbar(sc, ax=a, label="s")

    a = ax[3, 0]
    a.plot(t, d["Temp_FET_L_C"], color=KLEUR_L, label="FET L")
    a.plot(t, d["Temp_FET_R_C"], color=KLEUR_R, label="FET R")
    a.plot(t, d["Motortemp_model_L_C"], color=KLEUR_L, ls="--", label="motor L (model)")
    a.plot(t, d["Motortemp_model_R_C"], color=KLEUR_R, ls="--", label="motor R (model)")
    a.axhline(105, color="red", lw=0.7, ls=":"); a.text(t[0], 105, "motor beveiliging 105 C", color="red", fontsize=8, va="bottom")
    a.set_ylabel("temperatuur (C)"); a.set_title("Temperaturen"); a.legend(ncol=2)

    a = ax[3, 1]
    a.plot(t, d["Verbruikt_Wh"], color="tab:purple", label="verbruikt (Wh)")
    a.plot(t, d["Teruggeleverd_Wh"], color="tab:green", label="teruggeleverd (Wh)")
    a.set_ylabel("energie (Wh)"); a.set_title("Verbruik en lading"); a.legend(loc="upper left")
    b = a.twinx()
    b.plot(t, d["Accu_pct"], color="black", lw=0.8, ls="--")
    b.set_ylim(0, 100); b.set_ylabel("lading (%), schatting uit spanning")

    for a in ax.flat:
        a.grid(alpha=0.3)
    for a in (ax[0, 0], ax[0, 1], ax[1, 0], ax[1, 1], ax[3, 0], ax[3, 1]):
        a.set_xlabel("tijd in de rit (s)")
    return bewaar(fig, uit_pad, 110)


AANDRIJVING_UITLEG = [
    ("Vermogen (W)", "Wat de accu levert: accuspanning x accustroom. Het gemiddelde tijdens rijden telt alleen "
                     "de momenten dat de robot beweegt; het gemiddelde over de hele rit is energie gedeeld door tijd."),
    ("Motorstroom en accustroom", "De motorstroom is de stroom die het koppel levert (per wiel). De accustroom is wat "
                                  "de accu levert; bij lage duty is die kleiner dan de motorstroom (de VESC zet spanning "
                                  "om in stroom: accustroom ≈ duty x motorstroom)."),
    ("Duty", "Hoeveel van de accuspanning de motor krijgt: 1.0 is vol. Hoe leger de accu, hoe hoger de duty voor "
             "dezelfde snelheid. Rond 0.95 houdt het op."),
    ("Trekkracht", "Geschat uit de motorstroom: koppel = 1.5 x poolparen x λ x stroom, door de kast (x overbrenging "
                   "x rendement) en gedeeld door de bandstraal. Het is een berekening, geen meting; ijk hem met een "
                   "krachtmeter. λ komt uit de log zelf."),
    ("Verbruik (Wh/km)", "Energie per afgelegde kilometer. Hoger bij hogere snelheid, zware grond, veel bochten en "
                         "veel optrekken."),
    ("Interne weerstand", "De accuspanning zakt bij meer stroom. Het verband tussen stroom en spanning geeft de "
                          "interne weerstand; hoger = ouder of kouder pak of een slechtere verbinding."),
    ("Lading (%)", "Een schatting uit de spanning, gecorrigeerd voor de spanningsval. Betrouwbaar als balk, niet tot "
                   "op de procent."),
]


def aandrijving(raw_rows, cfg, lam_arg, eta, jpg_pad, titel):
    """Trekkracht, vermogen, verbruik en accu uit de VESC-kolommen: kerngetallen, tabellen, bevindingen en grafieken."""
    d = rit_dataframe(raw_rows)
    if len(d) < 50 or "Motorstroom_L_A" not in d or d["Motorstroom_L_A"].notna().sum() < 50:
        raise Overgeslagen("geen VESC-kolommen in deze log (rit van voor de VESC's)")
    lam = lam_arg or schat_lambda(d)
    if not lam:
        raise Overgeslagen("lambda niet te schatten (te weinig regels bij middelhoog toerental); geef --lambda op")
    kt, r_band = bereken_kracht(d, cfg, lam, eta)
    vd = spanningsval(d)
    aandrijving_figuur(d, cfg, lam, vd, jpg_pad, f"{titel}: aandrijving en accu")

    t = d["t"].to_numpy()
    dt = np.clip(np.diff(t, prepend=t[0]), 0.0, 1.0)             # s per regel (gaten niet meetellen)
    rijdt = d["v_ms"] > 0.3
    duur = float(t[-1] - t[0])
    afstand = max(d["Afstand_L_m"].iloc[-1] - d["Afstand_L_m"].iloc[0],
                  d["Afstand_R_m"].iloc[-1] - d["Afstand_R_m"].iloc[0])
    wh = d["Verbruikt_Wh"].iloc[-1] - d["Verbruikt_Wh"].iloc[0]
    wh_terug = d["Teruggeleverd_Wh"].iloc[-1] - d["Teruggeleverd_Wh"].iloc[0]
    ah = d["Verbruikt_Ah"].iloc[-1] - d["Verbruikt_Ah"].iloc[0]
    wh_km = wh / max(afstand, 1.0) * 1000.0
    nominaal_wh = cfg["capaciteit_ah"] * cfg["cellen"] * NOMINAAL_V_PER_CEL
    soc0, soc1 = d["Accu_pct"].iloc[0], d["Accu_pct"].iloc[-1]
    cel_min = d["Accu_V"].min() / cfg["cellen"]
    w, a_acc = d["Accu_W"], d["Accu_A"]
    gem_w_rit = wh * 3600.0 / max(duur, 1e-6)                    # energie / tijd, over de hele rit
    kr_max = max(d["Kracht_L_N"].max(), d["Kracht_R_N"].max())
    duty_hoog = ((d["Duty_L"] > 0.9) | (d["Duty_R"] > 0.9)).mean() * 100.0
    verschil = (d["Kracht_L_N"] - d["Kracht_R_N"])[rijdt].mean()
    kr_gem = (d["Kracht_L_N"][rijdt].mean() + d["Kracht_R_N"][rijdt].mean()) / 2.0
    n_per_a = kt * cfg["overbrenging"] * eta / r_band

    kaarten = [
        ("Gemiddeld vermogen", f"{fmt(w[rijdt].mean(), 0)} W", f"tijdens rijden; hele rit {fmt(gem_w_rit, 0)} W"),
        ("Piekvermogen", f"{fmt(w.max(), 0)} W", f"P95 {fmt(w.quantile(.95), 0)} W"),
        ("Verbruik", f"{fmt(wh_km, 0)} Wh/km", f"{fmt(wh)} Wh over {fmt(afstand, 0)} m"),
        ("Gemiddelde accustroom", f"{fmt(a_acc[rijdt].mean())} A", f"max {fmt(a_acc.max())} A"),
        ("Accuspanning", f"{fmt(d['Accu_V'].iloc[0])} → {fmt(d['Accu_V'].iloc[-1])} V",
         f"minimum {fmt(d['Accu_V'].min())} V ({fmt(cel_min, 2)} V/cel)"),
        ("Lading (schatting)", f"{fmt(soc0, 0)} → {fmt(soc1, 0)} %", "uit de spanning, niet gemeten"),
        ("Gem. trekkracht per wiel", f"{fmt(kr_gem, 0)} N", f"≈ {fmt(kr_gem / G, 0)} kgf; max {fmt(kr_max, 0)} N"),
        ("Gem. snelheid", f"{fmt(afstand / max(duur, 1e-6) * 3.6)} km/h", f"{fmt(duur, 0)} s, {fmt(afstand, 0)} m"),
    ]

    # --- per wiel (een kolom per wiel)
    per_wiel = {}
    for z in "LR":
        kr = d[f"Kracht_{z}_N"]
        per_wiel[z] = [
            f"{fmt(d[f'Wiel_kmh_{z}'][rijdt].mean())} km/h",
            f"{fmt(d[f'Motorstroom_{z}_A'][rijdt].mean())} / {fmt(d[f'Motorstroom_{z}_A'].max())} A",
            f"{fmt(kr[rijdt].mean(), 0)} / {fmt(kr[rijdt].quantile(.95), 0)} / {fmt(kr.max(), 0)} N",
            f"{fmt(kr.max() / SPEC_TREKKRACHT_N * 100, 0)} %",
            f"{fmt(d[f'Duty_{z}'][rijdt].mean(), 2)} / {fmt(d[f'Duty_{z}'].max(), 2)}",
            f"{fmt((d[f'Accustroom_{z}_A'] * d['Accu_V'])[rijdt].mean(), 0)} W",
            f"{fmt(d[f'Temp_FET_{z}_C'].max(), 0)} / {fmt(d[f'Motortemp_model_{z}_C'].max(), 0)} °C",
            f"{fmt(d[f'Afstand_{z}_m'].iloc[-1] - d[f'Afstand_{z}_m'].iloc[0], 0)} m",
        ]
    namen = ["Gem. snelheid", "Motorstroom gem / max", "Trekkracht gem / P95 / max", "Max t.o.v. spec",
             "Duty gem / max", "Gem. vermogen", "Temp. FET / motor max", "Afstand"]
    wiel_rijen = [[n, l, r] for n, l, r in zip(namen, per_wiel["L"], per_wiel["R"])]

    # --- per modus (rechte baan of draaien)
    modus_rijen = []
    for modus, g in d.groupby("Modus"):
        sec = dt[g.index].sum()
        modus_rijen.append([
            modus, f"{fmt(sec, 0)} s ({fmt(sec / max(dt.sum(), 1e-9) * 100, 0)} %)",
            f"{fmt(g['v_ms'].mean() * 3.6)} km/h",
            f"{fmt(g['Accu_W'].mean(), 0)} W", f"{fmt(g['Accu_A'].mean())} A",
            f"{fmt((g['Kracht_L_N'].mean() + g['Kracht_R_N'].mean()) / 2, 0)} N",
            f"{fmt((g['Accu_W'] * dt[g.index]).sum() / 3600.0)} Wh"])

    # --- per snelheidsklasse
    kmh = d["v_ms"] * 3.6
    snel_rijen = []
    for lo, hi in ((0.3, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 99.0)):
        m = (kmh >= lo) & (kmh < hi)
        if m.sum() < 10:
            continue
        snel_rijen.append([
            f"{fmt(lo, 0)} - {fmt(hi, 0)} km/h" if hi < 99 else f"boven {fmt(lo, 0)} km/h",
            f"{fmt(dt[m].sum(), 0)} s", f"{fmt(d['Accu_W'][m].mean(), 0)} W", f"{fmt(d['Accu_A'][m].mean())} A",
            f"{fmt((d['Kracht_L_N'][m].mean() + d['Kracht_R_N'][m].mean()) / 2, 0)} N",
            f"{fmt(d['Duty_L'][m].mean(), 2)}",
            f"{fmt(d['Accu_W'][m].mean() / (kmh[m].mean() / 3.6) / 3.6, 0)} Wh/km"])

    # --- per 30 s
    blok = (t - t[0]) // 30
    blok_rijen = []
    for b, g in d.groupby(blok):
        blok_rijen.append([f"{int(b * 30)} - {int(b * 30 + 30)} s", f"{fmt(g['v_ms'].mean() * 3.6)}",
                           f"{fmt(g['Accu_W'].mean(), 0)}", f"{fmt(g['Accu_V'].mean())}", f"{fmt(g['Accu_A'].mean())}",
                           f"{fmt((g['Kracht_L_N'].mean() + g['Kracht_R_N'].mean()) / 2, 0)}",
                           f"{fmt(g['Duty_L'].max(), 2)}", f"{fmt(g['Accu_pct'].iloc[-1], 0)}"])

    # --- accu en verbruik
    resterend_wh = nominaal_wh * soc1 / 100.0
    accu_rijen = [
        ("Accu", f"{cfg['cellen']}S, {fmt(cfg['capaciteit_ah'], 1)} Ah ≈ {fmt(nominaal_wh, 0)} Wh nominaal"),
        ("Spanning begin / eind / min", f"{fmt(d['Accu_V'].iloc[0])} / {fmt(d['Accu_V'].iloc[-1])} / {fmt(d['Accu_V'].min())} V"),
        ("Verbruikt in de rit", f"{fmt(wh)} Wh = {fmt(ah, 2)} Ah (teruggeleverd {fmt(wh_terug)} Wh)"),
        ("Verbruik per kilometer", f"{fmt(wh_km, 0)} Wh/km"),
        ("Bereik op een volle accu", f"ca. {fmt(nominaal_wh / max(wh_km, 1e-6), 1)} km (bij dit verbruik)"),
        ("Bereik op de huidige lading", f"ca. {fmt(resterend_wh / max(wh_km, 1e-6), 1)} km "
                                        f"(bij {fmt(soc1, 0)} % ≈ {fmt(resterend_wh, 0)} Wh)"),
        ("Interne weerstand", (f"{fmt(vd[1], 3)} Ω uit de spanningsval (config {fmt(cfg['weerstand_config'], 2)} Ω); "
                               f"rustspanning volgens de fit {fmt(vd[0])} V" if vd else "te weinig data")),
        ("Spanningsval bij piekstroom", (f"{fmt(vd[1] * a_acc.max())} V bij {fmt(a_acc.max())} A" if vd else "-")),
        ("Motorconstante", f"λ {fmt(lam, 4)} Wb{' (opgegeven)' if lam_arg else ' (uit de log)'} = {fmt(kt, 2)} Nm/A motor "
                           f"= {fmt(n_per_a, 1)} N per ampere aan het wiel (kast {fmt(eta, 2)})"),
    ]

    # --- bevindingen
    bev = []
    if duty_hoog >= 1.0:
        bev.append(("letop", f"De duty is {fmt(duty_hoog, 0)} % van de tijd boven 0.90. Dan heeft de regeling geen ruimte "
                    "meer om bij te sturen of sneller te gaan; de topsnelheid wordt begrensd door de accuspanning, "
                    "niet door het toerental."))
    if cel_min < 3.3:
        bev.append(("letop", f"Onder belasting zakte de accu tot {fmt(cel_min, 2)} V per cel (grens 'bijna leeg': 3.3 V). "
                    "Laad de accu voor een vergelijkbare rit eerst op."))
    if soc0 < 25:
        bev.append(("letop", f"De rit begon met een lage lading (ongeveer {fmt(soc0, 0)} %). Spanning, snelheid en verbruik "
                    "zijn daardoor niet vergelijkbaar met ritten op een volle accu."))
    if vd and abs(vd[1] - cfg["weerstand_config"]) / cfg["weerstand_config"] > 0.25:
        bev.append(("info", f"De gemeten interne weerstand ({fmt(vd[1], 3)} Ω) wijkt meer dan 25 % af van de config "
                    f"({fmt(cfg['weerstand_config'], 2)} Ω). Het % lading op het dashboard is dan iets minder betrouwbaar."))
    if abs(verschil) > max(10.0, 0.1 * kr_gem):
        bev.append(("info", f"Links en rechts verschillen gemiddeld {fmt(abs(verschil), 0)} N. Het "
                    f"{'linker' if verschil > 0 else 'rechter'} wiel werkt harder; kan komen door bochten de ene kant op, "
                    "een schuin veld of meer weerstand in dat wiel."))
    if kr_max / SPEC_TREKKRACHT_N > 0.8:
        bev.append(("letop", f"De piekkracht ({fmt(kr_max, 0)} N) zit dicht bij de spec van 490 N per motor."))
    else:
        bev.append(("goed", f"De trekkracht blijft ruim onder de spec: piek {fmt(kr_max, 0)} N van 490 N "
                    f"({fmt(kr_max / SPEC_TREKKRACHT_N * 100, 0)} %). Er is reserve voor een helling of zware grond."))
    temp_max = max(d["Temp_FET_L_C"].max(), d["Temp_FET_R_C"].max(),
                   d["Motortemp_model_L_C"].max(), d["Motortemp_model_R_C"].max())
    bev.append(("goed" if temp_max < 80 else "letop",
                f"Hoogste temperatuur {fmt(temp_max, 0)} °C (motorbeveiliging grijpt in bij 105 °C)."))

    blokken = [
        ("h3", "Per wiel"),
        ("tabel", ["", "Links", "Rechts"], wiel_rijen, set()),
        ("p", f"Kracht is geschat (λ {fmt(lam, 4)} Wb = {fmt(kt, 2)} Nm/A motor, kast {fmt(eta, 2)}, band "
              f"{fmt(r_band * 100, 1)} cm straal); spec: 490 N (50 kgf) per motor. Gemiddelden zijn over de "
              "momenten dat de robot rijdt."),
        ("h3", "Accu en verbruik"),
        ("kv", [("kv", k, v, False) for k, v in accu_rijen]),
        ("h3", "Per rijmodus"),
        ("tabel", ["Modus", "Tijd", "Gem. snelheid", "Gem. vermogen", "Gem. accustroom",
                   "Gem. kracht per wiel", "Energie"], modus_rijen, set()),
        ("p", "TRACKING = op de baan rijden, TURNING = keren op de kopakker."),
        ("h3", "Per snelheid"),
        ("tabel", ["Snelheid", "Tijd", "Gem. vermogen", "Gem. accustroom", "Gem. kracht per wiel",
                   "Gem. duty", "Verbruik"], snel_rijen, set()),
        ("p", "Wat elke snelheid kost. Het verbruik per kilometer is vermogen gedeeld door snelheid; blijft dat "
              "ongeveer gelijk, dan zit het verbruik vooral in rolweerstand en niet in de snelheid zelf."),
        ("h3", "Verloop per 30 seconden"),
        ("tabel", ["Periode", "km/h", "W", "V", "A", "N per wiel", "Duty max", "Lading %"], blok_rijen, set()),
        ("h3", "Grafieken"),
        ("beeld", jpg_pad, "Snelheid en duty, trekkracht per wiel, accuspanning en -stroom, vermogen, spanningsval, "
                           "kracht tegen snelheid, temperaturen, verbruik en lading."),
        ("h3", "Uitleg"),
        ("dl", AANDRIJVING_UITLEG),
    ]
    return {"kaarten": kaarten, "bevindingen": bev, "blokken": blokken, "jpg": jpg_pad}


# ==========================================
# TERREIN: hoogte, helling en ruwheid
# ==========================================
# De HELLING op de kaart komt op twee manieren:
#   - pitch: wat de dubbele antenne direct meet, maar alleen IN DE RIJRICHTING.
#     Rijd je dwars over een helling, dan ziet de pitch hem niet.
#   - uit de hoogtekaart: de echte steilheid in de steilste richting. Werkt
#     beter naarmate er meer banen naast elkaar gereden zijn.
# De hoogte komt uit de RTK-hoogte (Hoogte_Grond_m: GGA, gecorrigeerd voor de
# antennehoogte, op de plek Grond_Lat/Grond_Lon). Oudere ritlogs hebben die niet:
# dan rekent hoogte_uit_pitch() een RELATIEVE hoogte terug uit de pitch en staat
# er overal 'geschat' bij.
# Daarnaast schat hij de scheefstand van de antennemontage: rijd heen en terug,
# dan keert een helling om en blijft de montage gelijk. Zet die waarde bij
# gnss.pitch_offset_deg in de config (staat hij goed: ~0).

def lees_terrein(raw_rows):
    """Punten {lat, lon, hoogte, pitch, ruwheid, kmh, heading} met RTK fixed, een per 25 cm."""
    punten = []
    for r in raw_rows:
        if r.get("Fix") != "4":
            continue
        # Hoogte_Grond_m hoort bij de grond onder de antenne (Grond_Lat/Lon), niet bij het regelpunt.
        p = {"lat": getal(r.get("Grond_Lat")) or getal(r.get("Lat")),
             "lon": getal(r.get("Grond_Lon")) or getal(r.get("Lon")),
             "hoogte": getal(r.get("Hoogte_Grond_m")), "pitch": getal(r.get("Pitch_deg")),
             "ruwheid": getal(r.get("Ruwheid_deg")), "kmh": getal(r.get("Echt_kmh")),
             "heading": getal(r.get("Heading_Echt"))}
        if p["lat"] and p["lon"]:
            punten.append(p)
    return dun_uit(punten, 0.25)


def dun_uit(punten, stap):
    """Ritlogs hebben 25 regels per seconde: houd er een per 'stap' meter over (zo'n 4 punten per meter)."""
    uit, vorige = [], None
    for p in punten:
        if vorige is None or math.hypot(*xy(p["lat"], p["lon"], vorige["lat"], vorige["lon"])) >= stap:
            uit.append(p)
            vorige = p
    return uit


def montage_schatting(punten):
    """
    Scheefstand van de antennemontage uit de pitch: een helling keert om als
    je de andere kant op rijdt, de montage niet. Per paar tegengestelde
    rijrichtingen (vakken van 45 graden) is het gemiddelde de montage.
    Geeft None als er niet in tegengestelde richtingen gereden is.
    """
    vakken = {}
    for p in punten:
        if p["pitch"] is not None and p["heading"] is not None and (p["kmh"] or 0) > 0.5:
            vakken.setdefault(int((p["heading"] % 360) // 45), []).append(p["pitch"])
    # Alleen het paar tegengestelde richtingen waarin het meest gereden is:
    # dat zijn de banen. Kopakkerbochten vallen in de andere vakken.
    paren = [(min(len(vakken[k]), len(vakken[k + 4])), k) for k in range(4)
             if len(vakken.get(k, [])) >= 30 and len(vakken.get(k + 4, [])) >= 30]
    if not paren:
        return None
    _, k = max(paren)
    gem = lambda v: sum(v) / len(v)
    return (gem(vakken[k]) + gem(vakken[k + 4])) / 2


def vul_aan(punten):
    """Montage-scheefstand van de pitch af; ontbrekende ruwheid uit de pitch rond elk punt. Geeft de montage."""
    montage = montage_schatting(punten)
    if montage is not None:
        for p in punten:
            if p["pitch"] is not None:
                p["pitch"] -= montage
    if all(p["ruwheid"] is None for p in punten):
        # ~1 s rijden bij 3-4 km/h = ongeveer 1 m = 4 punten van 0.25 m
        for i, p in enumerate(punten):
            venster = [q["pitch"] for q in punten[max(0, i - 4):i + 1] if q["pitch"] is not None]
            if len(venster) >= 3:
                g = sum(venster) / len(venster)
                p["ruwheid"] = math.sqrt(sum((v - g) ** 2 for v in venster) / len(venster))
    return montage


def hoogte_uit_pitch(punten, buur_m=5.0, ridge=1000.0, max_paren=20000):
    """
    Relatieve hoogte uit de pitch, voor ritlogs zonder RTK-hoogte (Hoogte_Grond_m).
    Geeft (gelukt, melding).

    Per meter rijden is de hoogtewinst tan(pitch). Optellen langs de route
    loopt echter weg zodra de pitch een kleine vaste fout heeft (1 graad op
    100 m is 1,7 m). Daarom krijgt elk rechtstuk (koers binnen 30 graden) een
    eigen onbekende restfout, en wordt die zo gekozen dat naast elkaar
    liggende banen (binnen buur_m, iets meer dan de baanafstand) dezelfde hoogte krijgen. Heen en terug
    over dezelfde strook levert dus de ijking. De restfouten worden STERK naar
    een gemeenschappelijke waarde getrokken (ridge): de montagefout is in
    werkelijkheid een vaste waarde. Laat je elk stuk vrij (ridge ~ 3), dan is een
    vlak veld altijd een geldige oplossing en verdwijnt de helling in de
    rijrichting. Vanaf ridge ~ 300 is de uitkomst stabiel.

    Resultaat: p["hoogte"] in meter RELATIEF (nul = gemiddelde van het veld),
    geen hoogte boven zeeniveau. De helling in de rijrichting is goed; de
    helling dwars daarop wordt alleen via de aansluiting tussen de banen
    bepaald en is minder zeker.
    """
    from scipy.spatial import cKDTree
    pp = [p for p in punten if p["pitch"] is not None]
    if len(pp) < 200:
        return False, "Hoogte uit de pitch niet mogelijk: te weinig punten met pitch."
    lat0 = sum(p["lat"] for p in pp) / len(pp)
    lon0 = sum(p["lon"] for p in pp) / len(pp)
    xy_ = np.array([xy(p["lat"], p["lon"], lat0, lon0) for p in pp])
    ds = np.r_[0.0, np.hypot(*np.diff(xy_, axis=0).T)]
    sprongen = int((ds > 2.0).sum())
    ds[ds > 2.0] = 0.0                       # gat in de log: niet meetellen
    s = np.cumsum(ds)
    seg = np.zeros(len(pp), dtype=int)
    k, ref = 0, pp[0]["heading"]
    for i, p in enumerate(pp):
        h = p["heading"]
        if h is not None and ref is not None and abs((h - ref + 180.0) % 360.0 - 180.0) > 30.0:
            k, ref = k + 1, h
        seg[i] = k
    nseg = k + 1
    hoogtewinst = np.cumsum(ds * np.tan(np.radians([p["pitch"] for p in pp])))
    een = np.zeros((len(pp), nseg))
    een[np.arange(len(pp)), seg] = ds
    A = np.cumsum(een, axis=0)               # meter gereden per rechtstuk tot elk punt

    paren = cKDTree(xy_).query_pairs(buur_m, output_type="ndarray")
    if len(paren) == 0:
        return False, "Hoogte uit de pitch niet mogelijk: geen banen die naast elkaar liggen."
    i, j = paren.T
    ok = (np.abs(seg[i] - seg[j]) >= 2) & (np.abs(s[i] - s[j]) > 10.0)
    i, j = i[ok], j[ok]
    if len(i) < 50:
        return False, "Hoogte uit de pitch niet mogelijk: te weinig banen die naast elkaar liggen."
    if len(i) > max_paren:
        kies = np.random.default_rng(0).choice(len(i), max_paren, replace=False)
        i, j = i[kies], j[kies]
    M = np.zeros((len(i) + nseg, nseg + 1))
    v = np.zeros(len(i) + nseg)
    M[:len(i), :nseg] = A[i] - A[j]
    v[:len(i)] = hoogtewinst[i] - hoogtewinst[j]
    for r in range(nseg):                    # restfout van elk stuk ~ gemeenschappelijke waarde
        M[len(i) + r, r], M[len(i) + r, nseg] = ridge, -ridge
    b = np.linalg.lstsq(M, v, rcond=None)[0]
    rest = M[:len(i)] @ b - v[:len(i)]
    h = hoogtewinst - A @ b[:nseg]
    h -= h.mean()
    for p, hh in zip(pp, h):
        p["hoogte"] = float(hh)
    return True, (f"Hoogte GESCHAT uit de pitch (relatief, nul = gemiddelde): {len(i)} buurparen van banen sluiten "
                  f"op gemiddeld {np.sqrt(np.mean(rest ** 2)) * 100:.1f} cm na aan; gemeenschappelijke pitchfout "
                  f"{math.degrees(b[nseg]):+.2f} graad."
                  + (f" ({sprongen} gat(en) in de log overgeslagen)" if sprongen else ""))


def bereken_raster(punten, lat0, lon0, geschat, cel=0.5):
    """Hoogte en echte helling (%) op een raster van 'cel' meter, alleen tot 2 m van gereden punten."""
    met_h = [p for p in punten if p["hoogte"] is not None]
    if len(met_h) < 10:
        return None
    try:
        from scipy.interpolate import griddata
        from scipy.spatial import cKDTree
    except ImportError:
        return None
    x = np.array([xy(p["lat"], p["lon"], lat0, lon0)[0] for p in met_h])
    y = np.array([xy(p["lat"], p["lon"], lat0, lon0)[1] for p in met_h])
    h = np.array([p["hoogte"] for p in met_h])
    gx, gy = np.meshgrid(np.arange(x.min(), x.max() + cel, cel), np.arange(y.min(), y.max() + cel, cel))
    raster = griddata((x, y), h, (gx, gy), method="linear")
    afstand, _ = cKDTree(np.c_[x, y]).query(np.c_[gx.ravel(), gy.ravel()])
    raster[afstand.reshape(gx.shape) > 2.0] = np.nan
    gladde = raster
    if geschat:
        # Teruggerekende hoogte heeft een paar cm sprong tussen banen van ~4 m; zonder
        # uitsmeren leest de gradient dat als dwarshelling van enkele procenten.
        from scipy.ndimage import gaussian_filter
        geldig = np.isfinite(raster)
        sigma = 4.0 / cel
        teller = gaussian_filter(np.where(geldig, raster, 0.0), sigma)
        noemer = gaussian_filter(geldig.astype(float), sigma)
        gladde = np.where(geldig, teller / np.maximum(noemer, 1e-6), np.nan)
    dy, dx = np.gradient(gladde, cel)
    helling = np.hypot(dx, dy) * 100.0
    return {"gx": gx, "gy": gy, "hoogte": raster, "helling": helling}


def terrein_figuur(punten, lat0, lon0, rast, geschat, titel, uit_pad):
    """Hoogte met hoogtelijnen, helling en ruwheid over de luchtfoto."""
    alle_x = [xy(p["lat"], p["lon"], lat0, lon0)[0] for p in punten]
    alle_y = [xy(p["lat"], p["lon"], lat0, lon0)[1] for p in punten]
    marge = 4.0
    xmin, xmax = min(alle_x) - marge, max(alle_x) + marge
    ymin, ymax = min(alle_y) - marge, max(alle_y) + marge

    # Breed veld: panelen onder elkaar, anders naast elkaar.
    if (xmax - xmin) > 1.6 * (ymax - ymin):
        paneel_h = max(3.0, 13.0 * (ymax - ymin) / (xmax - xmin) + 1.0)
        fig, assen = plt.subplots(3, 1, figsize=(15, 3 * paneel_h + 1))
    else:
        fig, assen = plt.subplots(1, 3, figsize=(20, 7))
    foto = luchtfoto_onder(assen, lat0, lon0, xmin, xmax, ymin, ymax)
    fig.suptitle(f"Terrein: {titel}" + ("  (luchtfoto: Esri World Imagery)" if foto else ""))

    for ax in assen:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal")
        ax.set_xlabel("oost (m)")
        ax.set_ylabel("noord (m)")

    def punten_laag(ax, sleutel, cmap, label, absoluut=False):
        pp = [p for p in punten if p[sleutel] is not None]
        if not pp:
            return
        waarden = [abs(p[sleutel]) if absoluut else p[sleutel] for p in pp]
        sc = ax.scatter([xy(p["lat"], p["lon"], lat0, lon0)[0] for p in pp],
                        [xy(p["lat"], p["lon"], lat0, lon0)[1] for p in pp],
                        c=waarden, s=9, cmap=cmap, edgecolors="none", zorder=2,
                        vmin=kwantiel(waarden, 0.02), vmax=kwantiel(waarden, 0.98))
        fig.colorbar(sc, ax=ax, label=label, shrink=0.9)

    # 1. Hoogte: ingekleurd raster met hoogtelijnen, half doorzichtig over de foto.
    ax = assen[0]
    if rast is not None:
        vlak = ax.contourf(rast["gx"], rast["gy"], rast["hoogte"], levels=20, cmap="terrain", alpha=0.6, zorder=1)
        lijnen = ax.contour(rast["gx"], rast["gy"], rast["hoogte"], levels=10, colors="k", linewidths=0.6, zorder=2)
        ax.clabel(lijnen, fmt="%.2f", fontsize=7)
        fig.colorbar(vlak, ax=ax, label="hoogte (m)", shrink=0.9)
        ax.set_title(("Hoogte, GESCHAT uit de pitch (relatief, 0 = gemiddelde) met hoogtelijnen" if geschat
                      else "Hoogte van de grond (RTK) met hoogtelijnen"))
    elif any(p["hoogte"] is not None for p in punten):
        punten_laag(ax, "hoogte", "terrain", "hoogte (m)")
        ax.set_title("Hoogte, GESCHAT uit de pitch (relatief)" if geschat else "Hoogte van de grond (RTK)")
    else:
        ax.plot(alle_x, alle_y, "w.", ms=1, alpha=0.6, zorder=2)
        ax.set_title("Hoogte: niet in deze log - wit = gereden pad")

    # 2. Helling: echte helling uit de hoogtekaart, anders de pitch in de rijrichting.
    ax = assen[1]
    if rast is not None and np.isfinite(rast["helling"]).sum() > 20:
        hh = rast["helling"]
        vlak = ax.contourf(rast["gx"], rast["gy"], np.clip(hh, 0, np.nanpercentile(hh, 98)),
                           levels=15, cmap="RdYlGn_r", alpha=0.6, zorder=1)
        fig.colorbar(vlak, ax=ax, label="helling (%)", shrink=0.9)
        ax.set_title("Helling uit de hoogtekaart (steilste richting)" + (", uitgesmeerd over ~4 m" if geschat else ""))
    else:
        punten_laag(ax, "pitch", "RdYlGn_r", "|pitch| (graad)", absoluut=True)
        ax.set_title("Helling in de rijrichting (pitch)")

    # 3. Ruwheid
    ax = assen[2]
    punten_laag(ax, "ruwheid", "RdYlGn_r", "ruwheid (graad)")
    ax.set_title("Ruwheid (spreiding pitch over ~1 s)")

    fig.tight_layout()
    return bewaar(fig, uit_pad, 150)


def terrein(raw_rows, jpg_pad, titel):
    """Hoogte-, helling- en ruwheidskaart plus de montage-scheefstand van de antennes."""
    punten = lees_terrein(raw_rows)
    if len(punten) < 10:
        raise Overgeslagen("te weinig punten met RTK fixed")
    if all(p["pitch"] is None and p["hoogte"] is None for p in punten):
        raise Overgeslagen("geen pitch of hoogte in deze log")
    montage = vul_aan(punten)
    geschat, melding = False, None
    if not any(p["hoogte"] is not None for p in punten):
        geschat, melding = hoogte_uit_pitch(punten)
    lat0 = sum(p["lat"] for p in punten) / len(punten)
    lon0 = sum(p["lon"] for p in punten) / len(punten)
    rast = bereken_raster(punten, lat0, lon0, geschat)
    terrein_figuur(punten, lat0, lon0, rast, geschat, titel, jpg_pad)

    xs, ys = zip(*[xy(p["lat"], p["lon"], lat0, lon0) for p in punten])
    hoogte = [p["hoogte"] for p in punten if p["hoogte"] is not None]
    pitch = [abs(p["pitch"]) for p in punten if p["pitch"] is not None]
    ruw = [p["ruwheid"] for p in punten if p["ruwheid"] is not None]
    helling = (rast["helling"][np.isfinite(rast["helling"])] if rast is not None else np.array([]))

    kv, kaarten, bev = [], [], []
    kv.append(("kv", "Punten", f"{len(punten)} (een per 25 cm met RTK fixed), gebied ca. "
                                f"{max(xs) - min(xs):.0f} x {max(ys) - min(ys):.0f} m", False))
    if hoogte:
        kv.append(("kv", "Hoogte van de grond" + (" (geschat, relatief)" if geschat else ""),
                   f"{min(hoogte):.2f} .. {max(hoogte):.2f} m (verschil {max(hoogte) - min(hoogte):.2f} m)", False))
        kaarten.append(("Hoogteverschil" + (" (geschat)" if geschat else ""), f"{max(hoogte) - min(hoogte):.2f} m",
                        "relatief, uit de pitch" if geschat else f"{min(hoogte):.2f} .. {max(hoogte):.2f} m"))
    if pitch:
        kv.append(("kv", "Helling rijrichting |pitch|",
                   f"mediaan {kwantiel(pitch, .5):.1f}, P90 {kwantiel(pitch, .9):.1f}, max {max(pitch):.1f}° "
                   f"({math.tan(math.radians(max(pitch))) * 100:.0f} %)", False))
    if helling.size > 20:
        kv.append(("kv", "Helling uit hoogtekaart", f"mediaan {np.percentile(helling, 50):.1f} %, "
                                                   f"P95 {np.percentile(helling, 95):.1f} %, max {helling.max():.1f} %", False))
        kaarten.append(("Helling, P95", f"{np.percentile(helling, 95):.1f} %", "steilste richting, uit de hoogtekaart"))
    elif pitch:
        kaarten.append(("Helling rijrichting, P90", f"{kwantiel(pitch, .9):.1f}°", f"max {max(pitch):.1f}°"))
    if ruw:
        kv.append(("kv", "Ruwheid", f"mediaan {kwantiel(ruw, .5):.2f}, P90 {kwantiel(ruw, .9):.2f}, "
                                    f"max {max(ruw):.2f}°", False))
    if montage is not None:
        kv.append(("kv", "Montage-scheefstand", f"{montage:+.2f}° uit heen-en-terug rijden (in de config: "
                                                "gnss.pitch_offset_deg plus deze waarde; staat hij goed, dan ~0)",
                   abs(montage) > 0.3))
        if abs(montage) > 0.3:
            bev.append(("info", f"De antennemontage staat {montage:+.2f}° scheef ten opzichte van gnss.pitch_offset_deg. "
                                "Tel deze waarde op bij pitch_offset_deg in de config."))
    else:
        kv.append(("kv", "Montage-scheefstand", "niet te bepalen (niet heen en terug over dezelfde banen gereden)", False))
    if melding:
        kv.append(("note", melding, "", False))
    if geschat:
        bev.append(("info", "Deze log heeft geen RTK-hoogte (Hoogte_Grond_m): de hoogtekaart is teruggerekend uit de "
                            "pitch, relatief en geschat."))

    blokken = [
        ("p", "De pitch meet de helling alleen in de rijrichting; de hoogtekaart geeft de echte steilheid in de "
              "steilste richting en wordt beter naarmate er meer banen naast elkaar gereden zijn."),
        ("kv", kv),
        ("beeld", jpg_pad, "Hoogte met hoogtelijnen, helling en ruwheid (spreiding van de pitch over ongeveer een "
                           "seconde)."),
    ]
    return {"punten": punten, "lat0": lat0, "lon0": lon0, "rast": rast, "geschat": geschat,
            "kv": kv, "kaarten": kaarten, "bevindingen": bev, "blokken": blokken, "jpg": jpg_pad}


# ==========================================
# INTERACTIEVE KAART (folium): route en terrein op de luchtfoto
# ==========================================

def interactieve_kaart(tel, ter):
    """Een Leaflet-kaart met de route en de terreinlagen, als complete HTML-pagina (tekst)."""
    try:
        import folium
        import branca.colormap as cm
    except ImportError:
        raise Overgeslagen("folium niet geinstalleerd (pip install folium)")
    pp = [r for r in tel["rows"] if r["lat"] != 0.0 and r["lon"] != 0.0] if tel else []
    lats = [r["lat"] for r in pp] or ([p["lat"] for p in ter["punten"]] if ter else [])
    lons = [r["lon"] for r in pp] or ([p["lon"] for p in ter["punten"]] if ter else [])
    if not lats:
        raise Overgeslagen("geen GPS-posities")

    m = folium.Map(location=[avg(lats), avg(lons)], zoom_start=19, max_zoom=22, tiles=None)
    folium.TileLayer(tiles=TEGEL_URL, attr="Esri World Imagery", name="Satelliet",
                     max_zoom=22, max_native_zoom=19).add_to(m)
    # Niet OpenStreetMap: de OSM-servers blokkeren aanvragen van scripts (403).
    folium.TileLayer(tiles=STRAAT_URL, attr="Esri World Street Map", name="Kaart",
                     max_zoom=22, max_native_zoom=19, show=False).add_to(m)

    if ter and ter["rast"] is not None:
        rast = ter["rast"]
        lat_z, lon_w = _meters_naar_latlon(rast["gx"].min(), rast["gy"].min(), ter["lat0"], ter["lon0"])
        lat_n, lon_o = _meters_naar_latlon(rast["gx"].max(), rast["gy"].max(), ter["lat0"], ter["lon0"])
        for naam, veld, kaart in ((("Hoogtekaart (geschat uit pitch)" if ter["geschat"] else "Hoogtekaart"), "hoogte", "terrain"),
                                  ("Hellingkaart (%)", "helling", "RdYlGn_r")):
            v = rast[veld]
            lo, hi = np.nanpercentile(v, 2), np.nanpercentile(v, 98)
            norm = np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)
            rgba = (matplotlib.colormaps[kaart](np.nan_to_num(norm)) * 255).astype(np.uint8)
            rgba[..., 3] = np.where(np.isfinite(v), 170, 0)
            folium.raster_layers.ImageOverlay(image=rgba[::-1], bounds=[[lat_z, lon_w], [lat_n, lon_o]],
                                              name=naam, show=False).add_to(m)

    if pp:
        # Route: banen dik, kopakker dun, onderbroken bij gaten in de log.
        route = folium.FeatureGroup(name="Gereden route", show=True)
        stuk = [pp[0]]
        for vorige, r in zip(pp, pp[1:]):
            gat = haversine_distance(vorige["lat"], vorige["lon"], r["lat"], r["lon"]) > 5.0
            if r["modus"] != stuk[-1]["modus"] or gat:
                if len(stuk) > 1:
                    baan = stuk[0]["modus"] != "TURNING"
                    folium.PolyLine([(q["lat"], q["lon"]) for q in stuk], color="#2196F3" if baan else "#FF9800",
                                    weight=4 if baan else 2, opacity=0.85,
                                    tooltip=f"baan {stuk[0]['idx']}" if baan else "kopakkerbocht").add_to(route)
                stuk = [stuk[-1]] if not gat else []
            stuk.append(r)
        if len(stuk) > 1:
            baan = stuk[0]["modus"] != "TURNING"
            folium.PolyLine([(q["lat"], q["lon"]) for q in stuk], color="#2196F3" if baan else "#FF9800",
                            weight=4 if baan else 2, opacity=0.85).add_to(route)
        route.add_to(m)

        # Meetpunten met alle waarden onder de muis.
        hover = folium.FeatureGroup(name="Meetpunten (hover)", show=True)
        for r in pp[::max(1, len(pp) // 600)]:
            afw = abs(xte_waarde(r))
            if r["modus"] == "TURNING":
                kleur, afw_txt = "#9e9e9e", "-"
            else:
                kleur = "green" if afw < 0.05 else ("orange" if afw < 0.10 else "red")
                afw_txt = f"{xte_waarde(r) * 100:+.1f} cm"
            tijd = r["t"].strftime("%H:%M:%S") if r["t"] else "-"
            tip = (f'<div style="font:12px sans-serif;min-width:210px"><b>{tijd}</b> &middot; {r["modus"]} &middot; '
                   f'baan {r["idx"]}<table style="width:100%">'
                   f'<tr><td>Snelheid doel / echt</td><td align="right">{r["doel_kmh"]:.2f} / {r["echt_kmh"]:.2f} km/h</td></tr>'
                   f'<tr><td>Afwijking van de lijn</td><td align="right">{afw_txt}</td></tr>'
                   f'<tr><td>Stuurhoek</td><td align="right">{r["stuur"]:.1f}&deg;</td></tr>'
                   f'<tr><td>Koers echt / doel</td><td align="right">{r["h_echt"]:.1f} / {r["h_doel"]:.1f}&deg;</td></tr>'
                   f'<tr><td>Fix (HDOP)</td><td align="right">{r["fix"]} ({r["hdop"]:.2f})</td></tr></table></div>')
            folium.CircleMarker([r["lat"], r["lon"]], radius=4, color="black", weight=1, fill=True,
                                fill_color=kleur, fill_opacity=0.9, tooltip=tip).add_to(hover)
        hover.add_to(m)
        folium.Marker([pp[0]["lat"], pp[0]["lon"]], tooltip="Start",
                      icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker([pp[-1]["lat"], pp[-1]["lon"]], tooltip="Eind",
                      icon=folium.Icon(color="red", icon="stop")).add_to(m)

    if ter:
        punten = ter["punten"]

        def laag(naam, sleutel, kleuren, absoluut=False, eenheid=""):
            waarden = [abs(p[sleutel]) if absoluut else p[sleutel] for p in punten if p[sleutel] is not None]
            if not waarden:
                return
            lo, hi = kwantiel(waarden, 0.02), kwantiel(waarden, 0.98)
            if hi <= lo:
                hi = lo + 1e-3
            schaal = cm.LinearColormap(kleuren, vmin=lo, vmax=hi, caption=f"{naam} {eenheid}")
            groep = folium.FeatureGroup(name=naam, show=False)
            for p in punten[::2]:                    # een per 50 cm: scheelt de helft van de HTML
                v = p[sleutel]
                if v is None:
                    continue
                v = abs(v) if absoluut else v
                folium.CircleMarker([p["lat"], p["lon"]], radius=3, weight=0, fill=True, fill_opacity=0.85,
                                    fill_color=schaal(min(max(v, lo), hi)),
                                    tooltip=f"{naam}: {v:.2f} {eenheid}").add_to(groep)
            groep.add_to(m)
            schaal.add_to(m)

        laag("Hoogte geschat (punten)" if ter["geschat"] else "Hoogte (punten)", "hoogte",
             ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"], eenheid="m")
        laag("Helling rijrichting", "pitch", ["#1a9641", "#ffffbf", "#d7191c"], absoluut=True, eenheid="graad")
        laag("Ruwheid", "ruwheid", ["#1a9641", "#ffffbf", "#d7191c"], eenheid="graad")

    folium.LayerControl(collapsed=False).add_to(m)
    grenzen = [[min(lats), min(lons)], [max(lats), max(lons)]]
    m.fit_bounds(grenzen)
    # In het HTML-rapport zit de kaart in een iframe, en die kan starten voordat het frame
    # zijn maat heeft (dan staat heel Nederland in beeld): na het laden opnieuw passend maken.
    kaart = m.get_name()
    m.get_root().script.add_child(folium.Element(
        f"window.addEventListener('load', function () {{ setTimeout(function () {{ {kaart}.invalidateSize(); "
        f"{kaart}.fitBounds({json.dumps(grenzen)}); }}, 300); }});"))
    return m.get_root().render()


# ==========================================
# RAPPORT: een inhoud, drie vormen (tekst, HTML, PDF)
# ==========================================
# Het rapport is een lijst hoofdstukken met blokken:
#   ("p", tekst)                        uitleg
#   ("h3", tekst)                       tussenkop
#   ("kv", [(soort, naam, waarde, waarschuwing)])   soort = kv / sub / note
#   ("tabel", kop, rijen, waarschuwingsrijen)
#   ("beeld", pad, onderschrift)
#   ("dl", [(begrip, uitleg)])
#   ("interactief",)                    de folium-kaart (alleen in de HTML)

TEL_KPI = [
    ("RIT OVERZICHT", "Rijtijd", "Rijtijd"),
    ("RIT OVERZICHT", "Afstand gereden", "Afstand"),
    ("LIJNVOLGING (cross-track error)", "XTE gemiddeld", "Afwijking van de lijn, gem."),
    ("LIJNVOLGING (cross-track error)", "XTE P95", "Afwijking van de lijn, P95"),
    ("KOERS & ORIENTATIE", "Koers-bias", "Koers-bias"),
    ("SNELHEID & EFFICIENTIE", "Tijdens de baan", "Snelheid op de baan"),
    ("GPS & SYSTEEM", "RTK Fixed (4)", "RTK fixed"),
]
TEL_KPI_ACCU = [            # alleen als het onderdeel aandrijving er niet is
    ("ACCU & WIELEN", "Lading (schatting)", "Lading"),
    ("ACCU & WIELEN", "Vermogen", "Vermogen"),
    ("ACCU & WIELEN", "Energie deze rit", "Energie"),
]
AANDRIJVING_KPI = ("Gemiddeld vermogen", "Verbruik", "Accuspanning", "Lading (schatting)", "Gem. trekkracht per wiel")

HINTS = {"Koers-bias": " Blijft dit in beide rijrichtingen even groot terwijl de afwijking van de lijn "
                       "klein is, dan meet de dubbele antenne een vaste koersoffset: stel "
                       "gnss.heading_offset_deg bij in de config."}


def is_waarschuwing(key, waarde):
    return (key.startswith("LET OP") or "SCHEEF" in waarde or "<<" in waarde
            or key in ("Scheef opgepakt", "Doorgeschoten")
            or (key == "Koers-bias" and ("LINKS" in waarde or "RECHTS" in waarde)))


def tabel_banen(banen):
    rijen, warn = [], set()
    for i, b in enumerate(banen, 1):
        settle = f"{b['settle_s']:.1f} s" if b["settle_s"] is not None else "nooit"
        if b["oppakken"] > 0.5:
            warn.add(i - 1)
        rijen.append([str(i), str(b["baan"]), f"{b['duur']:.1f} s", f"{b['lengte']:.1f} m",
                      f"{b['oppakken']:.2f} m", f"{b['uitslag']:.2f} m", settle,
                      f"{b['gem'] * 100:.1f} / {b['max'] * 100:.1f} cm"])
    kop = ["Nr", "Baan", "Duur", "Lengte", "Oppakken", "Uitslag", "Op de lijn na", "Daarna gem / max"]
    return ("tabel", kop, rijen, warn)


def tabel_bochten(bochten):
    rijen, warn = [], set()
    for i, t in enumerate(bochten, 1):
        van = "start" if t["van"] is None else str(t["van"])
        naar = "eind" if t["naar"] is None else str(t["naar"])
        opm = "TIMEOUT" if t["timeout"] else ("naast de lijn begonnen" if t["afstand_pad"] > 1.0 else "")
        if opm:
            warn.add(i - 1)
        rijen.append([str(i), f"{van} → {naar}", f"{t['duur']:.1f} s", f"{t['gem']:.1f} / {t['max']:.1f}°",
                      f"{t['afstand_pad']:.2f} m", opm])
    kop = ["Nr", "Van → naar", "Duur", "Koersfout gem / max", "Afstand tot pad", "Opmerking"]
    return ("tabel", kop, rijen, warn)


def sectie_blokken(sec, banen, bochten):
    """Een sectie van het tekstrapport als blokken: uitleg, eventueel de tabel, dan de waarden."""
    blokken = []
    if sec["sub"]:
        blokken.append(("p", sec["sub"][:1].upper() + sec["sub"][1:] + "."))
    regels = sec["regels"]
    i = 0
    voor = []
    while i < len(regels) and regels[i][0] == "note":
        voor.append(regels[i][1])
        i += 1
    if voor:
        blokken.append(("p", " ".join(voor)))
    if sec["titel"] == "PER BAAN" and banen:
        blokken.append(tabel_banen(banen))
    if sec["titel"] == "PER KOPAKKERBOCHT" and bochten:
        blokken.append(tabel_bochten(bochten))
    kv = []
    for soort, key, waarde in regels[i:]:
        if soort == "note" and kv and kv[-1][0] == "note":
            kv[-1] = ("note", kv[-1][1] + " " + key, "", False)        # afgebroken uitlegregels weer aan elkaar
        else:
            kv.append((soort, key, waarde, soort != "note" and is_waarschuwing(key, waarde)))
    if kv:
        blokken.append(("kv", kv))
    return blokken


def rit_datum(naam):
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", naam)
    if not m:
        return ""
    j, mnd, d, u, mi, _ = (int(g) for g in m.groups())
    return f"{d} {MAANDEN[mnd - 1]} {j}, {u:02d}:{mi:02d}"


def bouw_rapport(naam, tel, aan, ter, beelden, meldingen):
    secties = parse_rapport(tel["tekst"]) if tel else []
    waarden = {(s["titel"], r[1]): r[2] for s in secties for r in s["regels"] if r[0] == "kv"}

    kaarten = [(label, waarden[(s, k)], "") for s, k, label in TEL_KPI + ([] if aan else TEL_KPI_ACCU)
               if (s, k) in waarden]
    if aan:
        kaarten += [k for k in aan["kaarten"] if k[0] in AANDRIJVING_KPI]
    if ter:
        kaarten += ter["kaarten"]

    aandacht = [("letop", f"{key}: {waarde}.{HINTS.get(key, '')}") for s in secties for soort, key, waarde in s["regels"]
                if soort == "kv" and is_waarschuwing(key, waarde)]
    aandacht += (aan["bevindingen"] if aan else []) + (ter["bevindingen"] if ter else []) + meldingen
    volgorde = {"letop": 0, "info": 1, "goed": 2}
    aandacht.sort(key=lambda a: volgorde.get(a[0], 1))

    hoofdstukken = []
    route = [("interactief",)]
    if "kaart" in beelden:
        route.append(("beeld", beelden["kaart"], "Op de baan gekleurd naar de afwijking van de lijn; de dunne lijn is "
                                                 "het hele gereden pad, ook de kopakker."))
    hoofdstukken.append({"titel": "Route op de luchtfoto", "blokken": route})
    if "verloop" in beelden:
        hoofdstukken.append({"titel": "Verloop van de rit", "blokken": [
            ("beeld", beelden["verloop"], "Grijs = kopakkerbocht.")]})
    instellingen = None
    for s in secties:
        h = {"titel": s["titel"][:1] + s["titel"][1:].lower(), "blokken": sectie_blokken(s, tel["banen"], tel["bochten"])}
        if s["titel"].startswith("INSTELLINGEN"):
            instellingen = h
        else:
            hoofdstukken.append(h)
    if aan:
        hoofdstukken.append({"titel": "Aandrijving en accu", "blokken": aan["blokken"]})
    if ter:
        hoofdstukken.append({"titel": "Terrein: hoogte, helling en ruwheid", "blokken": ter["blokken"]})
    if instellingen:
        hoofdstukken.append(instellingen)
    for i, h in enumerate(hoofdstukken, 1):
        h["id"] = f"h{i}"
    return {"naam": naam, "datum": rit_datum(naam), "kaarten": kaarten, "aandacht": aandacht,
            "hoofdstukken": hoofdstukken}


# ---------- tekst ----------

def tekst_tabel(kop, rijen):
    breed = [max(len(str(c)) for c in kol) for kol in zip(kop, *rijen)]
    return ["  " + "  ".join(str(c).ljust(b) if i == 0 else str(c).rjust(b)
                             for i, (c, b) in enumerate(zip(r, breed))) for r in [kop] + rijen]


def schrijf_tekst(rap, tel, pad):
    """Het tekstrapport: de telemetrie zoals altijd, met aandrijving en terrein erachter."""
    regels = ["=" * 50, f"RITRAPPORT: {rap['naam']}" + (f"  ({rap['datum']})" if rap["datum"] else ""), "=" * 50, ""]
    if tel:
        regels += [tel["tekst"], ""]
    for h in rap["hoofdstukken"]:
        if not (h["titel"].startswith("Aandrijving") or h["titel"].startswith("Terrein")):
            continue
        regels.append(f"[{h['titel'].upper()}]")
        for i, b in enumerate(h["blokken"]):
            if b[0] == "h3":
                if i + 1 < len(h["blokken"]) and h["blokken"][i + 1][0] in ("kv", "tabel"):   # geen kop boven een plaatje
                    regels.append(f"  {b[1]}:")
            elif b[0] == "kv":
                for soort, key, waarde, _ in b[1]:
                    regels.append(f"  {key}" if soort == "note" else f"- {key:<18s}: {waarde}")
            elif b[0] == "tabel":
                regels += tekst_tabel(b[1], b[2])
        regels.append("")
    regels.append("[AANDACHTSPUNTEN]")
    regels += [f"- {soort.upper():<6s}: {tekst}" for soort, tekst in rap["aandacht"]]
    regels += ["", "Analyseer dit en geef aanbevelingen.", "=" * 50]
    with open(pad, "w", encoding="utf-8") as f:
        f.write("\n".join(regels))
    return pad


# ---------- HTML ----------

HTML_CSS = """
:root{--bg:#f6f7f4;--kaart:#fff;--tekst:#1c2321;--zacht:#5b6763;--lijn:#dde2de;--goed:#2d7a46;--let:#b4531f;--info:#2f5d8a}
@media(prefers-color-scheme:dark){:root{--bg:#14181a;--kaart:#1d2326;--tekst:#e6ebe8;--zacht:#9aa6a1;--lijn:#2d3639;--goed:#5fbf82;--let:#e8905a;--info:#78a9d8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tekst);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:1.6rem;margin:0 0 2px} h2{font-size:1.15rem;margin:0 0 8px} h3{font-size:.95rem;margin:18px 0 6px}
.sub{color:var(--zacht);margin-bottom:18px;overflow-wrap:anywhere}
.kaarten{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:14px}
.kaart{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;padding:12px 14px}
.kaart .k{color:var(--zacht);font-size:.8rem} .kaart .g{font-size:1.25rem;font-weight:650;margin:2px 0;overflow-wrap:anywhere}
.kaart .s{color:var(--zacht);font-size:.8rem}
nav{display:flex;flex-wrap:wrap;gap:4px 14px;margin:0 0 14px;font-size:.85rem}
nav a{color:var(--info);text-decoration:none} nav a:hover{text-decoration:underline}
section{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;padding:14px 16px;margin-bottom:14px}
p.intro{color:var(--zacht);font-size:.86rem;margin:4px 0 8px}
.tw{overflow-x:auto;margin:8px 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--lijn)}
th:first-child,td:first-child{text-align:left} th{font-size:.78rem;color:var(--zacht);font-weight:600}
tr:last-child td{border-bottom:0}
table.kv td:first-child{color:var(--zacht);width:1%;padding-right:20px}
table.kv td:last-child{text-align:left;white-space:normal}
tr.sub td:first-child{padding-left:28px}
tr.warn td{background:rgba(180,83,31,.12)} tr.warn td:first-child{color:var(--let);font-weight:600}
td.noot{text-align:left;color:var(--zacht);font-size:.82rem;white-space:normal}
ul.aandacht{list-style:none;padding:0;margin:0}
ul.aandacht li{border-left:4px solid var(--info);background:rgba(47,93,138,.07);border-radius:6px;padding:8px 12px;margin-bottom:6px}
ul.aandacht li.letop{border-left-color:var(--let);background:rgba(180,83,31,.08)}
ul.aandacht li.goed{border-left-color:var(--goed);background:rgba(45,122,70,.08)}
ul.aandacht b{text-transform:uppercase;font-size:.72rem;letter-spacing:.05em;margin-right:6px}
li.letop b{color:var(--let)} li.info b{color:var(--info)} li.goed b{color:var(--goed)}
img{width:100%;height:auto;border-radius:8px;border:1px solid var(--lijn);background:#fff;display:block}
iframe.kaart{width:100%;height:620px;border:1px solid var(--lijn);border-radius:8px;margin-bottom:10px;background:#ddd}
dt{font-weight:600;margin-top:10px} dd{margin:2px 0 0;color:var(--zacht)}
@media print{body{background:#fff;color:#000}section,.kaart{break-inside:avoid}main{padding:0}iframe.kaart,nav{display:none}}
"""
LABEL = {"letop": "let op", "info": "info", "goed": "goed"}


def jpg_base64(pad):
    with open(pad, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def schrijf_html(rap, kaart_html, pad):
    """Zelfstandige HTML: plaatjes en de interactieve kaart zitten erin."""
    e = html.escape

    def blok(b):
        soort = b[0]
        if soort == "p":
            return f'<p class="intro">{e(b[1])}</p>'
        if soort == "h3":
            return f"<h3>{e(b[1])}</h3>"
        if soort == "kv":
            rijen = ""
            for s, key, waarde, warn in b[1]:
                if s == "note":
                    rijen += f'<tr><td class="noot" colspan="2">{e(key)}</td></tr>'
                    continue
                klas = " ".join(k for k, aan in (("sub", s == "sub"), ("warn", warn)) if aan)
                rijen += f'<tr class="{klas}"><td>{e(key)}</td><td>{e(waarde)}</td></tr>'
            return f'<div class="tw"><table class="kv"><tbody>{rijen}</tbody></table></div>'
        if soort == "tabel":
            _, kop, rijen, warn = b
            th = "".join(f"<th>{e(k)}</th>" for k in kop)
            tr = "".join(f'<tr{" class=warn" if i in warn else ""}>' + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>"
                         for i, r in enumerate(rijen))
            return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
        if soort == "beeld":
            onder = f'<p class="intro">{e(b[2])}</p>' if b[2] else ""
            return f'<img alt="{e(b[2] or "grafiek")}" src="{jpg_base64(b[1])}">{onder}'
        if soort == "dl":
            return "<dl>" + "".join(f"<dt>{e(t)}</dt><dd>{e(u)}</dd>" for t, u in b[1]) + "</dl>"
        if soort == "interactief" and kaart_html:
            return (f'<iframe class="kaart" title="Interactieve kaart" srcdoc="{e(kaart_html, quote=True)}"></iframe>'
                    '<p class="intro">Interactief: lagen rechtsboven aan- en uitklikken (route, meetpunten, hoogte, '
                    'helling, ruwheid). Heeft internet nodig voor de luchtfoto.</p>')
        return ""

    kaarten = "".join(f'<div class="kaart"><div class="k">{e(k)}</div><div class="g">{e(g)}</div>'
                      + (f'<div class="s">{e(s)}</div>' if s else "") + "</div>" for k, g, s in rap["kaarten"])
    aandacht = "".join(f'<li class="{s}"><b>{LABEL.get(s, s)}</b>{e(t)}</li>' for s, t in rap["aandacht"])
    nav = "".join(f'<a href="#{h["id"]}">{e(h["titel"])}</a>' for h in rap["hoofdstukken"])
    delen = "".join(f'<section id="{h["id"]}"><h2>{e(h["titel"])}</h2>' + "".join(blok(b) for b in h["blokken"])
                    + "</section>" for h in rap["hoofdstukken"])
    sub = e(rap["naam"]) + (f" &middot; {e(rap['datum'])}" if rap["datum"] else "")
    pagina = (f'<!doctype html><html lang="nl"><head><meta charset="utf-8">'
              f'<meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<title>Ritrapport {e(rap["naam"])}</title><style>{HTML_CSS}</style></head><body><main>'
              f'<h1>Ritrapport</h1><div class="sub">{sub}</div>'
              f'<div class="kaarten">{kaarten}</div>'
              f'<section><h2>Aandachtspunten</h2><ul class="aandacht">{aandacht}</ul></section>'
              f'<nav>{nav}</nav>{delen}</main></body></html>')
    with open(pad, "w", encoding="utf-8") as f:
        f.write(pagina)
    return pad


# ---------- PDF ----------

def schrijf_pdf(rap, pad):
    """Het rapport als A4-PDF (reportlab), met DejaVu Sans uit matplotlib zodat °, →, Ω en λ goed staan."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        raise Overgeslagen("reportlab niet geinstalleerd (pip install reportlab)")
    from xml.sax.saxutils import escape as x
    from PIL import Image as PILImage

    ttf = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    try:
        pdfmetrics.registerFont(TTFont("Rapport", os.path.join(ttf, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("Rapport-Vet", os.path.join(ttf, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("Rapport", normal="Rapport", bold="Rapport-Vet",
                                      italic="Rapport", boldItalic="Rapport-Vet")
        gewoon, vet = "Rapport", "Rapport-Vet"
    except Exception:
        gewoon, vet = "Helvetica", "Helvetica-Bold"

    tekst, zacht, lijn = colors.HexColor("#1c2321"), colors.HexColor("#5b6763"), colors.HexColor("#dde2de")
    kleur_hex = {"letop": "#b4531f", "info": "#2f5d8a", "goed": "#2d7a46"}
    kleur = {k: colors.HexColor(v) for k, v in kleur_hex.items()}
    tint = {"letop": colors.HexColor("#f6e9e1"), "info": colors.HexColor("#e7edf3"), "goed": colors.HexColor("#e5efe8")}
    st = {
        "titel": ParagraphStyle("titel", fontName=vet, fontSize=20, leading=24, textColor=tekst),
        "sub": ParagraphStyle("sub", fontName=gewoon, fontSize=9, leading=12, textColor=zacht, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName=vet, fontSize=13, leading=16, textColor=tekst, spaceBefore=12,
                             spaceAfter=5, keepWithNext=1),
        "h3": ParagraphStyle("h3", fontName=vet, fontSize=10, leading=13, textColor=tekst, spaceBefore=8,
                             spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", fontName=gewoon, fontSize=8, leading=10.5, textColor=zacht, spaceAfter=4),
        "cel": ParagraphStyle("cel", fontName=gewoon, fontSize=7.5, leading=9.5, textColor=tekst),
        "cel_r": ParagraphStyle("cel_r", fontName=gewoon, fontSize=7.5, leading=9.5, textColor=tekst, alignment=TA_RIGHT),
        "kop": ParagraphStyle("kop", fontName=vet, fontSize=7, leading=9, textColor=zacht),
        "kop_r": ParagraphStyle("kop_r", fontName=vet, fontSize=7, leading=9, textColor=zacht, alignment=TA_RIGHT),
        "k": ParagraphStyle("k", fontName=gewoon, fontSize=7, leading=9, textColor=zacht),
        "g": ParagraphStyle("g", fontName=vet, fontSize=10.5, leading=13, textColor=tekst),
        "dt": ParagraphStyle("dt", fontName=vet, fontSize=8, leading=10.5, textColor=tekst, spaceBefore=4),
    }
    breedte = A4[0] - 30 * mm
    max_hoogte = A4[1] - 50 * mm

    def P(t, stijl):
        return Paragraph(x(str(t)), st[stijl])

    def tabel(kop, rijen, warn):
        data = [[P(k, "kop" if i == 0 else "kop_r") for i, k in enumerate(kop)]]
        data += [[P(c, "cel" if i == 0 else "cel_r") for i, c in enumerate(r)] for r in rijen]
        # Kolombreedte naar de langste tekst, met een minimum.
        lengte = [max(10, min(40, max(len(str(c)) for c in kol))) for kol in zip(kop, *rijen)]
        breedtes = [breedte * n / sum(lengte) for n in lengte]
        t = Table(data, colWidths=breedtes, repeatRows=1)
        stijl = [("LINEBELOW", (0, 0), (-1, -1), 0.4, lijn), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        stijl += [("BACKGROUND", (0, i + 1), (-1, i + 1), tint["letop"]) for i in warn]
        t.setStyle(TableStyle(stijl))
        return t

    def kv(rijen):
        data, stijl = [], [("LINEBELOW", (0, 0), (-1, -1), 0.4, lijn), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4)]
        for i, (soort, key, waarde, warn) in enumerate(rijen):
            if soort == "note":
                data.append([P(key, "p"), ""])
                stijl.append(("SPAN", (0, i), (1, i)))
                continue
            naam = ("    " if soort == "sub" else "") + key
            data.append([Paragraph(f'<font color="{"#b4531f" if warn else "#5b6763"}">{x(naam)}</font>', st["cel"]),
                         P(waarde, "cel")])
            if warn:
                stijl.append(("BACKGROUND", (0, i), (-1, i), tint["letop"]))
        t = Table(data, colWidths=[52 * mm, breedte - 52 * mm])
        t.setStyle(TableStyle(stijl))
        return t

    def beeld(pad_, onder):
        with PILImage.open(pad_) as im:
            w, h = im.size
        schaal = min(breedte / w, max_hoogte / h)
        uit = [Image(pad_, width=w * schaal, height=h * schaal)]
        if onder:
            uit.append(P(onder, "p"))
        return uit

    verhaal = [P("Ritrapport", "titel"), P(rap["naam"] + (f"  ·  {rap['datum']}" if rap["datum"] else ""), "sub")]

    # Kerngetallen in een raster van 4 kolommen.
    cellen = [[P(k, "k"), P(g, "g")] + ([P(s, "k")] if s else []) for k, g, s in rap["kaarten"]]
    if cellen:
        cellen += [""] * (-len(cellen) % 4)
        rijen = [cellen[i:i + 4] for i in range(0, len(cellen), 4)]
        t = Table(rijen, colWidths=[breedte / 4] * 4)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, lijn), ("INNERGRID", (0, 0), (-1, -1), 0.4, lijn),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
        verhaal.append(t)

    verhaal.append(P("Aandachtspunten", "h2"))
    for soort, t_ in rap["aandacht"]:
        k = kleur.get(soort, kleur["info"])
        cel = Paragraph(f'<font name="{vet}" color="{kleur_hex.get(soort, kleur_hex["info"])}" size="6.5">'
                        f'{LABEL.get(soort, soort).upper()}</font>&nbsp;&nbsp;{x(t_)}', st["cel"])
        t = Table([[cel]], colWidths=[breedte])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), tint.get(soort, tint["info"])),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, k), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        verhaal += [t, Spacer(1, 3)]

    for h in rap["hoofdstukken"]:
        verhaal.append(P(h["titel"], "h2"))
        for b in h["blokken"]:
            soort = b[0]
            if soort == "p":
                verhaal.append(P(b[1], "p"))
            elif soort == "h3":
                verhaal.append(P(b[1], "h3"))
            elif soort == "kv":
                verhaal.append(kv(b[1]))
            elif soort == "tabel" and b[2]:
                verhaal.append(tabel(b[1], b[2], b[3]))
            elif soort == "beeld":
                verhaal += beeld(b[1], b[2])
            elif soort == "dl":
                for term, uitleg in b[1]:
                    verhaal += [P(term, "dt"), P(uitleg, "p")]
            elif soort == "interactief":
                verhaal.append(P("De interactieve kaart (lagen voor route, hoogte, helling en ruwheid) staat in het "
                                 "HTML-rapport.", "p"))

    def voet(canvas, doc):
        canvas.saveState()
        canvas.setFont(gewoon, 7)
        canvas.setFillColor(zacht)
        canvas.drawString(15 * mm, 9 * mm, f"Ritrapport {rap['naam']}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"pagina {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(pad, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"Ritrapport {rap['naam']}", author="Bruut OpenAgbot")
    doc.build(verhaal, onFirstPage=voet, onLaterPages=voet)
    return pad


# ==========================================
# PER RIT
# ==========================================

def rapport_map(csv_pad):
    naam = os.path.splitext(os.path.basename(csv_pad))[0]
    return naam, os.path.join(os.path.dirname(os.path.abspath(csv_pad)), naam)


def verwerk(pad, cfg, args):
    naam, uit_map = rapport_map(pad)
    print(f"\n{naam}")
    raw = lees_log(pad)
    if not raw:
        print("  geen regels in deze log, overgeslagen")
        return
    os.makedirs(uit_map, exist_ok=True)

    def uit(achter):
        return os.path.join(uit_map, f"{naam}_{achter}")

    meldingen = []          # (soort, tekst) voor de aandachtspunten

    def stap(wat, functie):
        try:
            uitkomst = functie()
            print(f"  {wat:<20s} klaar")
            return uitkomst
        except Overgeslagen as e:
            print(f"  {wat:<20s} overgeslagen: {e}")
            meldingen.append(("info", f"{wat[:1].upper() + wat[1:]} overgeslagen: {e}."))
        except Exception as e:
            print(f"  {wat:<20s} MISLUKT: {type(e).__name__}: {e}")
            print("    " + traceback.format_exc().strip().replace("\n", "\n    "))
            meldingen.append(("letop", f"{wat[:1].upper() + wat[1:]} mislukt: {type(e).__name__}: {e}"))
        return None

    tel = stap("telemetrie", lambda: telemetrie(raw, cfg))
    beelden = {}
    if tel:
        beelden["verloop"] = stap("verloop", lambda: verloop_grafiek(tel["rows"], cfg["max_center_angle"], uit("verloop.jpg")))
        beelden["kaart"] = stap("routekaart", lambda: route_kaart(tel["rows"], uit("kaart.jpg"), naam))
    aan = stap("aandrijving", lambda: aandrijving(raw, cfg, args.lam, args.kast_rendement, uit("aandrijving.jpg"), naam))
    ter = stap("terreinkaart", lambda: terrein(raw, uit("terrein.jpg"), naam))
    kaart_html = stap("interactieve kaart", lambda: interactieve_kaart(tel, ter))
    beelden = {k: v for k, v in beelden.items() if v}

    rap = bouw_rapport(naam, tel, aan, ter, beelden, meldingen)
    stap("tekstrapport", lambda: schrijf_tekst(rap, tel, uit("rapport.txt")))
    stap("HTML-rapport", lambda: schrijf_html(rap, kaart_html, uit("rapport.html")))
    stap("PDF-rapport", lambda: schrijf_pdf(rap, uit("rapport.pdf")))
    print(f"  Uitvoer: {uit_map}")


def main():
    global LUCHTFOTO
    try:
        sys.stdout.reconfigure(errors="replace")     # Windows-console kan niet elk teken aan
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description="Alles uit een ritlog: rapport (PDF, HTML, tekst), kaarten en grafieken.")
    p.add_argument("bestanden", nargs="*", help="ritlog(s), jokertekens mogen; zonder: de nieuwste rit in data/logs")
    p.add_argument("--alle", action="store_true", help="alle ritten in data/logs die nog geen rapport hebben")
    p.add_argument("--opnieuw", action="store_true", help="met --alle: ook ritten die al een rapport hebben")
    p.add_argument("--lambda", dest="lam", type=float, help="flux linkage in Wb (uit VESC Tool); anders geschat uit de log")
    p.add_argument("--kast-rendement", type=float, default=0.9, help="rendement van de 5:1 kast (standaard 0.9)")
    p.add_argument("--geen-luchtfoto", action="store_true", help="geen luchtfoto onder de kaarten (geen internet nodig)")
    args = p.parse_args()
    LUCHTFOTO = not args.geen_luchtfoto

    if args.bestanden:
        paden = [f for patroon in args.bestanden for f in (sorted(glob.glob(patroon)) or [patroon])]
    else:
        # Op de datum_tijd in de bestandsnaam; ritten zonder komen eerst.
        def sleutel(f):
            m = re.search(r"(\d{8}_\d{6})\.csv$", f)
            return m.group(1) if m else ""
        alle = sorted(glob.glob(os.path.join(LOG_DIR, "rit_*.csv")), key=sleutel)
        if args.alle:
            paden = [f for f in alle if args.opnieuw or not os.path.exists(
                os.path.join(rapport_map(f)[1], rapport_map(f)[0] + "_rapport.html"))]
            if alle and not paden:
                sys.exit("Alle ritten hebben al een rapport (gebruik --opnieuw om ze opnieuw te maken).")
        else:
            paden = alle[-1:]
    if not paden:
        sys.exit("Geen ritlogs gevonden in data/logs/. Rij eerst een missie met de app.")
    paden = [f for f in paden if os.path.exists(f) or print(f"Niet gevonden: {f}")]
    cfg = laad_config()
    for pad in paden:
        verwerk(pad, cfg, args)


if __name__ == "__main__":
    main()
