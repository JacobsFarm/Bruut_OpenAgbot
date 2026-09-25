# Startup CAN-bus

Op de Orin Nano (robot-PC) moet de CAN-bus na elke reboot of na het los- en vastmaken van de adapter opnieuw worden geactiveerd.

## Welke interface?

| Interface | Wat |
|-----------|-----|
| `can0` | Interne CAN-controller van de Jetson (mttcan). Niet gebruiken voor de VESC's. |
| `can1` | InnoMaker USB2CAN-adapter. Hier hangen de VESC's aan (ID 1 links, ID 2 rechts). |

De app gebruikt `can_channel: "can1"` (zie `data/config.example.json`).

## Activeren

```bash
sudo ip link set can1 down && sudo ip link set can1 type can bitrate 500000 loopback off && sudo ip link set can1 up
```

## Controleren

Staat de interface online en zijn er geen bus-fouten?

```bash
ip link show can1
```

Sturen de VESC's frames? (VESC's moeten aan staan.)

```bash
candump can1
```

## Problemen

- **Geen frames / BUS-OFF:** controleer dat de VESC's aan staan, dat de bitrate 500000 is en dat de bus aan beide uiteinden een 120 Ω-afsluiting heeft. Voer daarna de `down`/`up`-stappen hierboven opnieuw uit.
- **`can1` bestaat niet:** adapter niet herkend. Controleer de USB-kabel en `ip link`.
- **Oude scripts noemen `can0`:** `VESC/vesc_slider_2_wheels.py` heeft `can0` in de header. Op deze machine moet dat `can1` zijn.

## Automatisch bij opstarten (optioneel)

Nog niet ingesteld. Kan met een systemd-service of udev-regel die bovenstaand commando uitvoert zodra `can1` verschijnt.

Zie ook: `innomaker_usb2can_jetson_setup.json` en `VESC/README_DEV.md`.
