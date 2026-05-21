import os
import csv
import math

# ==========================================
# CONFIGURATIE
# ==========================================
BESTANDSNAAM = "rit_1_20_05_2026.csv" # Pas dit aan naar je nieuwste rit

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")
NAVIGATOR_PATH = os.path.join(PROJECT_ROOT, "app", "services", "navigator.py")

CSV_FILE = os.path.join(LOG_DIR, BESTANDSNAAM)
_base_name = os.path.splitext(BESTANDSNAAM)[0]
OUTPUT_REPORT = os.path.join(LOG_DIR, f"{_base_name}_extracted_data.txt")
# ==========================================

# --- Hulpfuncties ---

def haversine_afstand(lat1, lon1, lat2, lon2):
    """Berekent afstand in meters tussen twee GPS-coördinaten."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def hoek_verschil(h1, h2):
    """Berekent het kortste verschil tussen twee koersen (-180 t/m +180)."""
    diff = (h2 - h1 + 180) % 360 - 180
    return diff

def percentiel(gesorteerd, p):
    """Geeft het p-de percentiel van een gesorteerde lijst terug."""
    if not gesorteerd:
        return 0.0
    idx = (len(gesorteerd) - 1) * p / 100
    laag = int(idx)
    hoog = min(laag + 1, len(gesorteerd) - 1)
    return gesorteerd[laag] + (gesorteerd[hoog] - gesorteerd[laag]) * (idx - laag)

def haal_live_parameters_uit_navigator(nav_pad):
    params = {
        "kp": "N/B", "kd": "N/B", "k_xte": "N/B",
        "kp_snelheid": "N/B", "ki_snelheid": "N/B",
        "look_ahead": "N/B" # <-- NIEUW
    }
    if not os.path.exists(nav_pad):
        return params
    try:
        with open(nav_pad, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    continue
                if "self.kp =" in line and "snelheid" not in line:
                    params["kp"] = line.split("=")[1].split("#")[0].strip()
                elif "self.kd =" in line:
                    params["kd"] = line.split("=")[1].split("#")[0].strip()
                elif "self.k_xte =" in line:
                    params["k_xte"] = line.split("=")[1].split("#")[0].strip()
                elif "self.kp_snelheid =" in line:
                    params["kp_snelheid"] = line.split("=")[1].split("#")[0].strip()
                elif "self.ki_snelheid =" in line:
                    params["ki_snelheid"] = line.split("=")[1].split("#")[0].strip()
                elif "self.look_ahead_dist =" in line: # <-- NIEUW
                    params["look_ahead"] = line.split("=")[1].split("#")[0].strip()
    except:
        pass
    return params


def genereer_ai_rapport(csv_pad, rapport_pad, nav_pad):
    if not os.path.exists(csv_pad):
        print(f"❌ Fout: Logbestand '{csv_pad}' niet gevonden!")
        return

    pid = haal_live_parameters_uit_navigator(nav_pad)

    # --- Tellers & lijsten ---
    totale_regels = 0

    # Bestaande metrics
    xte_gesigneerd_lijst = []          
    xte_abs_lijst = []
    fout_lijst = []
    snel_doel_lijst, snel_echt_lijst = [], []
    dt_lijst, turn_lijst, i_term_lijst = [], [], []
    dac_verschil_lijst, dac_gem_lijst = [], []
    fix_ok_count = 0
    stuur_maxed_count = 0
    hapering_count = 0
    hoge_afwijking_count = 0

    # Nieuwe metrics
    hdop_lijst = []
    hdop_slecht_count = 0              
    heading_fout_gesigneerd = []       
    pi_corr_lijst = []                 
    afstand_wp_lijst = []              
    wp_bezoeken = {}                   
    gps_coords = []                    
    i_term_positief = 0                
    i_term_negatief = 0
    grote_i_term_count = 0             
    pi_corr_hoog_count = 0            
    stagnatie_count = 0                
    dac_asymmetrie_hoog_count = 0      
    xte_links_count = 0               
    xte_rechts_count = 0              
    
    # Tracking voor look-ahead data in CSV
    lookahead_data_aanwezig = False

    I_TERM_DREMPEL = 5.0
    PI_CORR_DREMPEL = 200.0
    DAC_ASYM_DREMPEL = 300

    met_geldige_gps = 0

    with open(csv_pad, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                xte_gesigneerd = float(row['XTE_Meters'])
                xte = abs(xte_gesigneerd)
                fout = abs(float(row['Fout_Graden']))
                snel_doel = float(row['Snelheid_Doel_kmh'])
                snel_echt = float(row['Snelheid_Echt_kmh'])
                dt = float(row['Delta_Tijd_Sec'])
                turn = abs(float(row['Ruwe_Turn']))
                i_term = float(row['PI_Integraal'])
                fix = int(row['Fix'])
                dac_l = int(row['DAC_Links'])
                dac_r = int(row['DAC_Rechts'])
                hdop = float(row['HDOP'])
                heading = float(row['Heading'])
                doel_heading = float(row['Doel_Heading'])
                pi_corr = float(row['Ruwe_PI_Corr'])
                afstand_wp = float(row['Afstand_tot_WP'])
                wp_idx = int(row['WP_Doel'])
                lat = float(row['Lat'])
                lon = float(row['Lon'])
                
                # Check of look-ahead data in deze row/CSV zit (veilig uilezen)
                la_lat = row.get('Lookahead_Lat', '')
                la_lon = row.get('Lookahead_Lon', '')
                if la_lat and la_lon:
                    lookahead_data_aanwezig = True

                # --- Lijsten vullen ---
                xte_gesigneerd_lijst.append(xte_gesigneerd)
                xte_abs_lijst.append(xte)
                fout_lijst.append(fout)
                snel_doel_lijst.append(snel_doel)
                snel_echt_lijst.append(snel_echt)
                dt_lijst.append(dt)
                turn_lijst.append(turn)
                i_term_lijst.append(abs(i_term))
                hdop_lijst.append(hdop)
                pi_corr_lijst.append(abs(pi_corr))
                afstand_wp_lijst.append(afstand_wp)
                gps_coords.append((lat, lon))

                # Gesigneerde heading fout
                h_fout = hoek_verschil(doel_heading, heading)
                heading_fout_gesigneerd.append(h_fout)

                # DAC berekeningen
                dac_verschil = abs(dac_l - dac_r)
                dac_gem = (dac_l + dac_r) / 2
                dac_verschil_lijst.append(dac_verschil)
                dac_gem_lijst.append(dac_gem)

                totale_regels += 1

                # --- Tellers ---
                if xte > 0.20:
                    hoge_afwijking_count += 1
                if fix == 4:
                    fix_ok_count += 1
                    met_geldige_gps += 1
                if turn >= 390:
                    stuur_maxed_count += 1
                if dt > 0.15:
                    hapering_count += 1
                if hdop > 1.5:
                    hdop_slecht_count += 1
                if i_term > 0:
                    i_term_positief += 1
                else:
                    i_term_negatief += 1
                if abs(i_term) > I_TERM_DREMPEL:
                    grote_i_term_count += 1
                if abs(pi_corr) > PI_CORR_DREMPEL:
                    pi_corr_hoog_count += 1
                if dac_verschil > DAC_ASYM_DREMPEL:
                    dac_asymmetrie_hoog_count += 1
                if snel_doel > 0 and snel_echt < 0.1:
                    stagnatie_count += 1
                if xte_gesigneerd > 0:
                    xte_rechts_count += 1
                elif xte_gesigneerd < 0:
                    xte_links_count += 1

                # Waypoint tracking
                if wp_idx not in wp_bezoeken:
                    wp_bezoeken[wp_idx] = 0
                wp_bezoeken[wp_idx] += 1

            except (ValueError, KeyError):
                pass

    if totale_regels == 0:
        print("❌ Geen geldige regels gevonden in het CSV-bestand.")
        return

    # --- Nabewerking ---
    totale_afstand_m = 0.0
    for i in range(1, len(gps_coords)):
        totale_afstand_m += haversine_afstand(
            gps_coords[i - 1][0], gps_coords[i - 1][1],
            gps_coords[i][0], gps_coords[i][1]
        )

    totale_tijd_sec = sum(dt_lijst)
    minuten = int(totale_tijd_sec // 60)
    seconden = totale_tijd_sec % 60
    gem_tijd_per_wp = (totale_tijd_sec / max(len(wp_bezoeken), 1))
    snel_fout_lijst = [abs(d - e) for d, e in zip(snel_doel_lijst, snel_echt_lijst)]

    xte_gesorteerd = sorted(xte_abs_lijst)
    xte_p90 = percentiel(xte_gesorteerd, 90)
    xte_p95 = percentiel(xte_gesorteerd, 95)

    gem_heading_fout = sum(heading_fout_gesigneerd) / len(heading_fout_gesigneerd)
    heading_bias_richting = "RECHTS (robot draait te ver CW)" if gem_heading_fout > 0.5 else \
                            "LINKS (robot draait te ver CCW)" if gem_heading_fout < -0.5 else \
                            "Geen significante bias"

    xte_bias = "RECHTS van lijn" if xte_rechts_count > xte_links_count * 1.2 else \
               "LINKS van lijn" if xte_links_count > xte_rechts_count * 1.2 else \
               "Geen duidelijke voorkeur"

    if i_term_positief > i_term_negatief * 1.5:
        windup_richting = "Positief (structurele ondercorrectie)"
    elif i_term_negatief > i_term_positief * 1.5:
        windup_richting = "Negatief (structurele overcorrectie)"
    else:
        windup_richting = "Gebalanceerd"

    gem_snel_efficiëntie = (sum(snel_echt_lijst) / max(sum(snel_doel_lijst), 0.001)) * 100

    # Look-ahead status string
    la_status = "Aanwezig" if lookahead_data_aanwezig else "Niet geregistreerd (Oude log)"

    # ==========================================
    # RAPPORT OPBOUWEN
    # ==========================================
    rapport_tekst = (
        f"==================================================\n"
        f"🤖 TELEMETRIE ANALYSE: {os.path.basename(csv_pad)}\n"
        f"==================================================\n\n"

        f"[RIT OVERZICHT]\n"
        f"- Totale regels     : {totale_regels}\n"
        f"- Rijtijd           : {minuten}m {seconden:.1f}s ({totale_tijd_sec:.1f} sec totaal)\n"
        f"- Gereden afstand   : {totale_afstand_m:.1f} m  ({totale_afstand_m / 1000:.3f} km)\n"
        f"- Waypoints bereikt : {len(wp_bezoeken)}  (indices: {sorted(wp_bezoeken.keys())})\n"
        f"- Gem. tijd per WP  : {gem_tijd_per_wp:.1f} s\n"
        f"- Look-Ahead Coords : {la_status} in CSV\n\n" # <-- GEEFT AAN OF LA-DATA IS OPGESLAGEN

        f"[LIJNVOLGING]\n"
        f"- XTE Gemiddeld     : {sum(xte_abs_lijst)/len(xte_abs_lijst):.3f} m\n"
        f"- XTE Maximaal      : {max(xte_abs_lijst):.3f} m\n"
        f"- XTE P90           : {xte_p90:.3f} m  (90% van metingen onder dit)\n"
        f"- XTE P95           : {xte_p95:.3f} m\n"
        f"- XTE Voorkeurszijde: {xte_bias}\n"
        f"    Links ({xte_links_count}x) vs Rechts ({xte_rechts_count}x)\n"
        f"- Instabiliteit     : {(hoge_afwijking_count / totale_regels) * 100:.1f} % van de rit (XTE > 0.20m)\n\n"

        f"[KOERS & ORIËNTATIE]\n"
        f"- Hoek Fout Gem.    : {sum(fout_lijst)/len(fout_lijst):.1f}°\n"
        f"- Hoek Fout Max.    : {max(fout_lijst):.1f}°\n"
        f"- Heading Bias      : {gem_heading_fout:+.2f}°  → {heading_bias_richting}\n"
        f"    (Positief = robot koopt rechts van doelkoers)\n\n"

        f"[SNELHEID & EFFICIËNTIE]\n"
        f"- Snelheid Echt Gem.: {sum(snel_echt_lijst)/len(snel_echt_lijst):.2f} km/h\n"
        f"- Snelheid Doel Gem.: {sum(snel_doel_lijst)/len(snel_doel_lijst):.2f} km/h\n"
        f"- Snelheidsfout Gem.: {sum(snel_fout_lijst)/len(snel_fout_lijst):.2f} km/h\n"
        f"- Snelheidsefficiënt: {gem_snel_efficiëntie:.1f} % van doelsnelheid gehaald\n"
        f"- Stagnatie         : {(stagnatie_count / totale_regels) * 100:.1f} % (doelsnelheid > 0 maar stilstand)\n\n"

        f"[STUURSYSTEEM & PI REGELAAR]\n"
        f"- DAC Verschil Gem. : {sum(dac_verschil_lijst)/len(dac_verschil_lijst):.1f}  (Stuurintensiteit)\n"
        f"- DAC Belasting Gem.: {sum(dac_gem_lijst)/len(dac_gem_lijst):.1f}  (Motor Load)\n"
        f"- Stuur Limiet      : {(stuur_maxed_count / totale_regels) * 100:.1f} % van de tijd (turn >= 390)\n"
        f"- PI Corr. Gem.     : {sum(pi_corr_lijst)/len(pi_corr_lijst):.1f}  (Ruwe correctie)\n"
        f"- PI Corr. Hoog     : {(pi_corr_hoog_count / totale_regels) * 100:.1f} % (|corr| > {PI_CORR_DREMPEL})\n"
        f"- Integraal Windup  : {windup_richting}\n"
        f"- Grote I-term      : {(grote_i_term_count / totale_regels) * 100:.1f} % (|I| > {I_TERM_DREMPEL})\n"
        f"- DAC Asymmetrie >  : {(dac_asymmetrie_hoog_count / totale_regels) * 100:.1f} % (verschil > {DAC_ASYM_DREMPEL} DAC)\n\n"

        f"[GPS & SYSTEEM GEZONDHEID]\n"
        f"- GPS RTK Fix (4)   : {(fix_ok_count / totale_regels) * 100:.1f} %\n"
        f"- HDOP Gemiddeld    : {sum(hdop_lijst)/len(hdop_lijst):.2f}  (ideaal < 1.0)\n"
        f"- HDOP Slecht       : {(hdop_slecht_count / totale_regels) * 100:.1f} % (HDOP > 1.5)\n"
        f"- Loop Tijd Gem.    : {sum(dt_lijst)/len(dt_lijst):.3f} s\n"
        f"- Loop Tijd Max.    : {max(dt_lijst):.3f} s\n"
        f"- CPU Hapering      : {(hapering_count / totale_regels) * 100:.1f} % (dt > 150ms)\n\n"

        f"[ACTUELE PID INSTELLINGEN]\n"
        f"- KP           : {pid['kp']}\n"
        f"- KD           : {pid['kd']}\n"
        f"- K_XTE        : {pid['k_xte']}\n"
        f"- KP_SNELHEID  : {pid['kp_snelheid']}\n"
        f"- KI_SNELHEID  : {pid['ki_snelheid']}\n"
        f"- LOOK_AHEAD   : {pid['look_ahead']} m\n\n" # <-- VOEGT DE UITGELEZEN LOOK-AHEAD AFSTAND TOE

        f"Analyseer dit en geef advies.\n"
        f"=================================================="
    )

    print(rapport_tekst)
    try:
        with open(rapport_pad, 'w', encoding='utf-8') as f_out:
            f_out.write(rapport_tekst)
        print(f"\n💾 Opgeslagen als: '{os.path.basename(rapport_pad)}'")
    except Exception as e:
        print(f"❌ Fout bij opslaan: {e}")


if __name__ == "__main__":
    genereer_ai_rapport(CSV_FILE, OUTPUT_REPORT, NAVIGATOR_PATH)