import os
import csv
from datetime import datetime

class DriveLogger:
    def __init__(self):
        self.log_file = None
        self.log_dir = os.path.join('data', 'logs')
        
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def start_nieuwe_rit(self, navigatie_modus="onbekend"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"rit_{navigatie_modus}_{timestamp}.csv")
        
        try:
            with open(self.log_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Tijdstip", "WP_Doel", "Modus",
                    "Lat", "Lon", "Fix", "HDOP",
                    "Heading_Echt", "Heading_Doel", "Heading_Fout", 
                    "Stuurhoek_Graden", 
                    "Snelheid_Doel_kmh", "Snelheid_Echt_kmh",
                    "DAC_Links", "DAC_Rechts", # <-- Nu weer mooi opgesplitst
                    "Afstand_tot_WP_m", "Lookahead_Slider_m", "Loop_Tijd_s"
                ])
        except Exception:
            self.log_file = None

    def log_regel(self, wp_idx, modus, lat, lon, fix, hdop, heading_echt, heading_doel, 
                  heading_fout, stuurhoek, doel_kmh, echt_kmh, dac_links, dac_rechts, dist_wp, 
                  lookahead, dt):
        if not self.log_file: return

        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                tijdstip_nu = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                
                writer.writerow([
                    tijdstip_nu, wp_idx, modus, lat, lon, fix, hdop, 
                    round(heading_echt, 2), round(heading_doel, 2), round(heading_fout, 2), 
                    round(stuurhoek, 2), round(doel_kmh, 2), round(echt_kmh, 2),
                    dac_links, dac_rechts, # <-- Beide DAC waarden wegschrijven
                    round(dist_wp, 3), round(lookahead, 3), round(dt, 3)
                ])
        except Exception:
            pass