from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.vision.streamer import VisionStreamer
from app.hardware import config
import json
import os
import glob

from app.hardware import motor_controller, gps_system
from app.services.navigator import Navigator
from app.services.skidsteer import SkidsteerController # <-- TOEGEVOEGD: Import voor Skidsteer

vision_streamer = VisionStreamer(config)
vision_streamer.start()

navigator = Navigator(gps_system, motor_controller)
skidsteer_controller = SkidsteerController(motor_controller) # <-- TOEGEVOEGD: Initialiseer de controller

router = APIRouter()
WAYPOINTS_FILE = 'data/waypoints.json'

class MotorCommand(BaseModel):
    links: int
    rechts: int

class Waypoint(BaseModel):
    lat: float
    lon: float

# AANGEPAST: We verwachten nu target_speed_kmh als float (bijv. 3.0)
class NavCommand(BaseModel):
    target_speed_kmh: float

# AANGEPAST: We verwachten nu target_speed_kmh als float (bijv. 3.0)
class DirectNavCommand(BaseModel):
    lat: float
    lon: float
    target_speed_kmh: float

@router.get("/status")
def get_status():
    return gps_system.current_position

@router.post("/motor")
def stuur_motor(cmd: MotorCommand):
    motor_controller.stuur_motoren(cmd.links, cmd.rechts)
    return {"status": "success", "links": cmd.links, "rechts": cmd.rechts}

# <-- TOEGEVOEGD: Nieuwe endpoint speciaal voor Skidsteer -->
@router.post("/skidsteer")
def update_skidsteer(cmd: MotorCommand):
    skidsteer_controller.set_target(cmd.links, cmd.rechts)
    return {"status": "success", "target_l": cmd.links, "target_r": cmd.rechts}

@router.post("/stop")
def noodstop():
    navigator.stop()
    
    # <-- TOEGEVOEGD: Zorg dat de skidsteer smoothing ook stopt! -->
    skidsteer_controller.stop_direct() 
    
    # HARDWARE NOODSTOP FORCEER: direct de rem-waarde 700!
    motor_controller.stuur_motoren(700, 700)
    
    return {"status": "noodstop geactiveerd (PWM 700)"}

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
    return laad_waypoints()

@router.post("/waypoints")
def add_waypoint(wp: Waypoint):
    waypoints = laad_waypoints()
    waypoints.append({"lat": wp.lat, "lon": wp.lon})
    bewaar_waypoints(waypoints)
    return {"status": "success", "total": len(waypoints)}

@router.delete("/waypoints")
def clear_waypoints():
    bewaar_waypoints([])
    return {"status": "cleared"}

@router.post("/start_nav")
def start_navigation(cmd: NavCommand):
    wps = laad_waypoints()
    if not wps:
        raise HTTPException(status_code=400, detail="Geen waypoints gevonden")
    
    # AANGEPAST: Geef target_speed_kmh mee aan de navigator
    navigator.start(wps, target_speed_kmh=cmd.target_speed_kmh)
    return {"status": "navigatie gestart"}

@router.post("/start_nav_direct")
def start_nav_direct(cmd: DirectNavCommand):
    # AANGEPAST: Geef target_speed_kmh mee aan de navigator
    navigator.start([{"lat": cmd.lat, "lon": cmd.lon}], target_speed_kmh=cmd.target_speed_kmh)
    return {"status": "navigatie gestart naar specifiek punt"}

@router.post("/stop_nav")
def stop_navigation():
    navigator.stop()
    # Ook bij stop_nav drukken we direct de 700 door voor een snelle, veilige stop
    motor_controller.stuur_motoren(700, 700)
    return {"status": "navigatie gestopt"}

@router.get("/video_feed")
def video_feed():
    return StreamingResponse(
        vision_streamer.get_mjpeg_stream(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@router.get("/weeds")
def get_weeds():
    weeds = []
    metadata_files = glob.glob('data/detections/*/metadata.json')
    
    for file_path in metadata_files:
        try:
            with open(file_path, 'r') as f:
                weeds.append(json.load(f))
        except Exception:
            pass
            
    weeds.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return weeds