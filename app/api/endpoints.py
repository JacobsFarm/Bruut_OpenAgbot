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
    speed_kmh: float
    steering_percentage: float

class SteeringEnableCommand(BaseModel):
    enable: bool
    wheel: str = None      # None = beide voorwielen, anders 'left' of 'right'

class SteeringZeroCommand(BaseModel):
    wheel: str = None      # None = beide voorwielen, anders 'left' of 'right'

class SteeringJogCommand(BaseModel):
    left_delta: float = 0.0
    right_delta: float = 0.0

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
    # Missieplan uit data/ab_line.json (gemaakt met AB_mission_maker.py).
    # Zonder deze velden rijdt hij gewoon 0,1,2,... zoals vroeger.
    swath_order: list = None
    aantal_banen: int = None
    banen_overslaan: int = 1
    kopakker_extra_m: float = None
    kant: str = "rechts"

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
        "ab_message": ab_navigator.status_message,
        "current_wp": navigator.current_wp_index if navigator.is_active else 0,
        "current_swath": ab_navigator.current_swath if ab_navigator.is_active else 0,
        # Voortgang door de werkvolgorde, plus of hij in het gewas of op de
        # kopakker rijdt - handig om straks een werktuig aan te koppelen.
        "ab_baan_nr": ab_navigator.order_index + 1 if ab_navigator.is_active else 0,
        "ab_totaal_banen": len(ab_navigator.swath_order),
        "ab_in_werkzone": ab_navigator.in_werkzone
    })
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
    # Schaal op de maximale MIDDENHOEK, niet op de wiellimiet uit de config.
    # Het binnenste voorwiel staat bij Ackermann scherper dan het virtuele
    # midden; zou de schuif op de wiellimiet schalen, dan doet het laatste stuk
    # van zijn bereik niets omdat de VehicleController het toch afkapt.
    max_angle = vehicle_controller.max_center_angle
    actual_angle = (cmd.steering_percentage / 100.0) * max_angle
    vehicle_controller.drive(cmd.speed_kmh, actual_angle)
    return {"status": "driving"}

@router.post("/steering/enable")
def toggle_steering(cmd: SteeringEnableCommand):
    steering = vehicle_controller.stepper_steering
    try:
        if cmd.enable:
            steering.enable(cmd.wheel)
        else:
            steering.disable(cmd.wheel)
    except ValueError as e:
        return {"status": "error", "msg": str(e)}
    return {"status": "success"}

@router.post("/steering/zero")
def zero_steering(cmd: SteeringZeroCommand = None):
    """
    Nulpunt instellen. Zonder body worden beide voorwielen genuld; met
    {"wheel": "left"} of {"wheel": "right"} kalibreer je er een apart.
    Dat laatste is nodig omdat elk voorwiel zijn eigen mechanische nulpunt
    heeft: staan ze niet exact gelijk, dan blijft er spanning op de vooras.
    """
    try:
        vehicle_controller.stepper_steering.set_zero(cmd.wheel if cmd else None)
    except ValueError as e:
        return {"status": "error", "msg": str(e)}
    return {"status": "success"}

@router.post("/steering/jog")
def jog_steering(cmd: SteeringJogCommand):
    """
    Relatieve verplaatsing per wiel in graden, voor het fijn uitlijnen tijdens
    het kalibreren. Werkt alleen op een wiel dat vastgezet (enabled) is.
    """
    vehicle_controller.stepper_steering.jog(cmd.left_delta, cmd.right_delta)
    return {"status": "success"}

@router.get("/steering/status")
def steering_status():
    """Actuele stand van beide voorwielen plus de geldende limieten."""
    steering = vehicle_controller.stepper_steering.get_status()
    return {
        "status": "success" if steering else "no_reply",
        "steering": steering,
        "max_wheel_angle_degrees": vehicle_controller.max_steer_angle,
        "max_center_angle_degrees": vehicle_controller.max_center_angle
    }

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
    ab_navigator.start_mission(
        cmd.work_width_m, cmd.field_length_m, cmd.speed_kmh,
        swath_order=cmd.swath_order,
        aantal_banen=cmd.aantal_banen,
        banen_overslaan=cmd.banen_overslaan,
        kopakker_extra_m=cmd.kopakker_extra_m,
        kant=cmd.kant
    )
    return {
        "status": "started",
        "baan_volgorde": ab_navigator.swath_order,
        "kopakker_extra_m": ab_navigator.headland_overrun_m
    }

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