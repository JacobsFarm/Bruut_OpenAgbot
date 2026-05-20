import time
import math
import os
import csv
from datetime import datetime

# Importeer jouw bestaande hardware (zorg dat je dit runt vanuit de hoofdmap waar ook 'app' staat)
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.hardware import motor_controller, gps_system

def haversine(lat1, lon1, lat2, lon2):
    """Berekent afstand in meters tussen 2 coördinaten"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def run_mapper():
    print("\n" + "="*50)
    print("🚜 AGBOT THROTTLE MAPPER KALIBRATIE 🚜")
    print("="*50)
    print("WAARSCHUWING: De robot gaat zometeen in een rechte lijn vooruit rijden!")
    print("Hij accelereert langzaam van stilstand tot topsnelheid.")
    print("Zorg dat je MINIMAAL 30 meter vrije ruimte recht voor de robot hebt.")
    print("Druk op CTRL+C om op elk moment een NOODSTOP (DAC 700) te maken.\n")
    
    input("Druk op ENTER om de kalibratie te starten...")

    # Instellingen voor de test
    start_pwm = 700
    max_pwm = 3100
    stap_grootte = 100   # Verhoog de motor elke stap met 100 DAC
    wacht_tijd = 1.5     # Geef de robot 1.5 seconde om op die specifieke snelheid te komen

    # Wacht op geldige RTK GPS data
    print("[KALIBRATIE] Wachten op GPS fix...")
    while gps_system.current_position["lat"] == 0.0:
        time.sleep(0.5)
    print("[KALIBRATIE] GPS Fix Gevonden! We gaan beginnen over 3 seconden...")
    time.sleep(3)

    # Logger setup
    log_dir = "data/logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"throttle_map_{timestamp}.csv")

    try:
        with open(log_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["DAC_Waarde", "Snelheid_Meters_Per_Seconde"])

            for actuele_pwm in range(start_pwm, max_pwm + 1, stap_grootte):
                print(f"-> Testen DAC Waarde: {actuele_pwm}")
                
                # 1. Zet motoren op de test-waarde
                motor_controller.stuur_motoren(actuele_pwm, actuele_pwm)
                
                # 2. Laat hem even op gang komen en stabiliseer de snelheid
                time.sleep(wacht_tijd)
                
                # 3. Start meting
                start_pos = dict(gps_system.current_position)
                
                # 4. Rij precies 1.0 seconde op deze snelheid
                time.sleep(1.0)
                
                # 5. Stop meting
                eind_pos = dict(gps_system.current_position)
                
                # 6. Bereken de fysieke snelheid (meters afgelegd in die 1.0 seconde)
                snelheid_ms = haversine(start_pos["lat"], start_pos["lon"], eind_pos["lat"], eind_pos["lon"])
                
                print(f"   Resultaat: {snelheid_ms:.2f} m/s")
                writer.writerow([actuele_pwm, round(snelheid_ms, 3)])

    except KeyboardInterrupt:
        print("\n[NOODSTOP] Geannuleerd door gebruiker!")
    except Exception as e:
        print(f"\n[FOUT] Er ging iets mis: {e}")
    finally:
        # Altijd stoppen, zelfs bij een crash!
        print("[KALIBRATIE] Test klaar. Motoren uitschakelen (DAC 700).")
        motor_controller.stuur_motoren(700, 700)
        print(f"[KALIBRATIE] Data succesvol opgeslagen in: {log_file}")

if __name__ == "__main__":
    run_mapper()