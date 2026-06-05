from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.vision.streamer import VisionStreamer
from app.hardware import config
import json
import os
import glob

# Hardware initialisatie en Services
from app.hardware import motor_controller, gps_system
from app.hardware.stepper_logic import StepperSteering
from app.services.navigator import Navigator, speed_mps_to_dac

# Initialiseer Vision (bestaande functionaliteit)
vision_streamer = VisionStreamer(config)
vision_streamer.start()

# Initialiseer de nieuwe Tricycle-gebaseerde sturing en navigator
stuur_controller = StepperSteering(config)
navigator = Navigator(gps_system, motor_controller, stuur_controller)

router = APIRouter()
WAYPOINTS_FILE = 'data/waypoints.json'

# ==========================================
# PYDANTIC DATA MODELLEN (Voor de Frontend)
# ==========================================

class Waypoint(BaseModel):
    lat: float
    lon: float

class PurePursuitStartCommand(BaseModel):
    target_speed_kmh: float
    lookahead_distance: float
    gain: float

class DirectNavStartCommand(BaseModel):
    lat: float
    lon: float
    target_speed_kmh: float
    gain: float

# <-- NIEUW: Specifiek model voor een Pure Pursuit bocht naar 1 specifiek coördinaat
class DirectPurePursuitCommand(BaseModel):
    lat: float
    lon: float
    target_speed_kmh: float
    lookahead_distance: float
    gain: float

class SliderUpdateCommand(BaseModel):
    target_speed_kmh: float = None
    lookahead_distance: float = None
    gain: float = None

class JoystickCommand(BaseModel):
    x: float  # -1.0 (volledig links) tot 1.0 (volledig rechts)
    y: float  # 0.0 (stilstand) tot 1.0 (volledig vooruit gas)
    target_speed_kmh: float # Snelheid gekoppeld aan de frontend slider

class EnableRequest(BaseModel):
    enable: bool


# ==========================================
# 1. ALGEMENE STATUS & NOODSTOP
# ==========================================

@router.get("/status")
def get_status():
    """Haal de huidige positie op voor de UI map"""
    return gps_system.current_position

@router.post("/stop")
def noodstop():
    """Directe mechanische stop via webinterface of fysieke knop"""
    navigator.stop()
    
    # HARDWARE STOP FORCEER: direct de rem-waarde 700 naar beide achterwielen
    motor_controller.stuur_motoren(700, 700)
    
    # Vergrendel de stappenmotor zodat het wiel niet ongecontroleerd wegzwenkt
    stuur_controller.enable()
    
    return {"status": "Noodstop actief! Aandrijving neutraal, stuurwiel vastgezet."}


# ==========================================
# 2. AUTONOME NAVIGATIE (Lijnen & Punten)
# ==========================================

@router.post("/nav/start_pure_pursuit")
def start_pure_pursuit(cmd: PurePursuitStartCommand):
    """Start de route via de Pure Pursuit methode (strak langs de lijnen)"""
    wps = laad_waypoints()
    if not wps:
        raise HTTPException(status_code=400, detail="Geen route geladen in waypoints.json")
    
    navigator.start(
        waypoints=wps, 
        mode="pure_pursuit", 
        target_speed_kmh=cmd.target_speed_kmh, 
        lookahead_distance=cmd.lookahead_distance, 
        gain=cmd.gain
    )
    return {"status": "Pure Pursuit gestart"}

@router.post("/nav/start_point_to_point")
def start_point_to_point(cmd: DirectNavStartCommand):
    """Rijdt direct naar een specifiek aangetikt punt in een rechte lijn (snappen)"""
    navigator.start(
        waypoints=[{"lat": cmd.lat, "lon": cmd.lon}], 
        mode="point_to_point", 
        target_speed_kmh=cmd.target_speed_kmh, 
        lookahead_distance=1.0, # Lookahead is niet relevant voor point-to-point
        gain=cmd.gain
    )
    return {"status": "Directe navigatie naar punt gestart"}

# <-- NIEUW: Endpoint voor een Vloeiende bocht naar 1 specifiek coördinaat
@router.post("/nav/start_pure_pursuit_direct")
def start_pure_pursuit_direct(cmd: DirectPurePursuitCommand):
    """Rijdt naar een specifiek aangetikt punt met de vloeiende Pure Pursuit wiskunde"""
    navigator.start(
        waypoints=[{"lat": cmd.lat, "lon": cmd.lon}], 
        mode="pure_pursuit", 
        target_speed_kmh=cmd.target_speed_kmh, 
        lookahead_distance=cmd.lookahead_distance, 
        gain=cmd.gain
    )
    return {"status": "Vloeiende route (Pure Pursuit) naar punt gestart"}

@router.post("/nav/update_sliders")
def update_sliders(cmd: SliderUpdateCommand):
    """Ontvangt live wijzigingen als de gebruiker aan de Svelte sliders schuift"""
    navigator.update_sliders(
        target_speed_kmh=cmd.target_speed_kmh,
        lookahead_distance=cmd.lookahead_distance,
        gain=cmd.gain
    )
    return {"status": "Parameters succesvol bijgesteld tijdens rit"}

@router.post("/stop_nav")
def stop_navigation():
    """Stopt de autonome route op een nette manier"""
    navigator.stop()
    return {"status": "Autonome navigatie netjes gestopt"}


# ==========================================
# 3. HANDMATIGE BESTURING (Telefoon Joystick)
# ==========================================

@router.post("/nav/joystick")
def verwerk_joystick(cmd: JoystickCommand):
    """
    Ontvangt live joystick data vanuit de Svelte frontend.
    Ondersteunt het elektronisch differentieel voor vloeiende bochten.
    """
    # Schakel autonome navigatie uit als de telefoon de besturing overneemt
    if navigator.active:
        navigator.stop()

    # Bereken de hoek voor de stappenmotor
    max_stuur_uitslag = config.get("steering", {}).get("max_angle_degrees", 45.0)
    berekende_hoek = cmd.x * max_stuur_uitslag
    stuur_controller.set_angle(berekende_hoek)

    # Bereken basis gas/snelheid
    joystick_gas = max(0.0, min(1.0, cmd.y))
    huidige_snelheid_kmh = joystick_gas * cmd.target_speed_kmh
    target_mps = huidige_snelheid_kmh / 3.6
    
    mps_links = target_mps
    mps_rechts = target_mps

    # --- Elektronisch Differentieel ---
    diff_sterkte = navigator.differentieel_sterkte 
    
    if diff_sterkte > 0.0 and target_mps > 0:
        draai_factor = abs(berekende_hoek) / max_stuur_uitslag
        snelheids_reductie = 1.0 - (draai_factor * diff_sterkte)
        
        # Welk wiel is de binnenbocht? Die moet zachter draaien.
        if berekende_hoek > 2.0:
            mps_rechts = target_mps * snelheids_reductie
        elif berekende_hoek < -2.0:
            mps_links = target_mps * snelheids_reductie

    # Vertaal snelheden naar DAC waarden voor de hubmotoren
    dac_l = speed_mps_to_dac(mps_links)
    dac_r = speed_mps_to_dac(mps_rechts)

    motor_controller.stuur_motoren(dac_l, dac_r)

    return {
        "status": "manual_control", 
        "stuurhoek": berekende_hoek, 
        "dac_links": dac_l,
        "dac_rechts": dac_r
    }


# ==========================================
# 4. STUUR HARDWARE & KALIBRATIE
# ==========================================

@router.get("/steering/position")
def get_steering_position():
    """Vraag de fysieke hoek van het zwenkwiel op voor de frontend UI."""
    pos = stuur_controller.get_position()
    if pos is not None:
        return {"status": "success", "position": pos}
    raise HTTPException(status_code=500, detail="Kan positie niet lezen van Arduino")

@router.post("/steering/enable")
def set_steering_enable(req: EnableRequest):
    """Zet de stappenmotor vast (True) of in vrijloop (False) om handmatig te verplaatsen."""
    if req.enable:
        stuur_controller.enable()
        return {"status": "success", "state": "enabled"}
    else:
        stuur_controller.disable()
        return {"status": "success", "state": "disabled"}

@router.post("/steering/zero")
def set_steering_zero():
    """Sla de huidige fysieke wielpositie op als 0 graden (rechtuit)."""
    stuur_controller.set_zero()
    return {"status": "success", "message": "Nulpunt succesvol gekalibreerd."}


# ==========================================
# 5. WAYPOINTS DATA BEHEER (Bestaand)
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


# ==========================================
# 6. ONKRUID DETECTIE / VISION FEED (Bestaand)
# ==========================================

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