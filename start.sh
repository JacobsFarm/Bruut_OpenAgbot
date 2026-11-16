#!/usr/bin/env bash
# Snelstart voor de robot (Jetson): CAN-bus activeren en de Bruut OpenAgbot-app starten.
#
# Gebruik:   ./start.sh            (CAN aan + app starten)
#            ./start.sh --no-can   (CAN overslaan, bv. zonder VESC's)
#            ./start.sh --browser  (opent ook Chromium op http://localhost:8000)
#
# Eenmalig: chmod +x start.sh
# Optioneel venv: maak ./venv of ./.venv aan, dan wordt die automatisch gebruikt.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

CAN_IF="can1"
CAN_BITRATE=500000
DO_CAN=1
DO_BROWSER=0

for arg in "$@"; do
    case "$arg" in
        --no-can)  DO_CAN=0 ;;
        --browser) DO_BROWSER=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Onbekende optie: $arg"; exit 1 ;;
    esac
done

# --- Config ---
if [ ! -f data/config.json ]; then
    echo "[start] data/config.json bestaat niet, kopieer van config.example.json"
    cp data/config.example.json data/config.json
fi

# --- Virtualenv (optioneel) ---
for v in venv .venv; do
    if [ -f "$v/bin/activate" ]; then
        # shellcheck disable=SC1090
        . "$v/bin/activate"
        echo "[start] virtualenv: $v"
        break
    fi
done

# --- CAN-bus ---
if [ "$DO_CAN" = 1 ]; then
    echo "[start] CAN-bus $CAN_IF activeren (sudo-wachtwoord kan gevraagd worden)"
    sudo modprobe gs_usb 2>/dev/null
    if ip link show "$CAN_IF" >/dev/null 2>&1; then
        sudo ip link set "$CAN_IF" down
        sudo ip link set "$CAN_IF" type can bitrate "$CAN_BITRATE" loopback off \
            && sudo ip link set "$CAN_IF" up \
            && echo "[start] $CAN_IF online ($CAN_BITRATE bit/s)" \
            || echo "[start] WAARSCHUWING: $CAN_IF kon niet geactiveerd worden"
    else
        echo "[start] WAARSCHUWING: $CAN_IF niet gevonden. Adapter aangesloten? (zie ip link)"
    fi
fi

# --- Browser (optioneel, na een paar seconden zodat de server er is) ---
if [ "$DO_BROWSER" = 1 ]; then
    BROWSER="$(command -v chromium-browser || command -v chromium || command -v google-chrome || command -v xdg-open)"
    if [ -n "$BROWSER" ]; then
        ( sleep 5 && "$BROWSER" http://localhost:8000 >/dev/null 2>&1 ) &
    fi
fi

# --- App ---
echo "[start] app starten (Ctrl+C om te stoppen)"
exec python3 run.py
