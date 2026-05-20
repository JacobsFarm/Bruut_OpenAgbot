import os
import csv
import folium

# ==========================================
# CONFIGURATIE
# ==========================================
# Vul hier ALLEEN de bestandsnaam in van de rit die je wilt zien
BESTANDSNAAM = "rit_2_20_05_2026.csv"

# --- SLIMME PADEN (Kijkt vanuit de Single_script_code map één map omhoog) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")

# Het volledige pad naar de CSV
CSV_FILE = os.path.join(LOG_DIR, BESTANDSNAAM) 

# Output wordt automatisch: [originele_naam]_route.html in dezelfde map
_base_name = os.path.splitext(BESTANDSNAAM)[0]
OUTPUT_MAP = os.path.join(LOG_DIR, f"{_base_name}_route.html")
# ==========================================

def genereer_route_kaart(csv_pad, output_pad):
    latitudes = []
    longitudes = []
    route_punten = []
    
    if not os.path.exists(csv_pad):
        print(f"❌ Fout: Bestand '{csv_pad}' niet gevonden!")
        print(f"💡 Zorg dat '{BESTANDSNAAM}' echt in de map 'data/logs' staat.")
        return
        
    print(f"📂 Bestand gevonden! We verwerken: {csv_pad}")

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
            except ValueError:
                pass

    if not route_punten:
        print("⚠️ Geen geldige GPS punten gevonden in de CSV.")
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
            xte = float(punt['XTE_Meters'])
            if abs(xte) > 0.5:
                kleur = "red"      
            elif abs(xte) > 0.2:
                kleur = "orange"   
            else:
                kleur = "green"    
        except (ValueError, KeyError):
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
                    <tr><td style="padding: 2px 0;"><b>Stuur (Turn):</b></td><td style="text-align: right;">{punt.get('Ruwe_Turn', '0')}</td></tr>
                    <tr><td style="padding: 2px 0;"><b>Gas Correctie:</b></td><td style="text-align: right;">{punt.get('Ruwe_PI_Corr', '0')}</td></tr>
                    <tr><td style="padding: 2px 0;"><b>DAC L/R:</b></td><td style="text-align: right;">{punt.get('DAC_Links', '0')} / {punt.get('DAC_Rechts', '0')}</td></tr>
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
    print(f"✅ Routekaart succesvol opgeslagen in de logs map als: '{output_pad}'")

if __name__ == "__main__":
    genereer_route_kaart(CSV_FILE, OUTPUT_MAP)