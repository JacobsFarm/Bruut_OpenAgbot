import time


class WeedTracker:
    """
    Volgt onkruid op basis van de YOLO tracking-ID's.

    Een plant wordt opgeslagen zodra hij in beeld komt (er is geen trigger-lijn meer).
    Zolang dezelfde track-ID in beeld blijft, geeft de tracker om de
    `screenshot_interval_s` een nieuwe screenshot-opdracht voor die plant, tot
    `max_screenshots_per_plant`. Is een track `track_verlopen_s` niet meer gezien,
    dan wordt hij als afgerond gemeld.
    """

    def __init__(self, config):
        vision = config['vision']
        self.aantal_zones = vision['zones_aantal']
        self.zone_offsets = vision['zone_offsets_meters']

        tracking = vision.get('tracking', {})
        self.screenshot_interval_s = tracking.get('screenshot_interval_s', 0.5)
        self.max_screenshots = tracking.get('max_screenshots_per_plant', 20)
        self.min_frames = tracking.get('min_frames_voor_opslaan', 3)
        self.track_verlopen_s = tracking.get('track_verlopen_s', 1.0)

        # track_id -> {'eerst_gezien', 'laatst_gezien', 'frames', 'laatste_screenshot', 'screenshots'}
        self.actieve_tracks = {}

    def _zone(self, midden_x, frame_breedte):
        zone_breedte = frame_breedte / self.aantal_zones
        zone = int(midden_x // zone_breedte)
        # Veiligheidscheck (zorg dat zone tussen 0 en aantal_zones - 1 blijft)
        return max(0, min(self.aantal_zones - 1, zone))

    def verwerk_tracks(self, resultaat, frame_breedte, frame_hoogte):
        """
        Ontvangt de YOLO tracking resultaten.

        Geeft (screenshots, afgerond) terug:
        - screenshots: lijst met detecties waarvan NU een screenshot moet worden gemaakt
        - afgerond: lijst met track-ID's die uit beeld zijn en afgesloten kunnen worden
        """
        nu = time.time()
        screenshots = []

        if resultaat.boxes is not None and resultaat.boxes.id is not None:
            boxes = resultaat.boxes.xyxy.cpu().numpy()  # [x1, y1, x2, y2]
            track_ids = resultaat.boxes.id.int().cpu().tolist()
            confidences = resultaat.boxes.conf.cpu().numpy()
            classes = resultaat.boxes.cls.int().cpu().tolist()
            names = resultaat.names  # Dictionary met namen, bijv {0: 'dandelion', 1: 'dockweed'}

            # Bij een segmentatiemodel (-seg): per detectie een polygoon in pixelcoördinaten
            if resultaat.masks is not None:
                polygonen = resultaat.masks.xy
            else:
                polygonen = [None] * len(track_ids)

            for box, track_id, conf, cls, polygoon in zip(boxes, track_ids, confidences, classes, polygonen):
                track = self.actieve_tracks.get(track_id)
                if track is None:
                    track = {
                        "eerst_gezien": nu,
                        "laatst_gezien": nu,
                        "frames": 0,
                        "laatste_screenshot": 0.0,
                        "screenshots": 0,
                    }
                    self.actieve_tracks[track_id] = track

                track["laatst_gezien"] = nu
                track["frames"] += 1

                # Pas opslaan als de plant een paar frames stabiel getrackt is (filtert flikkerende valse detecties)
                if track["frames"] < self.min_frames:
                    continue
                if track["screenshots"] >= self.max_screenshots:
                    continue
                if nu - track["laatste_screenshot"] < self.screenshot_interval_s:
                    continue

                track["laatste_screenshot"] = nu
                track["screenshots"] += 1

                x1, y1, x2, y2 = box
                zone = self._zone((x1 + x2) / 2, frame_breedte)

                screenshots.append({
                    "track_id": track_id,
                    "screenshot_nr": track["screenshots"],
                    "class_name": names[cls],
                    "confidence": float(conf),
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "segmentatie": polygoon.tolist() if polygoon is not None else None,
                    "zone": zone + 1,  # Maak er zone 1 t/m N van
                    "offset_m": float(self.zone_offsets[zone]),
                })

        # Tracks die te lang niet gezien zijn: uit beeld, afronden
        afgerond = [tid for tid, t in self.actieve_tracks.items()
                    if nu - t["laatst_gezien"] > self.track_verlopen_s]
        for tid in afgerond:
            del self.actieve_tracks[tid]

        return screenshots, afgerond
