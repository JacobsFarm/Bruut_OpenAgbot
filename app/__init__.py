import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.hardware.gps_logic import GpsSystem
from app.services.vehicle_controller import VehicleController
from app.services.navigator import Navigator
from app.services.ab_navigator import ABNavigator

# Gebruik je eigen 'config.json' als die bestaat; val anders terug op de
# meegeleverde 'config.example.json' (het sjabloon).
config_path = os.path.join('data', 'config.json')
if not os.path.exists(config_path):
    config_path = os.path.join('data', 'config.example.json')
    print(f"⚠️ Geen data/config.json gevonden, val terug op {config_path}")

print(f"⚙️  Configuratie geladen uit: {config_path}")
with open(config_path, 'r') as f:
    config = json.load(f)

gps_system = GpsSystem(config)
vehicle_controller = VehicleController(config)
navigator = Navigator(gps_system, vehicle_controller, config)
ab_navigator = ABNavigator(gps_system, vehicle_controller, config)

from app.api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app):
    yield
    # Bij afsluiten (Ctrl+C) de navigatie stoppen en de wielen zelf stilzetten,
    # in plaats van te wachten tot de VESC-timeout ze uitzet.
    for nav in (navigator, ab_navigator):
        if nav.is_active:
            nav.stop()
    vehicle_controller.shutdown()

def create_app():
    app = FastAPI(title="Bruut OpenAgbot", lifespan=lifespan)

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