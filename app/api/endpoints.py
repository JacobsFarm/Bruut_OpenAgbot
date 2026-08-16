import os
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app import vehicle_controller, navigator, ab_navigator, gps_system, config

try:
    from app.vision.streamer import VisionStreamer
    vision_streamer = VisionStreamer(config)
    vision_streamer.start()
except Exception as e:
    print(f"⚠️ WAARSCHUWING: Camera/AI module uitgeschakeld wegens fout: {e}")
    vision_streamer = None

router = APIRouter()
AB_LIJNEN_FILE = 'data/ab_line.json'
WAYPOINTS_FILE = 'data/waypoints.json'

class ManualDriveCommand(BaseModel):
    """Handbediening: rijsnelheid + draaien (-100% = links, +100% = rechts)."""
    speed_kmh: float
    turn_percentage: float

class PivotCommand(BaseModel):
    """Draaien op de plek (-100% = linksom, +100% = rechtsom)."""
    turn_percentage: float

class ABMissionCommand(BaseModel):
    work_width_m: float
    field_length_m: float
    speed_kmh: float
    lat_a: float
    lon_a: float
    lat_b: float
    lon_b: float
    lookahead_m: float = None
    turn_speed_kmh: float = None

class ABSliderUpdateCommand(BaseModel):
    lookahead_m: float = None
    target_speed_kmh: float = None
    turn_speed_kmh: float = None

class PurePursuitStartCommand(BaseModel):
    target_speed_kmh: float
    lookahead_distance: float
    gain: float

class DirectPurePursuitCommand(BaseModel):
    lat: float
    lon: float
    target_speed_kmh: float
    lookahead_distance: float
    gain: float

class DirectNavStartCommand(BaseModel):
    lat: float
    lon: float
    target_speed_kmh: float
    gain: float

class SliderUpdateCommand(BaseModel):
    target_speed_kmh: float = None
    lookahead_distance: float = None
    gain: float = None

class Waypoint(BaseModel):
    lat: float
    lon: float
    way_point_name: str = None

def stop_alle_navigatie():
    if navigator.is_active:
        navigator.stop()
    if ab_navigator.is_active:
        ab_navigator.stop()

def laad_ab_lijnen():
    if os.path.exists(AB_LIJNEN_FILE):
        try:
            with open(AB_LIJNEN_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def laad_waypoints():
    if os.path.exists(WAYPOINTS_FILE):
        try:
            with open(WAYPOINTS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def bewaar_waypoints(data):
    os.makedirs(os.path.dirname(WAYPOINTS_FILE), exist_ok=True)
    with open(WAYPOINTS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@router.get("/status")
def get_status():
    pos = gps_system.get_current_position()
    pos.update({
        "navigator_active": navigator.is_active,
        "nav_state": navigator.state,
        "nav_message": navigator.status_message,
        "ab_active": ab_navigator.is_active,
        "ab_state": ab_navigator.state,
        "current_wp": navigator.current_wp_index if navigator.is_active else 0,
        "current_swath": ab_navigator.current_swath if ab_navigator.is_active else 0
    })
    pos.update(vehicle_controller.get_state())
    pos.update(gps_system.get_diagnostics())
    return pos

@router.get("/ab_lijnen")
def get_ab_lijnen():
    return laad_ab_lijnen()

@router.post("/stop")
def noodstop():
    stop_alle_navigatie()
    vehicle_controller.stop()
    return {"status": "stopped"}

@router.post("/nav/manual_drive")
def manual_drive(cmd: ManualDriveCommand):
    stop_alle_navigatie()
    vehicle_controller.drive_manual(cmd.speed_kmh, cmd.turn_percentage)
    return {"status": "driving", **vehicle_controller.get_state()}

@router.post("/nav/pivot")
def pivot_op_de_plek(cmd: PivotCommand):
    """
    Draaien op de plek. Met vooruit-only hubmotoren wordt dit een pivot om het
    stilstaande binnenwiel: de robot draait om een punt onder dat wiel.
    """
    stop_alle_navigatie()
    vehicle_controller.drive_manual(0.0, cmd.turn_percentage)
    return {"status": "pivoting", **vehicle_controller.get_state()}

@router.post("/nav/start_ab")
def start_ab_mission(cmd: ABMissionCommand):
    stop_alle_navigatie()
    if not ab_navigator.set_ab_line(cmd.lat_a, cmd.lon_a, cmd.lat_b, cmd.lon_b):
        return {"status": "error", "msg": "Ongeldige A-B coördinaten"}
    # Lijnvolging-tuning toepassen vóór de start (indien meegegeven)
    if cmd.lookahead_m is not None:
        ab_navigator.lookahead_m = cmd.lookahead_m
    if cmd.turn_speed_kmh is not None:
        ab_navigator.turn_speed_kmh = cmd.turn_speed_kmh
    ab_navigator.start_mission(cmd.work_width_m, cmd.field_length_m, cmd.speed_kmh)
    return {"status": "started"}

@router.post("/nav/update_ab_sliders")
def update_ab_sliders(cmd: ABSliderUpdateCommand):
    """Live aanpassen van de AB-lijnvolging (werkt ook tijdens een lopende missie)."""
    if cmd.lookahead_m is not None:
        ab_navigator.lookahead_m = cmd.lookahead_m
    if cmd.target_speed_kmh is not None:
        ab_navigator.target_speed_kmh = cmd.target_speed_kmh
    if cmd.turn_speed_kmh is not None:
        ab_navigator.turn_speed_kmh = cmd.turn_speed_kmh
    return {
        "status": "Parameters geupdate",
        "lookahead_m": ab_navigator.lookahead_m,
        "target_speed_kmh": ab_navigator.target_speed_kmh,
        "turn_speed_kmh": ab_navigator.turn_speed_kmh
    }

@router.get("/waypoints")
def get_waypoints():
    return laad_waypoints()

@router.post("/waypoints")
def add_waypoint(wp: Waypoint):
    waypoints = laad_waypoints()
    naam = wp.way_point_name.strip() if wp.way_point_name else ""
    if not naam:
        naam = f"point {len(waypoints) + 1}"
    waypoints.append({"way_point_name": naam, "lat": wp.lat, "lon": wp.lon})
    bewaar_waypoints(waypoints)
    return {"status": "success", "total": len(waypoints)}

@router.delete("/waypoints")
def clear_waypoints():
    bewaar_waypoints([])
    return {"status": "cleared"}

@router.post("/nav/start_pure_pursuit")
def start_pure_pursuit(cmd: PurePursuitStartCommand):
    stop_alle_navigatie()
    waypoints = laad_waypoints()
    if not waypoints:
        return {"status": "error", "msg": "Geen waypoints geladen"}
    navigator.lookahead_distance = cmd.lookahead_distance
    navigator.load_route(waypoints, cmd.target_speed_kmh)
    navigator.start()
    return {"status": "Pure pursuit gestart"}

@router.post("/nav/start_pure_pursuit_direct")
def start_pure_pursuit_direct(cmd: DirectPurePursuitCommand):
    stop_alle_navigatie()
    navigator.lookahead_distance = cmd.lookahead_distance
    navigator.load_route([{"lat": cmd.lat, "lon": cmd.lon}], cmd.target_speed_kmh)
    navigator.start()
    return {"status": "Vloeiende route gestart"}

@router.post("/nav/start_point_to_point")
def start_point_to_point(cmd: DirectNavStartCommand):
    stop_alle_navigatie()
    navigator.lookahead_distance = 1.0 
    navigator.load_route([{"lat": cmd.lat, "lon": cmd.lon}], cmd.target_speed_kmh)
    navigator.start()
    return {"status": "Directe route gestart"}

@router.post("/nav/update_sliders")
def update_sliders(cmd: SliderUpdateCommand):
    if cmd.target_speed_kmh is not None:
        navigator.target_speed_kmh = cmd.target_speed_kmh
    if cmd.lookahead_distance is not None:
        navigator.lookahead_distance = cmd.lookahead_distance
    return {"status": "Parameters geupdate"}

@router.post("/stop_nav")
def stop_navigation():
    stop_alle_navigatie()
    vehicle_controller.stop()
    return {"status": "Gestopt"}

@router.get("/video_feed")
def video_feed():
    if not vision_streamer:
        return {"status": "error", "msg": "Camera feed niet beschikbaar"}
    return StreamingResponse(
        vision_streamer.get_mjpeg_stream(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@router.get("/weeds")
def get_weeds():
    if not vision_streamer:
        return []
    if hasattr(vision_streamer, 'get_latest_weeds'):
        return vision_streamer.get_latest_weeds()
    return []