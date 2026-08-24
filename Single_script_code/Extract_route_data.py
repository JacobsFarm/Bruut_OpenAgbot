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
#   Stuurhoek, Doel_kmh, Echt_kmh, DAC_Links, DAC_Rechts,
#   Afstand_tot_WP_m, Lookahead_m, Loop_Tijd_s
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
                    "dac_l": float(raw["DAC_Links"]),
                    "dac_r": float(raw["DAC_Rechts"]),
                    "afstand": float(raw["Afstand_tot_WP_m"]),
                    "lookahead": float(raw["Lookahead_m"]),
                    "loop_t": float(raw["Loop_Tijd_s"]),
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
    xte = [abs(r["h_fout"]) for r in seg["rows"]]

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
        "signed_na": [r["h_fout"] for r in seg["rows"][settle_i:]] if settle_i is not None else [],
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
        links = sum(1 for v in signed_na if v < 0)
        rechts = sum(1 for v in signed_na if v > 0)
        bias = ("RECHTS van de lijn" if rechts > links * 1.2 else
                "LINKS van de lijn" if links > rechts * 1.2 else
                "Geen duidelijke bias")
        onrustig = sum(1 for v in xte_na if v > XTE_INSTABILITY_M)

        lines.append("[LIJNVOLGING (cross-track error)]")
        lines.append("  Dit is de kwaliteitsmaat: alleen de meters NADAT hij de baan heeft")
        lines.append(f"  opgepakt (binnen {XTE_SETTLED_M} m). Het aanrijden zit er niet in.")
        lines.append(f"- XTE gemiddeld     : {avg(xte_na):.3f} m")
        lines.append(f"- XTE maximum       : {max(xte_na) if xte_na else 0:.3f} m")
        lines.append(f"- XTE P90           : {percentile(xte_na, 90):.3f} m")
        lines.append(f"- XTE P95           : {percentile(xte_na, 95):.3f} m")
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
    lines.append(f"- DAC-verschil gem. : {avg([abs(r['dac_l'] - r['dac_r']) for r in rows]):.1f}  "
                 f"(stuurintensiteit)")
    lines.append(f"- DAC-belasting gem.: {avg([(r['dac_l'] + r['dac_r']) / 2 for r in rows]):.1f}  "
                 f"(motorbelasting)")

    # Scheeftrek-test: rijdt hij met de wielen recht ook echt recht, of trekt
    # een van de twee hubmotoren? Alleen zinvol als hij ook echt rijdt.
    recht = [r for r in rows if abs(r["stuur"]) < STRAIGHT_STEER_DEG and r["echt_kmh"] > 0.5]
    if len(recht) >= 20:
        verschil = avg([r["dac_l"] - r["dac_r"] for r in recht])
        oordeel = "symmetrisch" if abs(verschil) < 15 else "SCHEEF - een kant trekt harder"
        lines.append(f"- Scheeftrek-test   : rechtuit (n={len(recht)}) links-rechts "
                     f"{verschil:+.1f} DAC -> {oordeel}")
    else:
        lines.append("- Scheeftrek-test   : te weinig rechtuit-samples "
                     f"(|stuurhoek| < {STRAIGHT_STEER_DEG}° en rijdend)")
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
