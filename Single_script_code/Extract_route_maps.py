import os
import csv
import math
import folium
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

VERWERK_HELE_MAP = True
BESTANDSNAAM = "rit_2_20_05_2026.csv"

BESTANDSFORMAAT = 'jpg'
BUFFER_MARGE = 0.0002 

def genereer_html_kaart(csv_pad, output_pad):
    latitudes = []
    longitudes = []
    route_punten = []
    
    with open(csv_pad, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row['Lat'])
                lon = float(row['Lon'])
                
                if lat == 0.0 or lon == 0.0:
                    continue
                    
                latitudes.append(lat)
                longitudes.append(lon)
                route_punten.append(row)
            except (ValueError, KeyError, TypeError):
                pass

    if not route_punten:
        return

    start_lat = sum(latitudes) / len(latitudes)
    start_lon = sum(longitudes) / len(longitudes)
    m = folium.Map(location=[start_lat, start_lon], zoom_start=18, max_zoom=21)

    coords = list(zip(latitudes, longitudes))
    folium.PolyLine(
        coords,
        color="#2196F3", 
        weight=4,
        opacity=0.7,
        tooltip="Gereden Route"
    ).add_to(m)

    stapgrootte = max(1, len(route_punten) // 500) 
    
    for i in range(0, len(route_punten), stapgrootte):
        punt = route_punten[i]
        lat = float(punt['Lat'])
        lon = float(punt['Lon'])
        
        try:
            xte = float(punt.get('XTE_Meters', 0))
            if abs(xte) > 0.5:
                kleur = "red"      
            elif abs(xte) > 0.2:
                kleur = "orange"   
            else:
                kleur = "green"    
        except (ValueError, KeyError, TypeError):
            kleur = "gray"
            
        hover_html = f'''
            <div style="width: 280px; font-family: sans-serif; padding: 5px;">
                <h4 style="margin-top: 0; margin-bottom: 8px; color: #333; border-bottom: 1px solid #ccc; padding-bottom: 4px;">
                    ⏱️ Tijdstip: {punt.get('Tijdstip', 'N/B')}
                </h4>
                <table style="width: 100%; font-size: 13px; color: #444; border-collapse: collapse;">
                    <tr><td style="padding: 2px 0;"><b>Snelheid (Doel/Echt):</b></td><td style="text-align: right;">{punt.get('Snelheid_Doel_kmh', '0')} / {punt.get('Snelheid_Echt_kmh', '0')} km/h</td></tr>
                    <tr><td style="padding: 2px 0;"><b>Afwijking (XTE):</b></td><td style="text-align: right; color: {kleur}; font-weight: bold;">{punt.get('XTE_Meters', '0')} m</td></tr>
                    <tr><td style="padding: 2px 0;"><b>Fout (Hoek):</b></td><td style="text-align: right;">{punt.get('Fout_Graden', '0')}°</td></tr>
                    <tr><td style="padding: 2px 0;"><b>RTK Fix:</b></td><td style="text-align: right;">{punt.get('Fix', 'N/B')} (HDOP: {punt.get('HDOP', 'N/B')})</td></tr>
                </table>
            </div>
        '''
        
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="black",
            weight=1,
            fill=True,
            fill_color=kleur,
            fill_opacity=0.9,
            tooltip=hover_html
        ).add_to(m)

    folium.Marker([latitudes[0], longitudes[0]], tooltip="Startpunt", icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker([latitudes[-1], longitudes[-1]], tooltip="Eindpunt", icon=folium.Icon(color="red", icon="stop")).add_to(m)

    m.fit_bounds([[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]])

    m.save(output_pad)
    print(f"✅ HTML opgeslagen: '{os.path.basename(output_pad)}'")

def genereer_statische_kaart(csv_pad, output_pad):
    lats = []
    lons = []
    colors = []
    
    with open(csv_pad, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row['Lat'])
                lon = float(row['Lon'])
                
                if lat == 0.0 or lon == 0.0:
                    continue
                    
                xte = float(row.get('XTE_Meters', 0))
                
                if abs(xte) > 0.5:
                    colors.append('red')
                elif abs(xte) > 0.2:
                    colors.append('orange')
                else:
                    colors.append('green')
                    
                lats.append(lat)
                lons.append(lon)
            except (ValueError, KeyError, TypeError):
                pass

    if not lats:
        return

    fig, ax = plt.subplots(figsize=(8, 8))
    
    ax.plot(lons, lats, color='#2196F3', linewidth=2, alpha=0.5, label='Route')
    ax.scatter(lons, lats, c=colors, s=12, zorder=3, edgecolors='none')
    
    ax.scatter(lons[0], lats[0], c='blue', s=120, marker='o', edgecolors='black', zorder=4, label='Start')
    ax.scatter(lons[-1], lats[-1], c='black', s=120, marker='X', edgecolors='white', zorder=4, label='Eind')

    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    ax.set_xlim([min_lon - BUFFER_MARGE, max_lon + BUFFER_MARGE])
    ax.set_ylim([min_lat - BUFFER_MARGE, max_lat + BUFFER_MARGE])
    
    avg_lat = sum(lats) / len(lats)
    aspect_ratio = 1 / math.cos(math.radians(avg_lat))
    ax.set_aspect(aspect_ratio)

    bestand_kort = os.path.basename(csv_pad)
    ax.set_title(f"Route Overzicht: {bestand_kort}", fontsize=12, fontweight='bold', pad=15)
    ax.grid(True, linestyle=':', alpha=0.6)
    
    ax.set_xlabel("Lengtegraad (Lon)", fontsize=9)
    ax.set_ylabel("Breedtegraad (Lat)", fontsize=9)
    ax.ticklabel_format(useOffset=False, style='plain') 
    ax.legend(loc='upper right', fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_pad, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"✅ Afbeelding opgeslagen: '{os.path.basename(output_pad)}'")

def verwerk_bestand(csv_pad):
    bestand_kort = os.path.basename(csv_pad)
    if not os.path.exists(csv_pad):
        print(f"❌ Fout: Bestand '{csv_pad}' niet gevonden!")
        return

    print(f"📂 Bezig met: {bestand_kort} ...")
    
    base_name = os.path.splitext(bestand_kort)[0]
    output_html = os.path.join(LOG_DIR, f"{base_name}_route.html")
    output_img = os.path.join(LOG_DIR, f"{base_name}_route_kaart.{BESTANDSFORMAAT}")
    
    genereer_html_kaart(csv_pad, output_html)
    genereer_statische_kaart(csv_pad, output_img)
    print("-" * 40)

if __name__ == "__main__":
    if VERWERK_HELE_MAP:
        print(f"🔍 Zoeken naar alle CSV bestanden in: {LOG_DIR}\n")
        csv_bestanden = [b for b in os.listdir(LOG_DIR) if b.endswith('.csv')]
        
        if not csv_bestanden:
            print("⚠️ Geen .csv bestanden gevonden in de log map.")
        else:
            for bestand in csv_bestanden:
                csv_pad = os.path.join(LOG_DIR, bestand)
                verwerk_bestand(csv_pad)
            print(f"🎉 Klaar! Alle {len(csv_bestanden)} bestanden zijn succesvol verwerkt.")
    else:
        CSV_FILE_PATH = os.path.join(LOG_DIR, BESTANDSNAAM)
        verwerk_bestand(CSV_FILE_PATH)
        print("🎉 Klaar!")