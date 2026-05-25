import os
import csv
import math

# ==========================================
# CONFIGURATION
# ==========================================
# --- SMART PATHS ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")
NAVIGATOR_PATH = os.path.join(PROJECT_ROOT, "app", "services", "navigator.py")

# ------------------------------------------
# CHOOSE YOUR MODE
# ------------------------------------------
# By default, this is False, meaning it will only process 'FILE_NAME'.
# Remove the hash (#) on the line below to process ALL files in the directory!

PROCESS_ENTIRE_FOLDER = True

# If PROCESS_ENTIRE_FOLDER is False, only this file will be used:
FILE_NAME = "rit_1_20_05_2026.csv" 
# ==========================================

# --- Helper functions ---

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates distance in meters between two GPS coordinates."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def angle_difference(h1, h2):
    """Calculates the shortest difference between two headings (-180 to +180)."""
    diff = (h2 - h1 + 180) % 360 - 180
    return diff

def percentile(sorted_list, p):
    """Returns the p-th percentile of a sorted list."""
    if not sorted_list:
        return 0.0
    idx = (len(sorted_list) - 1) * p / 100
    low = int(idx)
    high = min(low + 1, len(sorted_list) - 1)
    return sorted_list[low] + (sorted_list[high] - sorted_list[low]) * (idx - low)

def get_live_parameters_from_navigator(nav_path):
    params = {
        "kp": "N/A", "kd": "N/A", "k_xte": "N/A",
        "kp_snelheid": "N/A", "ki_snelheid": "N/A",
        "look_ahead": "N/A"
    }
    if not os.path.exists(nav_path):
        return params
    try:
        with open(nav_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    continue
                # Keeping the search strings intact as they match the actual python file
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
                elif "self.look_ahead_dist =" in line: 
                    params["look_ahead"] = line.split("=")[1].split("#")[0].strip()
    except:
        pass
    return params

def generate_ai_report(csv_path, report_path, nav_path):
    file_short = os.path.basename(csv_path)
    
    if not os.path.exists(csv_path):
        print(f"❌ Error: Log file '{file_short}' not found!")
        return

    print(f"📂 Processing file: {file_short}")
    pid = get_live_parameters_from_navigator(nav_path)

    # --- Counters & lists ---
    total_rows = 0

    # Existing metrics
    xte_signed_list = []          
    xte_abs_list = []
    error_list = []
    speed_target_list, speed_real_list = [], []
    dt_list, turn_list, i_term_list = [], [], []
    dac_diff_list, dac_avg_list = [], []
    fix_ok_count = 0
    steer_maxed_count = 0
    stutter_count = 0
    high_deviation_count = 0

    # New metrics
    hdop_list = []
    hdop_bad_count = 0              
    heading_error_signed = []       
    pi_corr_list = []                 
    dist_wp_list = []              
    wp_visits = {}                   
    gps_coords = []                    
    i_term_positive = 0                
    i_term_negative = 0
    large_i_term_count = 0             
    pi_corr_high_count = 0            
    stagnation_count = 0                
    dac_asymmetry_high_count = 0      
    xte_left_count = 0               
    xte_right_count = 0              
    
    # Tracking for look-ahead data in CSV
    lookahead_data_present = False

    I_TERM_THRESHOLD = 5.0
    PI_CORR_THRESHOLD = 200.0
    DAC_ASYM_THRESHOLD = 300

    with_valid_gps = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Reading CSV columns (Keeping the original Dutch header names)
                xte_signed = float(row['XTE_Meters'])
                xte = abs(xte_signed)
                fout = abs(float(row['Fout_Graden']))
                speed_target = float(row['Snelheid_Doel_kmh'])
                speed_real = float(row['Snelheid_Echt_kmh'])
                dt = float(row['Delta_Tijd_Sec'])
                turn = abs(float(row['Ruwe_Turn']))
                i_term = float(row['PI_Integraal'])
                fix = int(row['Fix'])
                dac_l = int(row['DAC_Links'])
                dac_r = int(row['DAC_Rechts'])
                hdop = float(row['HDOP'])
                heading = float(row['Heading'])
                target_heading = float(row['Doel_Heading'])
                pi_corr = float(row['Ruwe_PI_Corr'])
                dist_wp = float(row['Afstand_tot_WP'])
                wp_idx = int(row['WP_Doel'])
                lat = float(row['Lat'])
                lon = float(row['Lon'])
                
                # Check if look-ahead data is in this row/CSV (safe extraction)
                la_lat = row.get('Lookahead_Lat', '')
                la_lon = row.get('Lookahead_Lon', '')
                if la_lat and la_lon:
                    lookahead_data_present = True

                # --- Fill lists ---
                xte_signed_list.append(xte_signed)
                xte_abs_list.append(xte)
                error_list.append(fout)
                speed_target_list.append(speed_target)
                speed_real_list.append(speed_real)
                dt_list.append(dt)
                turn_list.append(turn)
                i_term_list.append(abs(i_term))
                hdop_list.append(hdop)
                pi_corr_list.append(abs(pi_corr))
                dist_wp_list.append(dist_wp)
                gps_coords.append((lat, lon))

                # Signed heading error
                h_error = angle_difference(target_heading, heading)
                heading_error_signed.append(h_error)

                # DAC calculations
                dac_diff = abs(dac_l - dac_r)
                dac_avg = (dac_l + dac_r) / 2
                dac_diff_list.append(dac_diff)
                dac_avg_list.append(dac_avg)

                total_rows += 1

                # --- Counters ---
                if xte > 0.20:
                    high_deviation_count += 1
                if fix == 4:
                    fix_ok_count += 1
                    with_valid_gps += 1
                if turn >= 390:
                    steer_maxed_count += 1
                if dt > 0.15:
                    stutter_count += 1
                if hdop > 1.5:
                    hdop_bad_count += 1
                if i_term > 0:
                    i_term_positive += 1
                else:
                    i_term_negative += 1
                if abs(i_term) > I_TERM_THRESHOLD:
                    large_i_term_count += 1
                if abs(pi_corr) > PI_CORR_THRESHOLD:
                    pi_corr_high_count += 1
                if dac_diff > DAC_ASYM_THRESHOLD:
                    dac_asymmetry_high_count += 1
                if speed_target > 0 and speed_real < 0.1:
                    stagnation_count += 1
                if xte_signed > 0:
                    xte_right_count += 1
                elif xte_signed < 0:
                    xte_left_count += 1

                # Waypoint tracking
                if wp_idx not in wp_visits:
                    wp_visits[wp_idx] = 0
                wp_visits[wp_idx] += 1

            except (ValueError, KeyError):
                pass

    if total_rows == 0:
        print(f"❌ No valid rows found in CSV file: {file_short}.")
        return

    # --- Post-processing ---
    total_distance_m = 0.0
    for i in range(1, len(gps_coords)):
        total_distance_m += haversine_distance(
            gps_coords[i - 1][0], gps_coords[i - 1][1],
            gps_coords[i][0], gps_coords[i][1]
        )

    total_time_sec = sum(dt_list)
    minutes = int(total_time_sec // 60)
    seconds = total_time_sec % 60
    avg_time_per_wp = (total_time_sec / max(len(wp_visits), 1))
    speed_error_list = [abs(t - r) for t, r in zip(speed_target_list, speed_real_list)]

    xte_sorted = sorted(xte_abs_list)
    xte_p90 = percentile(xte_sorted, 90)
    xte_p95 = percentile(xte_sorted, 95)

    avg_heading_error = sum(heading_error_signed) / len(heading_error_signed)
    heading_bias_direction = "RIGHT (robot turns too far CW)" if avg_heading_error > 0.5 else \
                             "LEFT (robot turns too far CCW)" if avg_heading_error < -0.5 else \
                             "No significant bias"

    xte_bias = "RIGHT of line" if xte_right_count > xte_left_count * 1.2 else \
               "LEFT of line" if xte_left_count > xte_right_count * 1.2 else \
               "No clear bias"

    if i_term_positive > i_term_negative * 1.5:
        windup_direction = "Positive (structural under-correction)"
    elif i_term_negative > i_term_positive * 1.5:
        windup_direction = "Negative (structural over-correction)"
    else:
        windup_direction = "Balanced"

    avg_speed_efficiency = (sum(speed_real_list) / max(sum(speed_target_list), 0.001)) * 100

    # Look-ahead status string
    la_status = "Present" if lookahead_data_present else "Not registered (Old log)"

    # ==========================================
    # BUILD REPORT
    # ==========================================
    report_text = (
        f"==================================================\n"
        f"🤖 TELEMETRY ANALYSIS: {os.path.basename(csv_path)}\n"
        f"==================================================\n\n"

        f"[DRIVE OVERVIEW]\n"
        f"- Total rows        : {total_rows}\n"
        f"- Drive time        : {minutes}m {seconds:.1f}s ({total_time_sec:.1f} sec total)\n"
        f"- Distance driven   : {total_distance_m:.1f} m  ({total_distance_m / 1000:.3f} km)\n"
        f"- Waypoints reached : {len(wp_visits)}  (indices: {sorted(wp_visits.keys())})\n"
        f"- Avg. time per WP  : {avg_time_per_wp:.1f} s\n"
        f"- Look-Ahead Coords : {la_status} in CSV\n\n" 

        f"[LINE TRACKING]\n"
        f"- XTE Average       : {sum(xte_abs_list)/len(xte_abs_list):.3f} m\n"
        f"- XTE Maximum       : {max(xte_abs_list):.3f} m\n"
        f"- XTE P90           : {xte_p90:.3f} m  (90% of readings below this)\n"
        f"- XTE P95           : {xte_p95:.3f} m\n"
        f"- XTE Bias Side     : {xte_bias}\n"
        f"    Left ({xte_left_count}x) vs Right ({xte_right_count}x)\n"
        f"- Instability       : {(high_deviation_count / total_rows) * 100:.1f} % of the drive (XTE > 0.20m)\n\n"

        f"[HEADING & ORIENTATION]\n"
        f"- Angle Error Avg   : {sum(error_list)/len(error_list):.1f}°\n"
        f"- Angle Error Max   : {max(error_list):.1f}°\n"
        f"- Heading Bias      : {avg_heading_error:+.2f}°  → {heading_bias_direction}\n"
        f"    (Positive = robot is heading right of target course)\n\n"

        f"[SPEED & EFFICIENCY]\n"
        f"- Speed Real Avg    : {sum(speed_real_list)/len(speed_real_list):.2f} km/h\n"
        f"- Speed Target Avg  : {sum(speed_target_list)/len(speed_target_list):.2f} km/h\n"
        f"- Speed Error Avg   : {sum(speed_error_list)/len(speed_error_list):.2f} km/h\n"
        f"- Speed Efficiency  : {avg_speed_efficiency:.1f} % of target speed achieved\n"
        f"- Stagnation        : {(stagnation_count / total_rows) * 100:.1f} % (target speed > 0 but standing still)\n\n"

        f"[STEERING SYSTEM & PI CONTROLLER]\n"
        f"- DAC Difference Avg: {sum(dac_diff_list)/len(dac_diff_list):.1f}  (Steering intensity)\n"
        f"- DAC Load Avg      : {sum(dac_avg_list)/len(dac_avg_list):.1f}  (Motor Load)\n"
        f"- Steering Limit    : {(steer_maxed_count / total_rows) * 100:.1f} % of the time (turn >= 390)\n"
        f"- PI Corr. Avg      : {sum(pi_corr_list)/len(pi_corr_list):.1f}  (Raw correction)\n"
        f"- PI Corr. High     : {(pi_corr_high_count / total_rows) * 100:.1f} % (|corr| > {PI_CORR_THRESHOLD})\n"
        f"- Integral Windup   : {windup_direction}\n"
        f"- Large I-term      : {(large_i_term_count / total_rows) * 100:.1f} % (|I| > {I_TERM_THRESHOLD})\n"
        f"- DAC Asymmetry >   : {(dac_asymmetry_high_count / total_rows) * 100:.1f} % (difference > {DAC_ASYM_THRESHOLD} DAC)\n\n"

        f"[GPS & SYSTEM HEALTH]\n"
        f"- GPS RTK Fix (4)   : {(fix_ok_count / total_rows) * 100:.1f} %\n"
        f"- HDOP Average      : {sum(hdop_list)/len(hdop_list):.2f}  (ideal < 1.0)\n"
        f"- HDOP Bad          : {(hdop_bad_count / total_rows) * 100:.1f} % (HDOP > 1.5)\n"
        f"- Loop Time Avg     : {sum(dt_list)/len(dt_list):.3f} s\n"
        f"- Loop Time Max     : {max(dt_list):.3f} s\n"
        f"- CPU Stutter       : {(stutter_count / total_rows) * 100:.1f} % (dt > 150ms)\n\n"

        f"[CURRENT PID SETTINGS]\n"
        f"- KP           : {pid['kp']}\n"
        f"- KD           : {pid['kd']}\n"
        f"- K_XTE        : {pid['k_xte']}\n"
        f"- KP_SPEED     : {pid['kp_snelheid']}\n"
        f"- KI_SPEED     : {pid['ki_snelheid']}\n"
        f"- LOOK_AHEAD   : {pid['look_ahead']} m\n\n" 

        f"Analyze this and provide recommendations.\n"
        f"=================================================="
    )

    print(report_text)
    try:
        with open(report_path, 'w', encoding='utf-8') as f_out:
            f_out.write(report_text)
        print(f"💾 Saved as: '{os.path.basename(report_path)}'\n")
    except Exception as e:
        print(f"❌ Error saving report: {e}")

if __name__ == "__main__":
    if PROCESS_ENTIRE_FOLDER:
        print(f"🔍 Searching for all CSV files in: {LOG_DIR}")
        csv_files = [f for f in os.listdir(LOG_DIR) if f.endswith('.csv')]
        
        if not csv_files:
            print("⚠️ No .csv files found in the log directory.")
        else:
            for file_name in csv_files:
                csv_path = os.path.join(LOG_DIR, file_name)
                base_name = os.path.splitext(file_name)[0]
                output_report = os.path.join(LOG_DIR, f"{base_name}_extracted_data.txt")
                generate_ai_report(csv_path, output_report, NAVIGATOR_PATH)
            print(f"🎉 Done! All {len(csv_files)} files have been processed successfully.")
    else:
        CSV_FILE_PATH = os.path.join(LOG_DIR, FILE_NAME)
        _base_name = os.path.splitext(FILE_NAME)[0]
        OUTPUT_REPORT_PATH = os.path.join(LOG_DIR, f"{_base_name}_extracted_data.txt")
        generate_ai_report(CSV_FILE_PATH, OUTPUT_REPORT_PATH, NAVIGATOR_PATH)