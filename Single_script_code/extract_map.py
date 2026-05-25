import os
import csv
import math
import matplotlib.pyplot as plt

# ==========================================
# CONFIGURATION
# ==========================================
# --- SMART PATHS ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

# ------------------------------------------
# CHOOSE YOUR MODE & FORMAT
# ------------------------------------------
PROCESS_ENTIRE_FOLDER = True
FILE_NAME = "rit_1_20_05_2026.csv"

# Choose how you want to save the file below: 'jpg', 'pdf', or 'png'
FILE_FORMAT = 'jpg'

# How much margin/buffer do you want around the route?
# (This is the 'border' beyond the route. 0.0002 is approx. 20-25 meters of extra space)
BUFFER_MARGIN = 0.0002 
# ==========================================

def generate_static_route(csv_path, output_path):
    file_short = os.path.basename(csv_path)
    
    if not os.path.exists(csv_path):
        print(f"❌ Error: File '{csv_path}' not found!")
        return
        
    print(f"📂 Reading file: {file_short}")

    lats = []
    lons = []
    colors = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Note: Keeping original Dutch header keys to match your CSV
                lat = float(row['Lat'])
                lon = float(row['Lon'])
                
                if lat == 0.0 or lon == 0.0:
                    continue
                    
                xte = float(row.get('XTE_Meters', 0))
                
                # Color coding based on the deviation (XTE)
                if abs(xte) > 0.5:
                    colors.append('red')
                elif abs(xte) > 0.2:
                    colors.append('orange')
                else:
                    colors.append('green')
                    
                lats.append(lat)
                lons.append(lon)
            except (ValueError, KeyError):
                pass

    if not lats:
        print(f"⚠️ No valid GPS points found in {file_short}.")
        return

    # --- Create the plot! ---
    # We create a canvas (e.g., 8 by 8 inches)
    fig, ax = plt.subplots(figsize=(8, 8))
    
    # 1. Draw the route as a soft blue line
    ax.plot(lons, lats, color='#2196F3', linewidth=2, alpha=0.5, label='Route')
    
    # 2. Draw the points on top (with the green/orange/red colors)
    ax.scatter(lons, lats, c=colors, s=12, zorder=3, edgecolors='none')
    
    # 3. Mark the start and end points to finish it off
    ax.scatter(lons[0], lats[0], c='blue', s=120, marker='o', edgecolors='black', zorder=4, label='Start')
    ax.scatter(lons[-1], lats[-1], c='black', s=120, marker='X', edgecolors='white', zorder=4, label='End')

    # --- CREATE THE BUFFER MARGIN ---
    # We find the extreme coordinates driven and add the margin to them!
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    ax.set_xlim([min_lon - BUFFER_MARGIN, max_lon + BUFFER_MARGIN])
    ax.set_ylim([min_lat - BUFFER_MARGIN, max_lat + BUFFER_MARGIN])
    
    # Correct the aspect ratio (Ensures the route isn't flattened by the earth's curvature)
    avg_lat = sum(lats) / len(lats)
    aspect_ratio = 1 / math.cos(math.radians(avg_lat))
    ax.set_aspect(aspect_ratio)

    # Clean up axes (Add a grid for scale)
    ax.set_title(f"Route Overview: {file_short}", fontsize=12, fontweight='bold', pad=15)
    ax.grid(True, linestyle=':', alpha=0.6)
    
    ax.set_xlabel("Longitude (Lon)", fontsize=9)
    ax.set_ylabel("Latitude (Lat)", fontsize=9)
    # Ensures coordinates don't get rounded or put in scientific notation
    ax.ticklabel_format(useOffset=False, style='plain') 
    
    ax.legend(loc='upper right', fontsize=9)
    
    # bbox_inches='tight' automatically removes large excess white borders
    plt.tight_layout()

    # Save the file
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    plt.close() # Prevents memory leaks if you process the entire folder
    
    print(f"✅ Saved as {FILE_FORMAT.upper()}: '{os.path.basename(output_path)}'\n")


if __name__ == "__main__":
    # Check if we have the library installed
    try:
        import matplotlib
    except ImportError:
        print("❌ 'matplotlib' is not installed. Run: pip install matplotlib")
        exit()

    if PROCESS_ENTIRE_FOLDER:
        print(f"🔍 Searching for all CSV files in: {LOG_DIR}")
        csv_files = [f for f in os.listdir(LOG_DIR) if f.endswith('.csv')]
        
        if not csv_files:
            print("⚠️ No .csv files found in the log directory.")
        else:
            for file_name in csv_files:
                csv_path = os.path.join(LOG_DIR, file_name)
                base_name = os.path.splitext(file_name)[0]
                output_path = os.path.join(LOG_DIR, f"{base_name}_route_map.{FILE_FORMAT}")
                generate_static_route(csv_path, output_path)
            print(f"🎉 Done! All files have been converted to {FILE_FORMAT.upper()}.")
    else:
        CSV_FILE_PATH = os.path.join(LOG_DIR, FILE_NAME) 
        _base_name = os.path.splitext(FILE_NAME)[0]
        OUTPUT_MAP_PATH = os.path.join(LOG_DIR, f"{_base_name}_route_map.{FILE_FORMAT}")
        generate_static_route(CSV_FILE_PATH, OUTPUT_MAP_PATH)