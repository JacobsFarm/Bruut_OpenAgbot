# Motor wiring: Quinder 8" hub motor → VESC Classic 100V

Quinder 8" 48 V 550 W (10101025). Motor cable: 3 × 2.5 mm² + 8 × 0.14 mm², 200 mm.

> **Blue, green and yellow are in the cable twice.** Sort by thickness, not by colour:
> **2.5 mm² = phase, 0.14 mm² = hall.** 48 V on a hall wire kills the sensors inside the hub.

## Connect these 8 wires

```text
MOTOR                        VESC CLASSIC 100V

Phase, 2.5 mm²               Phase bullets, 5.5 mm
  blue   ─────────────────── U
  green  ─────────────────── V
  yellow ─────────────────── W

Hall, 0.14 mm²               SENSORS, 6-pin JST-GH 1.25 mm
  red    ─────────────────── pin 6  +5V
                             pin 5  TEMP  (leave empty)
  blue   ─────────────────── pin 4  H1
  green  ─────────────────── pin 3  H2
  yellow ─────────────────── pin 2  H3
  black  ─────────────────── pin 1  GND

Not connected, 0.14 mm²
  white, purple, orange: insulate each one separately and label it
```

**SENSORS pin numbers:** count from the pin 1 mark on the PCB, not from the direction the printed labels read.

## What the 8 thin wires do

The five hall wires tell the VESC where the rotor is, so it can start and run smoothly at low speed.

| Wire   | Function |
|--------|----------|
| Red    | Hall supply + |
| Black  | Hall supply − (ground) |
| Blue   | Hall signal A |
| Green  | Hall signal B |
| Yellow | Hall signal C |
| White  | Speed pulse, 6 per revolution. *Not connected*: the VESC gets speed from the halls. |
| Purple | Motor temperature, 3-level active output (4.8 → 0.67 V), warning at 105 °C, cut-off at 110 °C. *Not connected.* |
| Orange | Not in the motor spec. *Not connected*: unknown, measure it before you cut it off. |

- **Red on +5V, black on GND.** Swapping these two destroys the hall sensors.
- The hall signal order on H1–H3 doesn't matter: hall detection in VESC Tool works it out.
- Purple is an active output, not an NTC, so it can't go on TEMP pin 5.

## 3-phase wiring

- Blue, green, yellow (phase A, B, C) → U, V, W, on 5.5 mm bullets, each in its own heat shrink.
- Phase order only decides which way the wheel turns. Runs backwards? Swap any two phase wires and re-run detection, or use *Invert Motor Direction*. Don't swap hall wires for this.
- 2.5 mm² is enough for the motor's 20 A max. The lead is only 200 mm, so extend it with 2.5 mm² or thicker.
- Route the hall wires away from the phase wires: twisted, crossing at right angles.

## VESC Tool

- *Sensor Port Mode*: **Hall**
- *Motor Temp Sensor*: **Disabled** (purple is not connected)
- *Motor Current Max*: **15 A**. Without purple there is no motor over-temperature protection, so this limit is all you have.

---

Sources: Quinder 8" 48V spec (ver. 2024-01A), VESC Classic 100V datasheet (rev. April 2026, table 2).

Full Dutch version with background: [quinder_motor_bedrading.html](quinder_motor_bedrading.html)
