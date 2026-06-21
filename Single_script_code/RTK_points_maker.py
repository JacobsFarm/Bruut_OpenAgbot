import json
import math
import os
import matplotlib.pyplot as plt
import folium  # Zorg dat deze is geïnstalleerd via je terminal: pip install folium

# ==========================================
# ⚙️ CONFIGURATIE PARAMETERS
# ==========================================
# Lijn 1 (De basislijn waar de missie start)
START_LAT = 52.000000       # Beginpunt Lat
START_LON = 4.000000        # Beginpunt Lon
EIND_LAT = 52.001000        # Eindpunt Lat (Bepaalt de richting en lengte)
EIND_LON = 4.001000         # Eindpunt Lon

WERKBREEDTE_M = 5.0         # Breedte van één werkgang in meters
AANTAL_RIJEN = 8            # Totaal aantal rijen om te genereren

OUTPUT_JSON = "waypoints.json"
OUTPUT_KAART = "mission_plan.jpg"
OUTPUT_HTML = "mission_plan.html"

# ==========================================
# 🛠️ HULPFUNCTIES VOOR COÖRDINATEN
# ==========================================
def haal_punt_op_afstand(lat, lon, offset_x_meters, offset_y_meters):
    """Berekent een nieuw GPS coordinaat gebaseerd op een x/y offset in meters."""
    R_AARDE = 6378137.0 # Radius van de aarde in meters
    
    # Verschuiving in graden
    delta_lat = (offset_y_meters / R_AARDE) * (180.0 / math.pi)
    delta_lon = (offset_x_meters / (R_AARDE * math.cos(math.pi * lat / 180.0))) * (180.0 / math.pi)
    
    return lat + delta_lat, lon + delta_lon

def bereken_richting_vectoren(lat1, lon1, lat2, lon2):
    """Berekent de vooruit- en rechts-vectoren gebaseerd op punt 1 naar punt 2."""
    R_AARDE = 6378137.0
    
    # Delta in meters tussen start en eind
    dy = (lat2 - lat1) * (math.pi / 180.0) * R_AARDE
    dx = (lon2 - lon1) * (math.pi / 180.0) * R_AARDE * math.cos(math.pi * lat1 / 180.0)
    
    lengte = math.sqrt(dx**2 + dy**2)
    if lengte == 0:
        return 0, 0, 0, 0
        
    # Vooruit vector (unit vector)
    u_x = dx / lengte
    u_y = dy / lengte
    
    # Rechts vector (90 graden gedraaid ten opzichte van vooruit)
    r_x = u_y
    r_y = -u_x
    
    return u_x, u_y, r_x, r_y

# ==========================================
# 🚀 HOOFDPROGRAMMA
# ==========================================
def genereer_missie():
    print(f"🚜 Start met genereren van {AANTAL_RIJEN} rijen (Breedte: {WERKBREEDTE_M}m)...")
    
    _, _, r_x, r_y = bereken_richting_vectoren(START_LAT, START_LON, EIND_LAT, EIND_LON)
    
    waypoints = []
    teller = 1
    
    # Splits rijen in Even (heenwerkend) en Oneven (terugwerkend)
    even_rijen = [i for i in range(AANTAL_RIJEN) if i % 2 == 0]
    oneven_rijen = [i for i in range(AANTAL_RIJEN) if i % 2 != 0]
    
    # Draai de oneven rijen om, zodat we van rechts weer naar links werken (richting start)
    oneven_rijen.reverse()
    
    uitvoer_volgorde = even_rijen + oneven_rijen
    kant = 'onder' # Houdt bij of we aan de start-kant of eind-kant staan
    
    for rij_index in uitvoer_volgorde:
        verschuiving_meters = rij_index * WERKBREEDTE_M
        offset_x = verschuiving_meters * r_x
        offset_y = verschuiving_meters * r_y
        
        punt_onder = haal_punt_op_afstand(START_LAT, START_LON, offset_x, offset_y)
        punt_boven = haal_punt_op_afstand(EIND_LAT, EIND_LON, offset_x, offset_y)
        
        if kant == 'onder':
            waypoints.append({"way_point_name": f"point {teller}", "lat": punt_onder[0], "lon": punt_onder[1]})
            teller += 1
            waypoints.append({"way_point_name": f"point {teller}", "lat": punt_boven[0], "lon": punt_boven[1]})
            teller += 1
            kant = 'boven'
        else:
            waypoints.append({"way_point_name": f"point {teller}", "lat": punt_boven[0], "lon": punt_boven[1]})
            teller += 1
            waypoints.append({"way_point_name": f"point {teller}", "lat": punt_onder[0], "lon": punt_onder[1]})
            teller += 1
            kant = 'onder'

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(waypoints, f, indent=4)
    print(f"✅ Missie plan opgeslagen in '{OUTPUT_JSON}'")
    
    return waypoints

def genereer_statische_kaart(waypoints, output_pad):
    print("🗺️ Statische plot aan het tekenen...")
    lats = [wp['lat'] for wp in waypoints]
    lons = [wp['lon'] for wp in waypoints]

    fig, ax = plt.subplots(figsize=(8, 8))
    
    ax.plot(lons, lats, color='#2196F3', linewidth=2, alpha=0.7, label='Trekker Pad')
    ax.scatter(lons, lats, c='black', s=20, zorder=3)
    
    ax.scatter(lons[0], lats[0], c='green', s=150, marker='o', edgecolors='black', zorder=4, label='Start (Punt 1)')
    ax.scatter(lons[-1], lats[-1], c='red', s=150, marker='X', edgecolors='black', zorder=4, label='Eind')

    for i, wp in enumerate(waypoints):
        nummer = wp['way_point_name'].replace("point ", "P")
        ax.annotate(nummer, (wp['lon'], wp['lat']), textcoords="offset points", xytext=(5,5), ha='center', fontsize=8, color='darkblue')

    BUFFER_MARGE = 0.0002
    ax.set_xlim([min(lons) - BUFFER_MARGE, max(lons) + BUFFER_MARGE])
    ax.set_ylim([min(lats) - BUFFER_MARGE, max(lats) + BUFFER_MARGE])
    
    avg_lat = sum(lats) / len(lats)
    aspect_ratio = 1 / math.cos(math.radians(avg_lat))
    ax.set_aspect(aspect_ratio)

    ax.set_title(f"Missie Overzicht: {WERKBREEDTE_M}m werkbreedte, {AANTAL_RIJEN} rijen", fontsize=12, fontweight='bold', pad=15)
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.set_xlabel("Lengtegraad (Lon)", fontsize=9)
    ax.set_ylabel("Breedtegraad (Lat)", fontsize=9)
    ax.ticklabel_format(useOffset=False, style='plain') 
    ax.legend(loc='upper left', fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_pad, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"✅ Afbeelding opgeslagen: '{os.path.basename(output_pad)}'")

def genereer_html_veldkaart(waypoints, output_pad):
    print("🌍 Interactieve veldkaart (satelliet) aan het bouwen...")
    lats = [wp['lat'] for wp in waypoints]
    lons = [wp['lon'] for wp in waypoints]

    start_lat = sum(lats) / len(lats)
    start_lon = sum(lons) / len(lons)
    
    m = folium.Map(location=[start_lat, start_lon], zoom_start=18, max_zoom=22, tiles=None)

    # Voeg Satellietbeelden toe
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satelliet Weergave',
        max_zoom=22
    ).add_to(m)
    folium.TileLayer('OpenStreetMap', name='Wegenkaart').add_to(m)

    # Teken de route
    coords = list(zip(lats, lons))
    folium.PolyLine(coords, color="#00E5FF", weight=4, opacity=0.8, tooltip="Gepland Trekker Pad").add_to(m)

    # Teken de waypoints
    for i, wp in enumerate(waypoints):
        if i == 0:
            kleur = "green"  # Startpunt
        elif i == len(waypoints) - 1:
            kleur = "red"    # Eindpunt
        else:
            kleur = "orange" # Tussenpunten
            
        folium.CircleMarker(
            location=[wp['lat'], wp['lon']],
            radius=6,
            color="black",
            weight=1,
            fill=True,
            fill_color=kleur,
            fill_opacity=1.0,
            tooltip=f"<b>{wp['way_point_name']}</b><br>Lat: {wp['lat']:.6f}<br>Lon: {wp['lon']:.6f}"
        ).add_to(m)

    # Zoom in op het veld
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    folium.LayerControl().add_to(m)

    m.save(output_pad)
    print(f"✅ Interactieve HTML opgeslagen: '{os.path.basename(output_pad)}'")

if __name__ == "__main__":
    berekende_waypoints = genereer_missie()
    genereer_statische_kaart(berekende_waypoints, OUTPUT_KAART)
    genereer_html_veldkaart(berekende_waypoints, OUTPUT_HTML)
    print("🎉 Helemaal klaar! Open 'missie_overzicht.html' in je browser om de sloot-check te doen.")