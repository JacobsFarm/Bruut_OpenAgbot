# CAN wiring: Innomaker USB2CAN → VESC Classic 100V

Innomaker USB2CAN Module (bare board, DB9 male, micro-USB) on a Jetson, talking to a VESC Classic 100V over CAN at 500 kbit/s.

> **Never connect Pin 1 to 5 volt on the VSEC, its a 5 V output on both connectors.** The Innomaker is USB-powered, the VESC is battery-powered. Linking those two pins puts two supplies against each other, will blow up the controller and computer.

## Connect these 3 wires

```text
INNOMAKER DB9 (male)         VESC CLASSIC  CAN, 4-pin JST-GH 1.25 mm

pin 7  CAN_H   ───────────── pin 2  CANH    ┐ twisted pair
pin 2  CAN_L   ───────────── pin 3  CANL    ┘
pin 3  CAN_GND ───────────── pin 4  GND

pin 1  5V      ─ leave open ─ pin 1  +5V
DB9 pins 4, 5, 6, 8, 9: NC
```
<img width="1110" height="339" alt="Innomaker USB2CAN diagram" src="https://github.com/user-attachments/assets/e1c7bbeb-e966-41a6-a4b0-565d36d54047" />

| Innomaker DB9 | Function | VESC CAN | Function |
|---|---|---|---|
| pin 7 | CAN_H, dominant high | pin 2 | CANH, ±60 V |
| pin 2 | CAN_L, dominant low | pin 3 | CANL, ±60 V |
| pin 3 | CAN_GND | pin 4 | GND, 1 A |
| pin 1 | 5 V out — only live if R9 is fitted | pin 1 | +5 V out, 1 A — **do not connect** |

- **Run CAN_H and CAN_L as a twisted pair**, roughly one turn per 2 cm.
- **The ground wire is not optional.** The Innomaker's transceiver is isolated (ISO1050); without CAN_GND it has no reference against the VESC and you get random error frames.
- Keep the CAN cable away from the phase wires — crossing at right angles is fine, running parallel is not. Alongside the motor, use shielded cable and ground the shield at one end only.
- Wire colours are free; nothing in the VESC depends on them.

## No open end

A CAN bus is a straight line with 120 Ω between CAN_H and CAN_L at **each** end. A wire left dangling reflects the signal and produces bit errors as soon as speed or length goes up.

Adding more VESCs later: daisy-chain wheel to wheel, stubs under 30 cm, and only the **two outermost** nodes get a resistor. With the Jetson at one end, the last VESC in the chain is the other.

## Termination

| Side | What to do |
|---|---|
| Innomaker USB2CAN Module | 120 Ω is on the board. Fit the jumper next to the DB9 — manual p. 11, *Enable 120 Ohm Resistor*. It usually ships disabled. |
| VESC Classic 100V | No termination on the board (not in the datasheet, confirmed by measurement). Solder a plain 120 Ω ¼ W across pins 2 and 3 of the JST-GH connector, or use a T-splitter with a resistor. |

Measure across CAN_H and CAN_L with the battery disconnected and USB unplugged:

| Reading | Meaning |
|---|---|
| open / very high | no termination at all |
| ≈ 120 Ω | one end terminated, the other still missing |
| ≈ 60 Ω | both ends terminated — this is what you want |

Also check CAN_H→GND and CAN_L→GND: both must be high impedance. If not, there's a solder bridge in the DB9.

## Bring it up on the Jetson

The module is a gs_usb SocketCAN device — no driver to install, it appears as `can0`. VESC defaults to 500 kbit/s.

```bash
sudo ip link set can0 up type can bitrate 500000
candump can0
```

`restart-ms` is not supported by gs_usb — `ip link set can0 up` fails with *"Device doesn't support restart from Bus Off"* if you pass it. Recovery from bus-off has to be done in software instead.

## VESC Tool

*App Settings → General*:

| Setting | Value |
|---|---|
| CAN Baud Rate | `CAN_BAUD_500K` |
| CAN Mode | `VESC` |
| VESC ID | `1`, `2`, `3`, `4` — unique per controller |
| Can Status Rate 1 | `50` Hz, tick **Status 1** |
| Can Status Rate 2 | `5` Hz, tick **Status 4** and **Status 5** |

Status 1 at 50 Hz is the control loop; the rest belongs on the slow group. Four VESCs × 5 messages × 50 Hz is a quarter of the bus; Status 1 fast and the rest at 5 Hz is about 6%.

> **Write with ↑A, not ↑M.** VESC Tool keeps motor and app configuration separate, each with its own toolbar buttons. Writing App Settings with the motor-config button (↑M) silently discards them — the screen keeps showing your ticks while the controller never received them. Verify with ↓A: if the boxes survive a read-back, it landed.

## What comes over the bus

Extended IDs, built as `command << 8 | VESC ID`. For VESC ID 1:

| ID | Command | Contents |
|---|---|---|
| `0x901` | 9, STATUS | eRPM, motor current, duty — 50 Hz |
| `0x1001` | 16, STATUS_4 | temperatures, motor current |
| `0x1B01` | 27, STATUS_5 | input voltage, tacho |
| `0x3901` | 57, NOTIFY_BOOT | payload is the ASCII hardware name, sent once at power-up |

Status 1, all big-endian:

| Bytes | Value |
|---|---|
| 0–3 | eRPM, int32 |
| 4–5 | motor current, int16, ÷10 → A |
| 6–7 | duty cycle, int16, ÷1000 → fraction |

The Quinder has 20 poles = 10 pole pairs, so wheel RPM = eRPM ÷ 10. At standstill expect `00 00 00 00 00 00 FF FC`: zero rpm, zero current, −0.4% duty of noise around zero.

A useful check that does not depend on any status setting — ping controller 1 and watch for a reply:

```bash
cansend can0 00001101#00
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Rising `bus-errors` | missing ground wire, CAN_H/CAN_L swapped, or termination |
| `state BUS-OFF` / `ERROR-PASSIVE` | bitrate mismatch between the two ends |
| Silence, all counters zero | the VESC is not sending — Status boxes not ticked, or written with ↑M |
| A single frame at power-up, then nothing | NOTIFY_BOOT works, so the link is fine; it is the status config |

Check with `ip -details -statistics link show can0`. Note that a `cansend` on a bus with no second node **always** fails: nobody acknowledges the frame, the TX error counter climbs and the interface goes bus-off. That is CAN working as designed, not a broken adapter. Use `loopback on` to test the adapter by itself.

## Cable build

The module has a DB9 male, so you need a female solder-cup connector. For the VESC side, cut a ready-made VESC CAN lead in half: it already has crimped 1.25 mm JST-GH contacts, which are hard to crimp well by hand.

---

Sources: Innomaker USB2CAN Device UserManual v2.0 §4.1 (pinout, 120 Ω jumper); VESC Classic 100V datasheet rev. April 2026, table 2; ISO 11898-2:2016.

Full Dutch version with diagram: [can_vesc_bedrading.html](can_vesc_bedrading.html)
