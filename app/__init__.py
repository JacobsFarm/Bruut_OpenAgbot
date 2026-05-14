from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router as api_router
import os

def create_app():
    app = FastAPI(title="Bruut OpenAgbot")

    # Voorkomt verbindingsproblemen tijdens lokaal testen
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 1. Koppel onze nieuwe Agbot API (Motor, GPS, Vision)
    app.include_router(api_router, prefix="/api")

    # 2. Serveer de Svelte frontend map (de /dist map die je hebt gebouwd)
    if os.path.exists("frontend/dist"):
        app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
    else:
        print("WAARSCHUWING: frontend/dist niet gevonden! Draai eerst 'npm run build' in je frontend map.")

    return app