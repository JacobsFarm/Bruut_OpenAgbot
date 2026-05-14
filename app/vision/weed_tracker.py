class WeedTracker:
    def __init__(self, config):
        self.lijn_y_ratio = config['vision']['trigger_lijn_y_percentage']
        self.aantal_zones = config['vision']['zones_aantal']
        self.zone_offsets = config['vision']['zone_offsets_meters']
        
        # Set om bij te houden welke tracking-ID's al zijn geteld/opgeslagen
        self.getelde_ids = set()

    def verwerk_tracks(self, resultaat, frame_breedte, frame_hoogte):
        """
        Ontvangt de YOLO tracking resultaten en geeft een lijst terug 
        van onkruid dat NU de lijn passeert.
        """
        triggers = []
        trigger_lijn_y = int(frame_hoogte * self.lijn_y_ratio)

        # Als er geen boxes of geen tracking ID's zijn, doe niks
        if resultaat.boxes is None or resultaat.boxes.id is None:
            return triggers

        boxes = resultaat.boxes.xyxy.cpu().numpy() # [x1, y1, x2, y2]
        track_ids = resultaat.boxes.id.int().cpu().tolist()
        confidences = resultaat.boxes.conf.cpu().numpy()
        classes = resultaat.boxes.cls.int().cpu().tolist()
        names = resultaat.names # Dictionary met namen, bijv {0: 'dandelion', 1: 'dockweed'}

        for box, track_id, conf, cls in zip(boxes, track_ids, confidences, classes):
            x1, y1, x2, y2 = box
            
            # Bereken het middelpunt van de bounding box
            midden_x = (x1 + x2) / 2
            midden_y = (y1 + y2) / 2

            # LOGICA 1: Check of de lijn is gepasseerd (van boven naar beneden)
            if midden_y > trigger_lijn_y and track_id not in self.getelde_ids:
                # Voorkom dat we deze de volgende frame weer opslaan
                self.getelde_ids.add(track_id)

                # LOGICA 2: Bereken in welke van de 6 zones het onkruid zit
                zone_breedte = frame_breedte / self.aantal_zones
                actuele_zone = int(midden_x // zone_breedte)
                # Veiligheidscheck (zorg dat zone tussen 0 en 5 blijft)
                actuele_zone = max(0, min(self.aantal_zones - 1, actuele_zone))

                offset_m = self.zone_offsets[actuele_zone]
                class_naam = names[cls]

                triggers.append({
                    "track_id": track_id,
                    "class_name": class_naam,
                    "confidence": float(conf),
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "zone": actuele_zone + 1, # Maak er zone 1 t/m 6 van
                    "offset_m": float(offset_m)
                })

        return triggers