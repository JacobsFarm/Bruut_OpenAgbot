import json
from .motor_logic import MotorController
from .gps_logic import GpsSystem

# Laad de configuratie
with open('data/config.json', 'r') as f:
    config = json.load(f)

# Start de hardware controllers als globale objecten (Singletons)
# Zodra de applicatie start, maken deze direct verbinding met de /dev/ttyACM* poorten
motor_controller = MotorController(
    port=config['hardware']['arduino_port'], 
    baudrate=config['hardware']['arduino_baudrate']
)

gps_system = GpsSystem(config)