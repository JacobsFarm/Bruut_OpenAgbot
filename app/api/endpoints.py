from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.vision.streamer import VisionStreamer
from app.hardware import config # Importeer de config die we in hardware/__init__.py laden
import json
import os
import glob

# Importeer de hardware die we net hebben opgestart
from app.hardware import motor_controller, gps_system

vision_streamer = VisionStreamer(config)
vision_streamer.start()

router = APIRouter()
WAYPOINTS_FILE = 'data/waypoints.json'

# --- Pydantic Modellen voor inkomende data ---
class MotorCommand(BaseModel):
    links: int
    rechts: int

class Waypoint(BaseModel):
    lat: float
    lon: float

# ==========================================
# 1. STATUS ENDPOINTS (GPS & Systeem)
# ==========================================
@router.get("/status")
def get_status():
    """Geeft de actuele GPS status terug aan het dashboard"""
    return gps_system.current_position

# ==========================================
# 2. MOTOR ENDPOINTS
# ==========================================
@router.post("/motor")
def stuur_motor(cmd: MotorCommand):
    print(f"💻 [API] Svelte zegt: Links={cmd.links}, Rechts={cmd.rechts}") # <-- VOEG DEZE TOE
    motor_controller.stuur_motoren(cmd.links, cmd.rechts)
    return {"status": "success", "links": cmd.links, "rechts": cmd.rechts}

@router.post("/stop")
def noodstop():
    """Zet alle motoren direct stil (DAC waarde 700)"""
    motor_controller.stop()
    return {"status": "noodstop geactiveerd"}

# ==========================================
# 3. WAYPOINT ENDPOINTS
# ==========================================
def laad_waypoints():
    if os.path.exists(WAYPOINTS_FILE):
        with open(WAYPOINTS_FILE, 'r') as f:
            return json.load(f)
    return []

def bewaar_waypoints(data):
    with open(WAYPOINTS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@router.get("/waypoints")
def get_waypoints():
    """Haalt de lijst met opgeslagen waypoints op"""
    return laad_waypoints()

@router.post("/waypoints")
def add_waypoint(wp: Waypoint):
    """Slaat een nieuw waypoint op (bijvoorbeeld huidige GPS locatie)"""
    waypoints = laad_waypoints()
    waypoints.append({"lat": wp.lat, "lon": wp.lon})
    bewaar_waypoints(waypoints)
    return {"status": "success", "total": len(waypoints)}

@router.delete("/waypoints")
def clear_waypoints():
    """Zil alle waypoints (om een nieuwe route te maken)"""
    bewaar_waypoints([])
    return {"status": "cleared"}

# ==========================================
# 4. VISION & CAMERA ENDPOINTS
# ==========================================
@router.get("/video_feed")
def video_feed():
    """Dit endpoint streamt de live YOLO beelden naar de <img> tag in Svelte"""
    return StreamingResponse(
        vision_streamer.get_mjpeg_stream(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@router.get("/weeds")
def get_weeds():
    """Scant de nieuwe data/detections mappen en haalt de metadata op"""
    weeds = []
    # Zoek naar alle metadata.json bestanden in de submappen van data/detections
    metadata_files = glob.glob('data/detections/*/metadata.json')
    
    for file_path in metadata_files:
        try:
            with open(file_path, 'r') as f:
                weeds.append(json.load(f))
        except Exception:
            pass
            
    # Sorteer op tijdstip (nieuwste eerst)
    weeds.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return weeds