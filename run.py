import uvicorn
from app import create_app

# Initialiseer de FastAPI applicatie
app = create_app()

if __name__ == '__main__':
    print("🚀 Bruut OpenAgbot Server start op...")
    print("👉 Open je browser en ga naar: http://localhost:8000")
    # Start de webserver
    uvicorn.run("run:app", host="0.0.0.0", port=8000, reload=False)