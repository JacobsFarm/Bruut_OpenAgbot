import os
import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.hardware.gps_logic import GpsSystem
from app.services.vehicle_controller import VehicleController
from app.services.navigator import Navigator
from app.services.ab_navigator import ABNavigator

config_path = os.path.join('data', 'config.example.json')
with open(config_path, 'r') as f:
    config = json.load(f)

gps_system = GpsSystem(config)
vehicle_controller = VehicleController(config)
navigator = Navigator(gps_system, vehicle_controller, config)
ab_navigator = ABNavigator(gps_system, vehicle_controller, config)

from app.api.endpoints import router as api_router

def create_app():
    app = FastAPI(title="Bruut OpenAgbot")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    if os.path.exists("frontend/dist"):
        app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
    else:
        print("WAARSCHUWING: frontend/dist niet gevonden! Draai eerst 'npm run build' in je frontend map.")

    return app