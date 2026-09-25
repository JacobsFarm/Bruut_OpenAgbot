import os
import json
import uuid
import cv2
import time


class DetectionLogger:
    """
    Slaat per plant (track-ID) één map op met meerdere screenshots.

    data/detections/<id>/
        001_clean.jpg
        001_conf0.87.jpg      (geannoteerd)
        002_clean.jpg
        ...
        metadata.json         (wordt na elke screenshot bijgewerkt)
    """

    def __init__(self, base_dir="data/detections"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

        # track_id -> metadata dict van de plant die nog in beeld is
        self.open_detecties = {}

    def _schrijf_metadata(self, metadata):
        pad = os.path.join(self.base_dir, metadata["id"], "metadata.json")
        with open(pad, 'w') as f:
            json.dump(metadata, f, indent=4)

    def log_screenshot(self, clean_frame, annotated_frame, weed_data):
        """
        Slaat een screenshot op van een plant.
        weed_data bevat: track_id, screenshot_nr, class_name, confidence, bbox, segmentatie, zone, offset_m, lat, lon
        """
        track_id = weed_data["track_id"]
        metadata = self.open_detecties.get(track_id)

        if metadata is None:
            # Eerste screenshot van deze plant: nieuwe map met unieke random code
            detectie_id = str(uuid.uuid4())[:8]  # Bijv: a1b2c3d4
            os.makedirs(os.path.join(self.base_dir, detectie_id), exist_ok=True)
            metadata = {
                "id": detectie_id,
                "track_id": track_id,
                "timestamp": time.time(),
                "time_readable": time.strftime('%Y-%m-%d %H:%M:%S'),
                "afgerond": False,
                "screenshots": [],
            }
            self.open_detecties[track_id] = metadata
            print(f"🌱 [LOGGER] Nieuwe plant in beeld (track {track_id}) -> {detectie_id}")

        sub_dir = os.path.join(self.base_dir, metadata["id"])
        nr = f"{weed_data['screenshot_nr']:03d}"
        clean_naam = f"{nr}_clean.jpg"
        annotated_naam = f"{nr}_conf{weed_data['confidence']:.2f}.jpg"
        cv2.imwrite(os.path.join(sub_dir, clean_naam), clean_frame)
        cv2.imwrite(os.path.join(sub_dir, annotated_naam), annotated_frame)

        metadata["screenshots"].append({
            "nr": weed_data["screenshot_nr"],
            "timestamp": time.time(),
            "clean_image": clean_naam,
            "annotated_image": annotated_naam,
            "class_name": weed_data["class_name"],
            "confidence": weed_data["confidence"],
            "bounding_box": weed_data["bbox"],  # [x1, y1, x2, y2]
            "segmentatie": weed_data["segmentatie"],  # [[x, y], ...] of None bij een detectiemodel
            "zone": weed_data["zone"],
            "offset_meters": weed_data["offset_m"],
            "gps_lat": weed_data["lat"],
            "gps_lon": weed_data["lon"],
        })

        # Samenvatting op topniveau = de screenshot met de hoogste confidence
        beste = max(metadata["screenshots"], key=lambda s: s["confidence"])
        metadata.update({
            "class_name": beste["class_name"],
            "confidence": beste["confidence"],
            "bounding_box": beste["bounding_box"],
            "segmentatie": beste["segmentatie"],
            "zone": beste["zone"],
            "offset_meters": beste["offset_meters"],
            "gps_lat": beste["gps_lat"],
            "gps_lon": beste["gps_lon"],
            "aantal_screenshots": len(metadata["screenshots"]),
        })

        self._schrijf_metadata(metadata)
        return metadata

    def sluit_detectie(self, track_id):
        """Plant is uit beeld: markeer de detectie als afgerond."""
        metadata = self.open_detecties.pop(track_id, None)
        if metadata is None:
            return None  # Track is nooit lang genoeg in beeld geweest om op te slaan

        metadata["afgerond"] = True
        metadata["uit_beeld"] = time.time()
        self._schrijf_metadata(metadata)
        print(f"📸 [LOGGER] Plant {metadata['id']} uit beeld, "
              f"{len(metadata['screenshots'])} screenshot(s) opgeslagen")
        return metadata
