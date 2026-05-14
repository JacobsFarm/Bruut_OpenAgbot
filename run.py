import uvicorn
import socket
from app import create_app

# Functie om het lokale IP-adres te vinden
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # We maken geen echte verbinding, maar gebruiken dit om de interface te bepalen
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# Initialiseer de FastAPI applicatie
app = create_app()

if __name__ == '__main__':
    local_ip = get_local_ip()
    print("🚀 Bruut OpenAgbot Server start op...")
    print(f"👉 Toegang via de robot zelf: http://localhost:8000")
    print(f"👉 Toegang via het netwerk (Wifi/Hotspot): http://{local_ip}:8000")
    
    # Start de webserver op 0.0.0.0 zodat deze op alle interfaces luistert
    uvicorn.run("run:app", host="0.0.0.0", port=8000, reload=False)
