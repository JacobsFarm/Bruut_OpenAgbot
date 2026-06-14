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

# Kolommen zoals de NIEUWE logger (app/services/logger.py) ze wegschrijft:
#   Tijdstip, Modus, WP_Doel, Lat, Lon, Fix, HDOP,
#   Heading_Echt, Heading_Doel, Heading_Fout,
#   Stuurhoek, Doel_kmh, Echt_kmh, DAC_Links, DAC_Rechts,
#   Afstand_tot_WP_m, Lookahead_m, Loop_Tijd_s
#
# Let op: 'Heading_Fout' = cross-track error (m) bij de AB-navigator
#         ('TRACKING'/'TURNING'), maar koersfout (graden) bij de
#         waypoint-navigator ('pure_pursuit').

AB_MODES = ("TRACKING", "TURNING")
WP_MODES = ("pure_pursuit",)


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


def percentile(sorted_list, p):
    """De p-de percentiel van een gesorteerde lijst."""
    if not sorted_list:
        return 0.0
    idx = (len(sorted_list) - 1) * p / 100
    low = int(idx)
    high = min(low + 1, len(sorted_list) - 1)
    return sorted_list[low] + (sorted_list[high] - sorted_list[low]) * (idx - low)


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
    """Leest data/config.json (val terug op config.example.json) voor de
    relevante stuur-/voertuiginstellingen, zodat we o.a. de stuurlimiet weten."""
    import json
    settings = {
        "max_angle": 50.0, "wheelbase": 1.2,
        "nav_lookahead": None, "source": "defaults"
    }
    for name in ("config.json", "config.example.json"):
        path = os.path.join(project_root, "data", name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                settings["max_angle"] = cfg.get("steering", {}).get("max_angle_degrees", 50.0)
                settings["wheelbase"] = cfg.get("vehicle", {}).get("wheelbase_m", 1.2)
                settings["nav_lookahead"] = cfg.get("navigation", {}).get("lookahead_distance_m", None)
                settings["source"] = name
            except Exception:
                pass
            break
    return settings


def generate_report(csv_path, report_path, cfg):
    file_short = os.path.basename(csv_path)

    if not os.path.exists(csv_path):
        print(f"❌ Error: Log file '{file_short}' not found!")
        return

    print(f"📂 Processing file: {file_short}")
    max_angle = cfg["max_angle"]
    steer_sat_threshold = max(1.0, max_angle - 0.5)

    # --- Lists & counters ---
    total_rows = 0
    modus_counts = {}

    gps_coords = []
    speed_target_list, speed_real_list = [], []
    loop_time_list = []
    lookahead_list = []
    hdop_list = []
    fix_counts = {}

    heading_error_signed = []      # berekend uit Heading_Echt vs Heading_Doel (graden)
    steer_list = []                # |Stuurhoek| in graden
    steer_signed_list = []         # Stuurhoek met teken
    dac_diff_list, dac_avg_list = [], []
    dist_target_list = []          # Afstand_tot_WP_m (waypoint) / voortgang (AB)

    xte_signed_list = []           # alleen AB (TRACKING): cross-track error in meters
    xte_abs_list = []

    timestamps = []
    tracking_indices = set()       # WP_Doel tijdens TRACKING / pure_pursuit

    # thresholds voor "instabiliteit"
    XTE_INSTABILITY_M = 0.20
    HEADING_INSTABILITY_DEG = 10.0
    STUTTER_S = 0.15

    high_xte_count = 0
    high_heading_count = 0
    stutter_count = 0
    stagnation_count = 0
    steer_maxed_count = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                modus = (row.get("Modus") or "").strip()
                # Sla de afsluitregel ('---', 'EINDE RIT', ...) en lege regels over.
                if modus in ("", "EINDE RIT"):
                    continue

                lat = float(row["Lat"])
                lon = float(row["Lon"])
                fix = int(float(row["Fix"]))
                hdop = float(row["HDOP"])
                heading_echt = float(row["Heading_Echt"])
                heading_doel = float(row["Heading_Doel"])
                heading_fout = float(row["Heading_Fout"])
                stuurhoek = float(row["Stuurhoek"])
                doel_kmh = float(row["Doel_kmh"])
                echt_kmh = float(row["Echt_kmh"])
                dac_l = int(float(row["DAC_Links"]))
                dac_r = int(float(row["DAC_Rechts"]))
                dist_target = float(row["Afstand_tot_WP_m"])
                lookahead = float(row["Lookahead_m"])
                loop_t = float(row["Loop_Tijd_s"])
                wp_idx = row.get("WP_Doel", "")
            except (ValueError, KeyError, TypeError):
                continue

            total_rows += 1
            modus_counts[modus] = modus_counts.get(modus, 0) + 1

            ts = parse_time(row.get("Tijdstip", ""))
            if ts:
                timestamps.append(ts)

            if lat != 0.0 and lon != 0.0:
                gps_coords.append((lat, lon))

            speed_target_list.append(doel_kmh)
            speed_real_list.append(echt_kmh)
            loop_time_list.append(loop_t)
            lookahead_list.append(lookahead)
            hdop_list.append(hdop)
            dist_target_list.append(dist_target)

            fix_counts[fix] = fix_counts.get(fix, 0) + 1

            heading_error_signed.append(angle_difference(heading_doel, heading_echt))

            steer_signed_list.append(stuurhoek)
            steer_list.append(abs(stuurhoek))
            if abs(stuurhoek) >= steer_sat_threshold:
                steer_maxed_count += 1

            dac_diff_list.append(abs(dac_l - dac_r))
            dac_avg_list.append((dac_l + dac_r) / 2)

            # Cross-track error: alleen betekenisvol bij AB-tracking.
            if modus == "TRACKING":
                xte_signed_list.append(heading_fout)
                xte_abs_list.append(abs(heading_fout))
                if abs(heading_fout) > XTE_INSTABILITY_M:
                    high_xte_count += 1

            if modus in WP_MODES or modus == "TRACKING":
                try:
                    tracking_indices.add(int(float(wp_idx)))
                except (ValueError, TypeError):
                    pass

            if abs(heading_error_signed[-1]) > HEADING_INSTABILITY_DEG:
                high_heading_count += 1
            if loop_t > STUTTER_S:
                stutter_count += 1
            if doel_kmh > 0.1 and echt_kmh < 0.1:
                stagnation_count += 1

    if total_rows == 0:
        print(f"❌ No valid data rows found in: {file_short}.")
        return

    # --- Bepaal het type log ---
    is_ab = any(m in modus_counts for m in AB_MODES)
    is_wp = any(m in modus_counts for m in WP_MODES)
    if is_ab and not is_wp:
        log_type = "AB-lijn missie"
    elif is_wp and not is_ab:
        log_type = "Waypoint route (pure pursuit)"
    else:
        log_type = "Onbekend / gemengd"

    # --- Afgeleide statistieken ---
    total_distance_m = 0.0
    for i in range(1, len(gps_coords)):
        total_distance_m += haversine_distance(
            gps_coords[i - 1][0], gps_coords[i - 1][1],
            gps_coords[i][0], gps_coords[i][1]
        )

    # Rijtijd: bij voorkeur uit tijdstempels (Loop_Tijd_s is bij AB constant 0.1).
    if len(timestamps) >= 2:
        total_time_sec = (max(timestamps) - min(timestamps)).total_seconds()
    else:
        total_time_sec = sum(loop_time_list)
    minutes = int(total_time_sec // 60)
    seconds = total_time_sec % 60

    speed_error_list = [abs(t - r) for t, r in zip(speed_target_list, speed_real_list)]
    avg_speed_efficiency = (sum(speed_real_list) / max(sum(speed_target_list), 0.001)) * 100

    avg_heading_error = avg(heading_error_signed)
    heading_bias = ("RECHTS (koerst te ver met de klok mee)" if avg_heading_error > 0.5 else
                    "LINKS (koerst te ver tegen de klok in)" if avg_heading_error < -0.5 else
                    "Geen duidelijke bias")

    # RTK-fix percentages
    fixed_pct = (fix_counts.get(4, 0) / total_rows) * 100
    float_pct = (fix_counts.get(5, 0) / total_rows) * 100
    nofix_pct = (sum(c for fx, c in fix_counts.items() if fx < 2) / total_rows) * 100

    modes_str = ", ".join(f"{m}: {c}" for m, c in sorted(modus_counts.items()))

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
    lines.append(f"- Lookahead (gem.)  : {avg(lookahead_list):.2f} m")
    if tracking_indices:
        lines.append(f"- Indices (WP/baan) : {sorted(tracking_indices)} (max {max(tracking_indices)})")
    lines.append("")

    if xte_abs_list:
        xte_sorted = sorted(xte_abs_list)
        left = sum(1 for v in xte_signed_list if v < 0)
        right = sum(1 for v in xte_signed_list if v > 0)
        xte_bias = ("RECHTS van de lijn" if right > left * 1.2 else
                    "LINKS van de lijn" if left > right * 1.2 else
                    "Geen duidelijke bias")
        lines.append("[LIJNVOLGING (cross-track error)]")
        lines.append(f"- XTE gemiddeld     : {avg(xte_abs_list):.3f} m")
        lines.append(f"- XTE maximum       : {max(xte_abs_list):.3f} m")
        lines.append(f"- XTE P90           : {percentile(xte_sorted, 90):.3f} m")
        lines.append(f"- XTE P95           : {percentile(xte_sorted, 95):.3f} m")
        lines.append(f"- XTE bias          : {xte_bias}  (links {left}x / rechts {right}x)")
        lines.append(f"- Instabiliteit     : {(high_xte_count / max(len(xte_abs_list),1)) * 100:.1f} % (XTE > {XTE_INSTABILITY_M} m)")
        lines.append("  Tip: kleinere lookahead = strakker (maar meer slingeren), groter = soepeler.")
        lines.append("")
    else:
        lines.append("[DOELVOLGING (afstand tot waypoint)]")
        lines.append("  (Geen cross-track error: de waypoint-navigator mikt op het punt,")
        lines.append("   niet op een lijn ertussen.)")
        lines.append(f"- Afstand tot doel gem. : {avg(dist_target_list):.2f} m")
        lines.append(f"- Afstand tot doel max. : {max(dist_target_list):.2f} m")
        lines.append("")

    lines.append("[KOERS & ORIENTATIE]")
    lines.append(f"- Koersfout gem.    : {avg([abs(h) for h in heading_error_signed]):.1f}°")
    lines.append(f"- Koersfout max.    : {max(abs(h) for h in heading_error_signed):.1f}°")
    lines.append(f"- Koers-bias        : {avg_heading_error:+.2f}° → {heading_bias}")
    lines.append(f"- Grote afwijking   : {(high_heading_count / total_rows) * 100:.1f} % (> {HEADING_INSTABILITY_DEG}°)")
    lines.append("")

    lines.append("[SNELHEID & EFFICIENTIE]")
    lines.append(f"- Snelheid echt gem.: {avg(speed_real_list):.2f} km/h")
    lines.append(f"- Snelheid doel gem.: {avg(speed_target_list):.2f} km/h")
    lines.append(f"- Snelheidsfout gem.: {avg(speed_error_list):.2f} km/h")
    lines.append(f"- Efficientie       : {avg_speed_efficiency:.1f} % van doelsnelheid gehaald")
    lines.append(f"- Stilstand         : {(stagnation_count / total_rows) * 100:.1f} % (doel > 0 maar staat stil)")
    lines.append("")

    lines.append("[STUURSYSTEEM]")
    lines.append(f"- Stuurhoek gem.    : {avg(steer_list):.1f}°")
    lines.append(f"- Stuurhoek max.    : {max(steer_list):.1f}°")
    lines.append(f"- Stuurlimiet       : {(steer_maxed_count / total_rows) * 100:.1f} % van de tijd (|hoek| >= {steer_sat_threshold:.1f}°)")
    lines.append(f"- DAC-verschil gem. : {avg(dac_diff_list):.1f}  (stuurintensiteit)")
    lines.append(f"- DAC-belasting gem.: {avg(dac_avg_list):.1f}  (motorbelasting)")
    lines.append("")

    lines.append("[GPS & SYSTEEM]")
    lines.append(f"- RTK Fixed (4)     : {fixed_pct:.1f} %")
    lines.append(f"- RTK Float (5)     : {float_pct:.1f} %")
    lines.append(f"- Geen/zwakke fix   : {nofix_pct:.1f} % (fix < 2)")
    lines.append(f"- HDOP gemiddeld    : {avg(hdop_list):.2f}  (ideaal < 1.0)")
    lines.append(f"- Loop-tijd gem.    : {avg(loop_time_list):.3f} s")
    lines.append(f"- Loop-tijd max.    : {max(loop_time_list):.3f} s")
    lines.append(f"- CPU-hapering      : {(stutter_count / total_rows) * 100:.1f} % (loop > {int(STUTTER_S*1000)} ms)")
    lines.append("")

    lines.append("[INSTELLINGEN (uit config)]")
    lines.append(f"- Bron config       : {cfg['source']}")
    lines.append(f"- Max stuurhoek     : {cfg['max_angle']}°")
    lines.append(f"- Wielbasis         : {cfg['wheelbase']} m")
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
