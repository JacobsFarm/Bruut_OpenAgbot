import os
import json
import folium
import base64
from glob import glob

# ==========================================
# CONFIGURATION PARAMETERS
# ==========================================
# File Paths
DATA_FOLDER = os.path.join(".", "data")  # Directory containing .json and .jpg files
OUTPUT_FILE = "detection_map.html"       # Output filename

# Fallback Map Settings (used if no detections are found)
FALLBACK_LAT = 52.2128                 
FALLBACK_LON = 4.5914                  
MAP_START_ZOOM = 18                      
MAP_MAX_ZOOM = 21                        
# ==========================================

def image_to_base64(image_path):
    """Converts an image file to a base64 encoded string."""
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:image/jpeg;base64,{encoded_string}"

def get_first_valid_coords(json_files):
    """Scans JSON files to find the first available GPS coordinates."""
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                lat = data.get("gps_lat")
                lon = data.get("gps_lon")
                if lat is not None and lon is not None:
                    return [lat, lon]
        except Exception:
            continue
    return None

def create_interactive_map(data_folder, output_html):
    """Generates an interactive map, centered on the first detection."""
    print("Searching for data and calculating start position...")
    
    # Find all .json files
    json_files = glob(os.path.join(data_folder, "*.json"))
    
    # Determine the starting center of the map
    first_coords = get_first_valid_coords(json_files)
    if first_coords:
        start_location = first_coords
        print(f"Map will start at first detection: {start_location}")
    else:
        start_location = [FALLBACK_LAT, FALLBACK_LON]
        print(f"No detections found. Using fallback location: {start_location}")

    # Initialize Map
    m = folium.Map(
        location=start_location, 
        zoom_start=MAP_START_ZOOM,
        max_zoom=MAP_MAX_ZOOM,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
    )
    
    latitudes = []
    longitudes = []
    point_count = 0

    for json_file in json_files:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        item_id = data.get("id")
        lat = data.get("gps_lat")
        lon = data.get("gps_lon")
        class_name = data.get("class_name", "Unknown")
        confidence = data.get("confidence", 0)
        
        if lat is None or lon is None or item_id is None:
            continue
            
        latitudes.append(lat)
        longitudes.append(lon)
        
        # Color logic
        if confidence > 0.8: marker_color = "darkgreen"
        elif confidence > 0.7: marker_color = "lightgreen"
        elif confidence > 0.6: marker_color = "orange"
        else: marker_color = "red"
        
        # Image handling
        image_files = glob(os.path.join(data_folder, f"{item_id}*.jpg"))
        if image_files:
            image_path = image_files[0]
            b64_image = image_to_base64(image_path)
            
            hover_html = f'''
                <div style="width: 300px; font-family: sans-serif;">
                    <h4 style="margin-bottom: 5px;">{class_name}</h4>
                    <p style="margin-top: 0; font-size: 12px; color: gray;">
                        ID: {item_id}<br>
                        Confidence: {round(confidence * 100, 1)}%
                    </p>
                    <img src="{b64_image}" style="width: 100%; border-radius: 5px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
                </div>
            '''
            
            folium.Marker(
                location=[lat, lon],
                tooltip=hover_html,
                icon=folium.Icon(color=marker_color, icon="leaf")
            ).add_to(m)
            point_count += 1

    # Fit bounds to show all points if multiple points exist
    if latitudes and longitudes:
        m.fit_bounds([[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]])

    m.save(output_html)
    print(f"Done! Map saved as '{output_html}' with {point_count} points.")

if __name__ == "__main__":
    os.makedirs(DATA_FOLDER, exist_ok=True)
    create_interactive_map(data_folder=DATA_FOLDER, output_html=OUTPUT_FILE)