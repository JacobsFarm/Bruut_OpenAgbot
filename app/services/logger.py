import os
import csv
from datetime import datetime

class DriveLogger:
    def __init__(self):
        self.log_file = None
        self.log_dir = os.path.join('data', 'logs')
        
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def start_nieuwe_rit(self, navigatie_modus="autonoom"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"rit_{navigatie_modus}_{timestamp}.csv")
        
        try:
            with open(self.log_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Tijdstip", "Modus", "WP_Doel", "Lat", "Lon", "Fix", "HDOP",
                    "Heading_Echt", "Heading_Doel", "Heading_Fout",
                    "Stuurhoek", "Doel_kmh", "Echt_kmh",
                    "DAC_Links", "DAC_Rechts",
                    "Afstand_tot_WP_m", "Lookahead_m", "Loop_Tijd_s"
                ])
        except Exception:
            self.log_file = None

    def log_regel(self, modus="", wp_idx=0, lat=0.0, lon=0.0, fix=0, hdop=99.0,
                  heading_echt=0.0, heading_doel=0.0, heading_fout=0.0,
                  stuurhoek=0.0, doel_kmh=0.0, echt_kmh=0.0,
                  dac_links=0, dac_rechts=0,
                  dist_wp=0.0, lookahead=0.0, dt=0.0):
        if not self.log_file:
            return

        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                tijdstip_nu = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                writer.writerow([
                    tijdstip_nu, modus, wp_idx, lat, lon, fix, hdop,
                    round(heading_echt, 2) if heading_echt else 0.0, 
                    round(heading_doel, 2) if heading_doel else 0.0, 
                    round(heading_fout, 2) if heading_fout else 0.0,
                    round(stuurhoek, 2) if stuurhoek else 0.0, 
                    round(doel_kmh, 2) if doel_kmh else 0.0, 
                    round(echt_kmh, 2) if echt_kmh else 0.0,
                    int(dac_links) if dac_links else 0, 
                    int(dac_rechts) if dac_rechts else 0,
                    round(dist_wp, 3) if dist_wp else 0.0, 
                    round(lookahead, 2) if lookahead else 0.0, 
                    round(dt, 4) if dt else 0.0
                ])
        except Exception:
            pass

    def stop_log(self):
        if not self.log_file:
            return
        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["---", "EINDE RIT", "---"])
        except Exception:
            pass
        self.log_file = None