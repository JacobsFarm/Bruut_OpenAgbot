import cv2
import threading
import time
from ultralytics import YOLO

# Importeer de nieuwe modules
from app.vision.detection_logger import DetectionLogger
from app.vision.weed_tracker import WeedTracker
from app.hardware import gps_system

class VisionStreamer:
    def __init__(self, config):
        self.stream_url = config['vision']['rtsp_streams'][0]
        self.model = YOLO(config['vision']['yolo_model_path'])
        self.conf_threshold = config['vision']['confidence_threshold']
        
        # Initialiseer onze nieuwe scripts
        self.logger = DetectionLogger()
        self.tracker = WeedTracker(config)
        
        self.latest_frame = None
        self.latest_annotated_frame = None
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._inference_loop, daemon=True).start()

    def _capture_loop(self):
        print(f"[VISION] Verbinden met camera of video: {self.stream_url}")
        cap = cv2.VideoCapture(self.stream_url)
        
        # Bepaal of het een videobestand is
        is_video_bestand = ".mp4" in self.stream_url.lower()

        while self.running:
            ret, frame = cap.read()
            if ret:
                with self.lock:
                    self.latest_frame = frame
                
                # Als het een lokaal bestand is, bouw een kleine vertraging in 
                # zodat hij op ~30 FPS afspeelt en niet in 1 seconde klaar is.
                if is_video_bestand:
                    time.sleep(0.033) 
            else:
                # Geen beeld ontvangen?
                if is_video_bestand:
                    # Video is afgelopen! Spoel terug naar het begin (Frame 0) voor een oneindige loop
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    # RTSP stream hapering, wacht even
                    time.sleep(0.1)
                    
        cap.release()

    def _inference_loop(self):
        while self.running:
            frame_to_process = None
            with self.lock:
                if self.latest_frame is not None:
                    frame_to_process = self.latest_frame.copy()

            if frame_to_process is not None:
                frame_hoogte, frame_breedte = frame_to_process.shape[:2]
                
                # BELANGRIJK: Gebruik .track() in plaats van () voor tracking ID's
                # persist=True zorgt dat de tracker z'n geheugen behoudt over frames
                results = self.model.track(frame_to_process, conf=self.conf_threshold, persist=True, verbose=False)
                
                # Sla de schone frame op (voordat we er blokken op tekenen)
                clean_frame = frame_to_process.copy()
                
                # Teken de blokken op de nieuwe frame (voor het dashboard en de save)
                annotated_frame = results[0].plot()

                # Teken de denkbeeldige trigger lijn voor de live feed (visuele feedback)
                lijn_y = int(frame_hoogte * self.tracker.lijn_y_ratio)
                cv2.line(annotated_frame, (0, lijn_y), (frame_breedte, lijn_y), (0, 0, 255), 2) # Rode lijn

                # Controleer of er getrackte objecten de lijn passeren
                triggers = self.tracker.verwerk_tracks(results[0], frame_breedte, frame_hoogte)

                # Voor elke getriggerde detectie, vraag GPS en log alles!
                for weed_data in triggers:
                    pos = gps_system.current_position
                    
                    # Voeg actuele GPS coördinaten toe aan de dataset
                    weed_data["lat"] = pos["lat"]
                    weed_data["lon"] = pos["lon"]
                    
                    # Oproepen logger
                    self.logger.log_detection(clean_frame, annotated_frame, weed_data)

                with self.lock:
                    self.latest_annotated_frame = annotated_frame
            else:
                time.sleep(0.05)

    def get_mjpeg_stream(self):
        while self.running:
            with self.lock:
                frame = self.latest_annotated_frame
                
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.05)