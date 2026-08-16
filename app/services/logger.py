import os
import csv
from datetime import datetime


class DriveLogger:
    """
    Schrijft per rit een CSV met wat de robot wilde en wat hij deed.

    Skid steer: in plaats van een stuurhoek loggen we de DRAAISNELHEID
    (graden/s) en de KROMMING (1/m), plus de wielsnelheden links en rechts.
    Dat zijn de grootheden waarmee deze aandrijving daadwerkelijk stuurt.
    """
    KOLOMMEN = [
        "Tijdstip", "Modus", "WP_Doel", "Lat", "Lon", "Fix", "HDOP",
        "Heading_Echt", "Heading_Doel", "Heading_Fout",
        "Draai_dps", "Kromming_1pm", "Doel_kmh", "Echt_kmh",
        "DAC_Links", "DAC_Rechts", "Snelheid_Links_mps", "Snelheid_Rechts_mps",
        "Afstand_tot_WP_m", "Lookahead_m", "Loop_Tijd_s"
    ]

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
                writer.writerow(self.KOLOMMEN)
        except Exception:
            self.log_file = None

    def log_regel(self, modus="", wp_idx=0, lat=0.0, lon=0.0, fix=0, hdop=99.0,
                  heading_echt=0.0, heading_doel=0.0, heading_fout=0.0,
                  draai_dps=0.0, kromming=0.0, doel_kmh=0.0, echt_kmh=0.0,
                  dac_links=0, dac_rechts=0, snelheid_links=0.0, snelheid_rechts=0.0,
                  dist_wp=0.0, lookahead=0.0, dt=0.0):
        if not self.log_file:
            return

        try:
            with open(self.log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                tijdstip_nu = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                writer.writerow([
                    tijdstip_nu, modus, wp_idx, lat, lon, fix, hdop,
                    round(heading_echt or 0.0, 2),
                    round(heading_doel or 0.0, 2),
                    round(heading_fout or 0.0, 2),
                    round(draai_dps or 0.0, 2),
                    round(kromming or 0.0, 4),
                    round(doel_kmh or 0.0, 2),
                    round(echt_kmh or 0.0, 2),
                    int(dac_links or 0),
                    int(dac_rechts or 0),
                    round(snelheid_links or 0.0, 3),
                    round(snelheid_rechts or 0.0, 3),
                    round(dist_wp or 0.0, 3),
                    round(lookahead or 0.0, 2),
                    round(dt or 0.0, 4)
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
