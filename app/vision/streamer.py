import cv2
import threading
import time
import os
from datetime import datetime
from ultralytics import YOLO

# Importeer de nieuwe modules
from app.vision.detection_logger import DetectionLogger
from app.vision.weed_tracker import WeedTracker
from app.hardware import gps_system

class VisionStreamer:
    def __init__(self, config):
        self.config = config
        
        # Bepaal de bron op basis van het config bestand
        self.camera_type = config['vision'].get('camera_type', 'rtsp')
        if self.camera_type == 'rtsp':
            self.stream_source = config['vision']['rtsp_streams'][0]
        elif self.camera_type == 'usb':
            self.stream_source = config['vision']['usb_camera']['index']
        else:
            raise ValueError(f"Onbekend camera type: {self.camera_type}")

        self.model = YOLO(config['vision']['yolo_model_path'])
        self.conf_threshold = config['vision']['confidence_threshold']
        
        # Initialiseer onze nieuwe scripts
        self.logger = DetectionLogger()
        self.tracker = WeedTracker(config)
        
        self.latest_frame = None
        self.latest_annotated_frame = None
        self.running = False
        self.lock = threading.Lock()
        
        # --- NIEUW: Snapshot map aanmaken en timer instellen ---
        self.snapshot_dir = os.path.join("data", "snapshot")
        os.makedirs(self.snapshot_dir, exist_ok=True) # Maakt de map aan als deze niet bestaat
        self.last_snapshot_time = time.time()

    def start(self):
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._inference_loop, daemon=True).start()

    def _capture_loop(self):
        print(f"[VISION] Verbinden met camera of video bron: {self.stream_source}")
        
        # Lees het besturingssysteem uit de config (standaard 'linux' als het er niet staat)
        os_type = self.config.get('system', {}).get('os', 'linux').lower()
        
        # Voor Windows en USB camera's gebruiken we DirectShow (DSHOW) voor de 100 fps
        if self.camera_type == 'usb' and os_type == 'windows':
            print("[VISION] Windows gedetecteerd in config: DirectShow wordt gebruikt.")
            cap = cv2.VideoCapture(self.stream_source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(self.stream_source)
        
        # Als het een USB camera is, forceer dan de resolutie en framerate
        if self.camera_type == 'usb':
            # Gebruik het MJPG format (noodzakelijk voor 100fps via USB 2.0)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config['vision']['usb_camera']['width'])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config['vision']['usb_camera']['height'])
            cap.set(cv2.CAP_PROP_FPS, self.config['vision']['usb_camera']['fps'])
            
            # Lees ter controle terug wat de camera daadwerkelijk geaccepteerd heeft
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"[VISION] USB Camera succesvol geconfigureerd op: {w}x{h} @ {fps} FPS")

        # Bepaal of het een videobestand is (alleen relevant bij RTSP of lokale string)
        is_video_bestand = False
        if isinstance(self.stream_source, str):
            is_video_bestand = ".mp4" in self.stream_source.lower()

        while self.running:
            ret, frame = cap.read()
            if ret:
                with self.lock:
                    self.latest_frame = frame
                
                # Als het een lokaal bestand is, bouw een kleine vertraging in 
                if is_video_bestand:
                    time.sleep(0.033) 
            else:
                # Geen beeld ontvangen?
                if is_video_bestand:
                    # Video is afgelopen! Spoel terug naar het begin
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    # Camera hapering of losgekoppeld, wacht even
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
                results = self.model.track(frame_to_process, conf=self.conf_threshold, persist=True, verbose=False)
                
                # Sla de schone frame op (voordat we er blokken op tekenen)
                clean_frame = frame_to_process.copy()
                
                # --- NIEUW: Logica voor de 10-seconden snapshot ---
                current_time = time.time()
                if current_time - self.last_snapshot_time >= 10.0:
                    # Genereer een unieke bestandsnaam met datum en tijd
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    snapshot_path = os.path.join(self.snapshot_dir, f"snapshot_{timestamp}.jpg")
                    
                    # Sla de schone (niet geannoteerde) frame op
                    cv2.imwrite(snapshot_path, clean_frame)
                    print(f"[VISION] 10-sec snapshot opgeslagen: {snapshot_path}")
                    
                    # Reset de timer
                    self.last_snapshot_time = current_time

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
