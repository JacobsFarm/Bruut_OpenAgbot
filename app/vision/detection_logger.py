import os
import json
import uuid
import cv2
import time

class DetectionLogger:
    def __init__(self, base_dir="data/detections"):
        self.base_dir = base_dir
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

    def log_detection(self, clean_frame, annotated_frame, weed_data):
        """
        Maakt een unieke folder en slaat de afbeeldingen en metadata op.
        weed_data bevat: class_name, confidence, bbox, zone, offset_m, lat, lon
        """
        # Genereer unieke random code
        detectie_id = str(uuid.uuid4())[:8] # Bijv: a1b2c3d4
        sub_dir = os.path.join(self.base_dir, detectie_id)
        os.makedirs(sub_dir, exist_ok=True)

        # 1. Sla clean.jpg op
        cv2.imwrite(os.path.join(sub_dir, "clean.jpg"), clean_frame)

        # 2. Sla geannoteerde afbeelding op (met _conf in de naam)
        conf_str = f"{weed_data['confidence']:.2f}"
        annotated_filename = f"{detectie_id}_conf{conf_str}.jpg"
        cv2.imwrite(os.path.join(sub_dir, annotated_filename), annotated_frame)

        # 3. Genereer metadata
        metadata = {
            "id": detectie_id,
            "timestamp": time.time(),
            "time_readable": time.strftime('%Y-%m-%d %H:%M:%S'),
            "class_name": weed_data["class_name"],
            "confidence": weed_data["confidence"],
            "bounding_box": weed_data["bbox"], # [x1, y1, x2, y2]
            "zone": weed_data["zone"],         # 0 t/m 5
            "offset_meters": weed_data["offset_m"],
            "gps_lat": weed_data["lat"],
            "gps_lon": weed_data["lon"]
        }

        # Sla metadata.json op
        with open(os.path.join(sub_dir, "metadata.json"), 'w') as f:
            json.dump(metadata, f, indent=4)
            
        print(f"📸 [LOGGER] Nieuwe detectie opgeslagen in {sub_dir}")
        return metadata