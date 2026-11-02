import os
import csv
import math
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
# --- SMART PATHS ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

# ------------------------------------------
# CHOOSE YOUR MODE
# ------------------------------------------
# True  = process ALL csv files in the log directory.
# False = only process the single file in FILE_NAME below.
PROCESS_ENTIRE_FOLDER = True

# Used only when PROCESS_ENTIRE_FOLDER is False:
FILE_NAME = "rit_Waypoint_Route_20260614_210608.csv"
# ==========================================

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
XTE_SETTLED_M = 0.10            # hieronder heet de baan opgepakt
HEADING_INSTABILITY_DEG = 10.0
STUTTER_S = 0.15
STRAIGHT_STEER_DEG = 1.0        # |stuurhoek| hieronder = rechtuit (scheeftrek-test)


# --- Helper functions ---

def haversine_distance(lat1, lon1, lat2, lon2):
    """Afstand in meters tussen twee GPS-coordinaten."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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


def avg(values, default=0.0):
    return (sum(values) / len(values)) if values else default


def optional_float(raw, key):
    """Kolom als float, of None als hij in deze log ontbreekt of leeg is."""
    try:
        return float(raw[key])
    except (KeyError, ValueError, TypeError):
        return None


def parse_time(value):
    """Parset 'HH:MM:SS.mmm' (of zonder ms) naar een datetime; anders None."""
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def load_config_settings(project_root):
    """
    Leest data/config.json (val terug op config.example.json) voor de
    voertuig- en stuurinstellingen.

    Belangrijk: max_angle_degrees is de limiet per WIEL. De VehicleController
    klemt de gevraagde stuurhoek echter op de MIDDENHOEK van de vooras, en die
    ligt lager omdat het binnenwiel bij Ackermann scherper staat. Meet je de
    verzadiging tegen de wiellimiet, dan lijkt het alsof de robot nooit aan zijn
    eind zit terwijl hij in werkelijkheid volop tegen de aanslag stuurt.
    """
    import json
    settings = {
        "max_angle": 50.0, "wheelbase": 1.2, "track_width": 1.0,
        "nav_lookahead": None, "turn_timeout": 90.0, "source": "defaults"
    }
    for name in ("config.json", "config.example.json"):
        path = os.path.join(project_root, "data", name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                settings["max_angle"] = cfg.get("steering", {}).get("max_angle_degrees", 50.0)
                settings["wheelbase"] = cfg.get("vehicle", {}).get("wheelbase_m", 1.2)
                settings["track_width"] = cfg.get("vehicle", {}).get("track_width_m", 1.0)
                nav = cfg.get("navigation", {})
                settings["nav_lookahead"] = nav.get("lookahead_distance_m", None)
                settings["turn_timeout"] = nav.get("turn_timeout_s", 90.0)
                settings["source"] = name
            except Exception:
                pass
            break

    tangens = math.tan(math.radians(settings["max_angle"]))
    if tangens > 1e-6:
        radius = settings["wheelbase"] / tangens + settings["track_width"] / 2.0
        settings["max_center_angle"] = math.degrees(math.atan(settings["wheelbase"] / radius))
    else:
        settings["max_center_angle"] = settings["max_angle"]
    return settings


def read_rows(csv_path):
    """Leest de log in als een lijst dicts; slaat kop- en afsluitregels over."""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            modus = (raw.get("Modus") or "").strip()
            if modus in ("", "EINDE RIT"):
                continue
            try:
                rows.append({
                    "t": parse_time(raw.get("Tijdstip", "")),
                    "modus": modus,
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
            except (ValueError, KeyError, TypeError):
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


def analyseer_baan(seg, settle_window=20):
    """
    Cijfers voor een enkele baan.

    'Oppakken' is de afwijking op de eerste regel: hoe scheef hij de baan
    binnenkomt. Daarna zoeken we het moment waarop hij de lijn te pakken heeft
    en houdt - vandaar het venster van settle_window regels (2 seconden) die
    allemaal binnen XTE_SETTLED_M moeten liggen. Kijk je alleen naar de eerste
    regel onder de drempel, dan telt een NULDOORGANG al als opgepakt terwijl
    hij op dat moment vol tegen de stuuraanslag dwars door de lijn schiet.

    'Uitslag' is de grootste afwijking tijdens dat oppakken: schiet hij door
    naar de andere kant van de lijn, dan zie je dat hier.
    """
    xte = [abs(xte_waarde(r)) for r in seg["rows"]]

    settle_i = None
    for i in range(len(xte)):
        venster = xte[i:i + settle_window]
        if venster and all(v < XTE_SETTLED_M for v in venster):
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
        "settle_s": (settle_i * 0.1) if settle_i is not None else None,
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


def generate_report(csv_path, report_path, cfg):
    file_short = os.path.basename(csv_path)

    if not os.path.exists(csv_path):
        print(f"❌ Error: Log file '{file_short}' not found!")
        return

    print(f"📂 Processing file: {file_short}")
    rows = read_rows(csv_path)
    if not rows:
        print(f"❌ No valid data rows found in: {file_short}.")
        return

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

    # ==========================================
    # BUILD REPORT
    # ==========================================
    lines = []
    lines.append("==================================================")
    lines.append(f"🤖 TELEMETRY ANALYSE: {file_short}")
    lines.append("==================================================\n")

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
    lines.append("")
    lines.append("Analyseer dit en geef aanbevelingen.")
    lines.append("==================================================")

    report_text = "\n".join(lines)
    print(report_text)
    try:
        with open(report_path, "w", encoding="utf-8") as f_out:
            f_out.write(report_text)
        print(f"💾 Opgeslagen als: '{os.path.basename(report_path)}'\n")
    except Exception as e:
        print(f"❌ Fout bij opslaan rapport: {e}")

    html_path = os.path.splitext(report_path)[0] + ".html"
    try:
        schrijf_html(file_short, report_text, banen, bochten, rows, cfg, html_path)
        print(f"🌐 HTML-rapport     : '{os.path.basename(html_path)}'\n")
    except Exception as e:
        print(f"❌ Fout bij maken HTML-rapport: {e}")


# ==========================================
# HTML-RAPPORT
# ==========================================
HTML_CSS = """
:root{--bg:#f6f7f4;--kaart:#fff;--tekst:#1c2321;--zacht:#5b6763;--lijn:#dde2de;--goed:#2d7a46;--let:#b4531f;--info:#2f5d8a}
@media(prefers-color-scheme:dark){:root{--bg:#14181a;--kaart:#1d2326;--tekst:#e6ebe8;--zacht:#9aa6a1;--lijn:#2d3639;--goed:#5fbf82;--let:#e8905a;--info:#78a9d8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tekst);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:1.5rem;margin:0 0 2px} h2{font-size:1.1rem;margin:0 0 4px}
.sub{color:var(--zacht);margin-bottom:18px;word-break:break-all}
.kaarten{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:18px}
.kaart{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;padding:12px 14px}
.kaart .k{color:var(--zacht);font-size:.8rem} .kaart .g{font-size:1.3rem;font-weight:650;margin:2px 0;overflow-wrap:anywhere}
section{background:var(--kaart);border:1px solid var(--lijn);border-radius:10px;padding:14px 16px;margin-bottom:14px}
section .intro{color:var(--zacht);font-size:.85rem;margin:0 0 8px}
.tw{overflow-x:auto;margin:8px 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--lijn)}
th:first-child,td:first-child{text-align:left} th{font-size:.78rem;color:var(--zacht);font-weight:600}
tr:last-child td{border-bottom:0}
table.kv td:first-child{color:var(--zacht);white-space:nowrap;width:1%;padding-right:20px}
table.kv td:last-child{text-align:left;white-space:normal}
tr.sub td:first-child{padding-left:28px}
tr.warn td{background:rgba(180,83,31,.12)} tr.warn td:first-child{color:var(--let);font-weight:600}
td.noot{text-align:left;color:var(--zacht);font-size:.82rem;white-space:normal}
.aandacht{list-style:none;padding:0;margin:0}
.aandacht li{border-left:4px solid var(--let);background:rgba(180,83,31,.08);border-radius:6px;padding:8px 12px;margin-bottom:6px}
.goed{border-left:4px solid var(--goed);background:rgba(45,122,70,.08);border-radius:6px;padding:8px 12px}
img{width:100%;height:auto;border-radius:8px;border:1px solid var(--lijn);background:#fff}
@media print{body{background:#fff;color:#000}section,.kaart{break-inside:avoid}main{padding:0}}
"""

HTML_KPI = [
    ("RIT OVERZICHT", "Rijtijd", "Rijtijd"),
    ("RIT OVERZICHT", "Afstand gereden", "Afstand"),
    ("LIJNVOLGING (cross-track error)", "XTE gemiddeld", "Afwijking van de lijn, gem."),
    ("LIJNVOLGING (cross-track error)", "XTE P95", "Afwijking van de lijn, P95"),
    ("KOERS & ORIENTATIE", "Koers-bias", "Koers-bias"),
    ("SNELHEID & EFFICIENTIE", "Tijdens de baan", "Snelheid op de baan"),
    ("ACCU & WIELEN", "Lading (schatting)", "Lading"),
    ("ACCU & WIELEN", "Vermogen", "Vermogen"),
    ("ACCU & WIELEN", "Energie deze rit", "Energie"),
    ("GPS & SYSTEEM", "RTK Fixed (4)", "RTK fixed"),
]


def parse_rapport(tekst):
    """Het tekstrapport terug in secties: titel, uitleg en regels (kv / sub / note)."""
    import re
    secties, huidig = [], None
    for ln in tekst.split("\n"):
        s = ln.rstrip()
        if not s.strip() or s.startswith("====") or "TELEMETRY ANALYSE" in s or s.startswith("Analyseer dit"):
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


def maak_grafiek(rows, max_center):
    """XTE, snelheid en stuurhoek over de rit, met de kopakkerbochten grijs; als base64-PNG."""
    import base64
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if all(r["t"] for r in rows):
        t0 = rows[0]["t"]
        t = [((r["t"] - t0).total_seconds() + 86400) % 86400 for r in rows]
    else:
        t, acc = [], 0.0
        for r in rows:
            acc += r["loop_t"]
            t.append(acc)
    nan = float("nan")
    xte = [xte_waarde(r) if r["modus"] == "TRACKING" else nan for r in rows]
    fig, ax = plt.subplots(3, 1, figsize=(13, 8), sharex=True, constrained_layout=True)
    ax[0].plot(t, xte, lw=0.7, color="#1f77b4")
    ax[0].axhline(0, color="k", lw=0.5)
    ax[0].set_ylim(-0.3, 0.3)
    ax[0].set_ylabel("afwijking van de lijn (m)")
    ax[0].set_title("Lijnvolging (alleen op de baan; as afgekapt op \u00b130 cm)")
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
    ax[2].set_title(f"Stuurhoek (rode lijn = limiet middenhoek {max_center:.1f}\u00b0)")
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
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def schrijf_html(file_short, report_text, banen, bochten, rows, cfg, uit_pad):
    """Zelfstandig HTML-rapport (te printen als PDF) uit hetzelfde tekstrapport en de baan/bocht-cijfers."""
    import html as h
    e = h.escape
    secties = parse_rapport(report_text)
    waarden = {(sec["titel"], r[1]): r[2] for sec in secties for r in sec["regels"] if r[0] == "kv"}

    kaarten = "".join(
        f'<div class="kaart"><div class="k">{e(label)}</div><div class="g">{e(waarden[(sec, key)])}</div></div>'
        for sec, key, label in HTML_KPI if (sec, key) in waarden)

    def is_waarschuwing(key, waarde):
        return (key.startswith("LET OP") or "SCHEEF" in waarde or "<<" in waarde
                or key in ("Scheef opgepakt", "Doorgeschoten")
                or (key == "Koers-bias" and ("LINKS" in waarde or "RECHTS" in waarde)))

    hints = {"Koers-bias": " Blijft dit in beide rijrichtingen even groot terwijl de afwijking van de lijn "
                           "klein is, dan meet de dubbele antenne een vaste koersoffset: stel "
                           "gnss.heading_offset_deg bij in de config."}
    aandacht = [f"{key}: {waarde}.{hints.get(key, '')}" for sec in secties for soort, key, waarde in sec["regels"]
                if soort == "kv" and is_waarschuwing(key, waarde)]
    aandacht_html = ('<ul class="aandacht">' + "".join(f"<li>{e(a)}</li>" for a in aandacht) + "</ul>"
                     if aandacht else '<div class="goed">Geen waarschuwingen in dit rapport.</div>')

    def tabel_banen():
        rijen = ""
        for i, b in enumerate(banen, 1):
            settle = f"{b['settle_s']:.1f} s" if b["settle_s"] is not None else "nooit"
            klas = ' class="warn"' if b["oppakken"] > 0.5 else ""
            rijen += (f"<tr{klas}><td>{i}</td><td>{b['baan']}</td><td>{b['duur']:.1f} s</td><td>{b['lengte']:.1f} m</td>"
                      f"<td>{b['oppakken']:.2f} m</td><td>{b['uitslag']:.2f} m</td><td>{settle}</td>"
                      f"<td>{b['gem']:.3f} / {b['max']:.3f} m</td></tr>")
        kop = "".join(f"<th>{k}</th>" for k in ("Nr", "Baan", "Duur", "Lengte", "Oppakken", "Uitslag",
                                                  "Op de lijn na", "Daarna gem / max"))
        return f'<div class="tw"><table><thead><tr>{kop}</tr></thead><tbody>{rijen}</tbody></table></div>'

    def tabel_bochten():
        rijen = ""
        for i, t in enumerate(bochten, 1):
            van = "start" if t["van"] is None else t["van"]
            naar = "eind" if t["naar"] is None else t["naar"]
            opm = "TIMEOUT" if t["timeout"] else ("naast de lijn begonnen" if t["afstand_pad"] > 1.0 else "")
            klas = ' class="warn"' if opm else ""
            rijen += (f"<tr{klas}><td>{i}</td><td>{van} \u2192 {naar}</td><td>{t['duur']:.1f} s</td>"
                      f"<td>{t['gem']:.1f} / {t['max']:.1f}\u00b0</td><td>{t['afstand_pad']:.2f} m</td><td>{opm}</td></tr>")
        kop = "".join(f"<th>{k}</th>" for k in ("Nr", "Van \u2192 naar", "Duur", "Koersfout gem / max",
                                                  "Afstand tot pad", "Opmerking"))
        return f'<div class="tw"><table><thead><tr>{kop}</tr></thead><tbody>{rijen}</tbody></table></div>'

    delen = []
    for sec in secties:
        inhoud = ""
        if sec["titel"] == "PER BAAN" and banen:
            inhoud += tabel_banen()
        if sec["titel"] == "PER KOPAKKERBOCHT" and bochten:
            inhoud += tabel_bochten()
        # Uitleg die direct onder de titel staat, boven de tabel
        voor = []
        for soort, key, waarde in sec["regels"]:
            if soort != "note":
                break
            voor.append(key)
        intro_html = (f'<p class="intro">{e(sec["sub"])}</p>' if sec["sub"] else "")
        intro_html += "".join(f'<p class="intro">{e(t)}</p>' for t in voor)
        kv_html = ""
        gezien_kv = False
        for soort, key, waarde in sec["regels"]:
            if soort == "note":
                if gezien_kv:
                    kv_html += f'<tr><td class="noot" colspan="2">{e(key)}</td></tr>'
                continue
            gezien_kv = True
            klas = "sub" if soort == "sub" else ""
            if is_waarschuwing(key, waarde):
                klas = (klas + " warn").strip()
            kv_html += f'<tr class="{klas}"><td>{e(key)}</td><td>{e(waarde)}</td></tr>'
        if kv_html:
            inhoud += f'<div class="tw"><table class="kv"><tbody>{kv_html}</tbody></table></div>'
        delen.append(f"<section><h2>{e(sec['titel'].capitalize())}</h2>{intro_html}{inhoud}</section>")

    grafiek = maak_grafiek(rows, cfg["max_center_angle"])
    pagina = (f'<!doctype html><html lang="nl"><head><meta charset="utf-8">'
              f'<meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<title>Telemetrie analyse</title><style>{HTML_CSS}</style></head><body><main>'
              f'<h1>Telemetrie analyse</h1><div class="sub">{e(file_short)}</div>'
              f'<div class="kaarten">{kaarten}</div>'
              f'<section><h2>Aandachtspunten</h2>{aandacht_html}</section>'
              f'<section><h2>Verloop van de rit</h2><img alt="Verloop" src="data:image/png;base64,{grafiek}">'
              f'<p class="intro">Grijs = kopakkerbocht.</p></section>'
              + "".join(delen) + '</main></body></html>')
    with open(uit_pad, "w", encoding="utf-8") as f:
        f.write(pagina)


if __name__ == "__main__":
    cfg = load_config_settings(PROJECT_ROOT)

    if not os.path.isdir(LOG_DIR):
        print(f"⚠️ Log-map niet gevonden: {LOG_DIR}")
    elif PROCESS_ENTIRE_FOLDER:
        print(f"🔍 Zoek alle CSV-bestanden in: {LOG_DIR}")
        csv_files = [f for f in os.listdir(LOG_DIR)
                     if f.endswith(".csv") and not f.endswith("_extracted_data.csv")]
        if not csv_files:
            print("⚠️ Geen .csv-bestanden gevonden in de log-map.")
        else:
            for file_name in csv_files:
                csv_path = os.path.join(LOG_DIR, file_name)
                base_name = os.path.splitext(file_name)[0]
                output_report = os.path.join(LOG_DIR, f"{base_name}_extracted_data.txt")
                generate_report(csv_path, output_report, cfg)
            print(f"🎉 Klaar! {len(csv_files)} bestand(en) verwerkt.")
    else:
        csv_path = os.path.join(LOG_DIR, FILE_NAME)
        base_name = os.path.splitext(FILE_NAME)[0]
        output_report = os.path.join(LOG_DIR, f"{base_name}_extracted_data.txt")
        generate_report(csv_path, output_report, cfg)
