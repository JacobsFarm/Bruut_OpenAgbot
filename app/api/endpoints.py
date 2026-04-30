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

vision_streamer = VisionStreamer(config)
vision_streamer.start()

navigator = Navigator(gps_system, motor_controller)

router = APIRouter()
WAYPOINTS_FILE = 'data/waypoints.json'

class MotorCommand(BaseModel):
    links: int
    rechts: int

class Waypoint(BaseModel):
    lat: float
    lon: float

class NavCommand(BaseModel):
    base_pwm: int

class DirectNavCommand(BaseModel):
    lat: float
    lon: float
    base_pwm: int

@router.get("/status")
def get_status():
    return gps_system.current_position

@router.post("/motor")
def stuur_motor(cmd: MotorCommand):
    motor_controller.stuur_motoren(cmd.links, cmd.rechts)
    return {"status": "success", "links": cmd.links, "rechts": cmd.rechts}

@router.post("/stop")
def noodstop():
    navigator.stop()
    motor_controller.stop()
    return {"status": "noodstop geactiveerd"}

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
    navigator.start(wps, cmd.base_pwm)
    return {"status": "navigatie gestart"}

@router.post("/start_nav_direct")
def start_nav_direct(cmd: DirectNavCommand):
    navigator.start([{"lat": cmd.lat, "lon": cmd.lon}], cmd.base_pwm)
    return {"status": "navigatie gestart naar specifiek punt"}

@router.post("/stop_nav")
def stop_navigation():
    navigator.stop()
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