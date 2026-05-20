import os
import csv
from datetime import datetime

class DriveLogger:
    def __init__(self):
        self.log_file = None
        self.log_dir = os.path.join('data', 'logs')
        
        # Maak de mappenstructuur aan als deze nog niet bestaat
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def start_nieuwe_rit(self):
        """Maakt een nieuw CSV bestand aan met de uitgebreide headers"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"rit_{timestamp}.csv")
        
        try:
            with open(self.log_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Tijdstip", "WP_Doel", "Lat", "Lon", 
                    "Fix", "HDOP",
                    "Heading", "Doel_Heading", "Fout_Graden", "XTE_Meters", 
                    "Snelheid_Doel_kmh", "Snelheid_Echt_kmh",
                    "Ruwe_Turn", "Ruwe_PI_Corr", "PI_Integraal",
                    "DAC_Links", "DAC_Rechts", "Afstand_tot_WP", 
                    "Delta_Tijd_Sec"
                ])
            print(f"[LOGGER] Nieuwe rit gestart (Uitgebreide versie): {self.log_file}")
        except Exception as e:
            print(f"[LOGGER ERROR] Kan logbestand niet aanmaken: {e}")
            self.log_file = None

    def log_regel(self, wp_idx, lat, lon, fix, hdop, heading, doel_heading, 
                  fout, xte, doel_kmh, echt_kmh, turn, pi_corr, i_term, 
                  links, rechts, dist, dt):
        """Schrijft de volledige telemetrie weg naar de CSV (10 Hz)"""
        if not self.log_file:
            return

        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                tijdstip_nu = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                
                writer.writerow([
                    tijdstip_nu, wp_idx, lat, lon, 
                    fix, hdop, 
                    round(heading, 2), round(doel_heading, 2), 
                    round(fout, 2), round(xte, 3), 
                    round(doel_kmh, 2), round(echt_kmh, 2),
                    round(turn, 1), round(pi_corr, 1), round(i_term, 3),
                    links, rechts, round(dist, 2), 
                    round(dt, 3)
                ])
        except Exception:
            # Fout negeren om te voorkomen dat de hoofd-loop crasht
            pass