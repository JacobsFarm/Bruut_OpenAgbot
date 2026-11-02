import os
import csv
from datetime import datetime

from app.hardware.motor_logic import LOG_COLUMNS as MOTOR_KOLOMMEN

# Uit GpsSystem.get_current_position(): wat de ZED-X20D per meting meegeeft.
GNSS_KOLOMMEN = [
    ("Fix_Soort", "fix_soort"), ("Heading_Bron", "heading_bron"),
    ("Draaisnelheid_dps", "draaisnelheid_dps"), ("Sliphoek_deg", "sliphoek_deg"),
    ("Rijrichting", "rijrichting"), ("Pos_Leeftijd_s", "positie_leeftijd_s"),
    ("Correctie_Leeftijd_s", "correctie_leeftijd_s"), ("Voorspeld_s", "voorspeld_s"),
    # UBX-NAV-DAHEADING: leeg zolang het board hem niet stuurt.
    ("Baseline_m", "baseline_m"), ("Hoogteverschil_m", "antenne_hoogteverschil_m"),
    ("Pitch_deg", "pitch_deg"), ("DAH_Heading", "dah_heading"),
    ("DAH_AccHeading", "dah_acc_heading"), ("DAH_Oplossing", "dah_oplossing"),
    ("DAH_Leeftijd_s", "dah_leeftijd_s"),
    ("Pitch_Correctie_m", "pitch_correctie_m"), ("Hoogte_Grond_m", "hoogte_grond_m"),
    # Ruwe GGA-hoogte van de antenne zelf (Hoogte_Grond_m = deze min antenna_height_m x cos(pitch)).
    ("Hoogte_Antenne_m", "alt_m"),
    ("Ruwheid_deg", "ruwheid_deg"),
    # Grond onder de antenne: bij deze positie hoort Hoogte_Grond_m (Lat/Lon is het regelpunt).
    ("Grond_Lat", "grond_lat"), ("Grond_Lon", "grond_lon"),
]

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
                    "Afstand_tot_WP_m", "Lookahead_m", "Loop_Tijd_s",
                    "Afwijking_m", "Regelaar", *[k for k, _ in GNSS_KOLOMMEN],
                    *MOTOR_KOLOMMEN
                ])
        except Exception:
            self.log_file = None

    def log_regel(self, modus="", wp_idx=0, lat=0.0, lon=0.0, fix=0, hdop=99.0,
                  heading_echt=0.0, heading_doel=0.0, heading_fout=0.0,
                  stuurhoek=0.0, doel_kmh=0.0, echt_kmh=0.0,
                  dist_wp=0.0, lookahead=0.0, dt=0.0, motor=None,
                  xte=None, regelaar="", gnss=None):
        if not self.log_file:
            return

        # Aandrijfdata van de VESC's (VehicleController.log_snapshot()).
        motor = motor or {}
        gnss = gnss or {}
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
                    round(dist_wp, 3) if dist_wp else 0.0, 
                    round(lookahead, 2) if lookahead else 0.0, 
                    round(dt, 4) if dt else 0.0,
                    "" if xte is None else round(xte, 3), regelaar,
                    *[gnss.get(k, "") if gnss.get(k) is not None else "" for _, k in GNSS_KOLOMMEN],
                    *[motor.get(k, "") for k in MOTOR_KOLOMMEN]
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
