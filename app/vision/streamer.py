import cv2
import threading
import time
import os
import queue
from datetime import datetime
from ultralytics import YOLO

try:
    import gxipy as gx
except ImportError:
    gx = None

# Maximaal aantal gebufferde frames voor de gx camera.
# Bij 15 fps = max 200ms latency voordat de queue geleegd wordt.
GX_QUEUE_MAX = 3

# Importeer de nieuwe modules
from app.vision.detection_logger import DetectionLogger
from app.vision.weed_tracker import WeedTracker
from app import gps_system

class VisionStreamer:
    def __init__(self, config):
        self.config = config
        
        # Bepaal de bron op basis van het config bestand
        self.camera_type = config['vision'].get('camera_type', 'rtsp')
        if self.camera_type == 'rtsp':
            self.stream_source = config['vision']['rtsp_streams'][0]
        elif self.camera_type == 'usb':
            self.stream_source = config['vision']['usb_camera']['index']
        elif self.camera_type == 'gx':
            self.stream_source = None  # gxipy gebruikt eigen device manager
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
        self.gx_frame_queue = queue.Queue(maxsize=GX_QUEUE_MAX)
        
        # --- NIEUW: Snapshot map aanmaken en timer instellen ---
        self.snapshot_dir = os.path.join("data", "snapshot")
        os.makedirs(self.snapshot_dir, exist_ok=True) # Maakt de map aan als deze niet bestaat
        self.last_snapshot_time = time.time()

    def start(self):
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._inference_loop, daemon=True).start()

    def _capture_loop(self):
        if self.camera_type == 'gx':
            self._capture_loop_gx()
        else:
            self._capture_loop_cv()

    def _capture_loop_gx(self):
        if gx is None:
            print("[VISION] gxipy niet geïnstalleerd. Kan Daheng camera niet starten.")
            return

        cfg = self.config['vision']['gx_camera']
        interval = 1.0 / cfg.get('fps', 15)

        print("[VISION] Verbinden met Daheng (gxipy) camera...")
        device_manager = gx.DeviceManager()
        num, _ = device_manager.update_device_list()
        if num == 0:
            print("[VISION] Geen Daheng camera gevonden. Controleer USB aansluiting.")
            return

        cam = device_manager.open_device_by_index(cfg.get('index', 1))

        cam.ExposureAuto.set(gx.GxAutoEntry.CONTINUOUS)
        cam.AutoExposureTimeMax.set(cfg.get('exposure_max_us', 500))
        cam.AutoExposureTimeMin.set(cfg.get('exposure_min_us', 100))
        cam.GainAuto.set(gx.GxAutoEntry.CONTINUOUS)
        cam.AutoGainMax.set(cfg.get('gain_max_db', 16))
        cam.AutoGainMin.set(cfg.get('gain_min_db', 0))
        cam.BalanceWhiteAuto.set(gx.GxAutoEntry.ONCE)

        cam.stream_on()
        print(f"[VISION] Daheng camera gestart op {cfg.get('fps', 15)} fps.")

        while self.running:
            start = time.time()
            raw = cam.data_stream[0].get_image()
            if raw is None:
                continue

            rgb = raw.convert("RGB")
            img = rgb.get_numpy_array()
            frame = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            # Queue vol = inference kan GPU-piek niet bijhouden: gooi oude frames weg
            # zodat de inference altijd een recente frame krijgt.
            if self.gx_frame_queue.full():
                try:
                    self.gx_frame_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                self.gx_frame_queue.put_nowait(frame)
            except queue.Full:
                pass

            verstreken = time.time() - start
            wacht = interval - verstreken
            if wacht > 0:
                time.sleep(wacht)

        cam.stream_off()
        cam.close_device()

    def _capture_loop_cv(self):
        print(f"[VISION] Verbinden met camera of video bron: {self.stream_source}")

        os_type = self.config.get('system', {}).get('os', 'linux').lower()

        if self.camera_type == 'usb' and os_type == 'windows':
            print("[VISION] Windows gedetecteerd in config: DirectShow wordt gebruikt.")
            cap = cv2.VideoCapture(self.stream_source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(self.stream_source)

        if self.camera_type == 'usb':
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config['vision']['usb_camera']['width'])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config['vision']['usb_camera']['height'])
            cap.set(cv2.CAP_PROP_FPS, self.config['vision']['usb_camera']['fps'])

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"[VISION] USB Camera succesvol geconfigureerd op: {w}x{h} @ {fps} FPS")

        is_video_bestand = False
        if isinstance(self.stream_source, str):
            is_video_bestand = ".mp4" in self.stream_source.lower()

        while self.running:
            ret, frame = cap.read()
            if ret:
                with self.lock:
                    self.latest_frame = frame

                if is_video_bestand:
                    time.sleep(0.033)
            else:
                if is_video_bestand:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    time.sleep(0.1)

        cap.release()

    def _inference_loop(self):
        while self.running:
            frame_to_process = None

            if self.camera_type == 'gx':
                try:
                    frame_to_process = self.gx_frame_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
            else:
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
