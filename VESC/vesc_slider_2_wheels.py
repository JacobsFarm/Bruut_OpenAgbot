#!/usr/bin/env python3
"""Dubbele schuifregelaar voor 2 VESC's over CAN met koppel-optie.

Stuurt SET_RPM op 50 Hz naar beide VESC's en leest Status 1, 4 en 5 uit.
Wielen vrij van de grond voordat je dit draait.

    sudo ip link set can0 up type can bitrate 500000
    pip install python-can
    python3 vesc_dual_slider.py
"""

import struct
import threading
import time
import tkinter as tk

import can

# --- Opstelling ------------------------------------------------------------
CHANNEL = "can0"
VESC_1_ID = 1
VESC_2_ID = 2

POLE_PAIRS = 10        # Quinder 8": 20 polen
GEAR_RATIO = 5.0       # 5:1 reductie
WHEEL_CIRC_M = 0.638   # pi * 0,2032 m

ERPM_MAX = 3000        # 60 rpm wiel, 0,64 m/s
SEND_HZ = 50           # Timeout in de VESC staat standaard op 1000 ms
SLEW_ERPM_PER_S = 3000 # Max versnelling (eRPM per seconde)
BRAKE_A = 3.0          # Remstroom bij stoppen en afsluiten

# --- CAN-pakket-ID's uit bldc/datatypes.h ----------------------------------
SET_CURRENT_BRAKE = 2
SET_RPM = 3
STATUS_1 = 9
STATUS_2 = 14
STATUS_3 = 15
STATUS_4 = 16
STATUS_5 = 27

TACHO_PER_REV = 6 * POLE_PAIRS * GEAR_RATIO


class Vesc:
    def __init__(self, bus: can.Bus, vesc_id: int):
        self.bus = bus
        self.id = vesc_id
        self.target = 0.0
        self.sent = 0.0
        self.tele = {
            "erpm": 0, "current": 0.0, "duty": 0.0, "volt": 0.0,
            "temp": 0.0, "amps_in": 0.0, "tacho": 0,
            "ah": 0.0, "ah_chg": 0.0, "wh": 0.0, "wh_chg": 0.0
        }
        self.last_rx = None
        self.tacho_zero = None
        self.running = True

        threading.Thread(target=self._tx, daemon=True).start()

    def _frame(self, cmd: int, payload: bytes) -> can.Message:
        return can.Message(
            arbitration_id=(cmd << 8) | self.id,
            data=payload,
            is_extended_id=True
        )

    def _tx(self):
        dt = 1.0 / SEND_HZ
        step = SLEW_ERPM_PER_S * dt
        while self.running:
            delta = self.target - self.sent
            self.sent += max(-step, min(step, delta))
            try:
                self.bus.send(self._frame(SET_RPM, struct.pack(">i", int(self.sent))))
            except can.CanError:
                pass
            time.sleep(dt)

    def handle_msg(self, msg: can.Message):
        self.last_rx = time.monotonic()
        cmd = msg.arbitration_id >> 8

        if cmd == STATUS_1:
            erpm, cur, duty = struct.unpack(">ihh", msg.data)
            self.tele.update(erpm=erpm, current=cur / 10.0, duty=duty / 1000.0)
        elif cmd == STATUS_2:
            ah, ah_chg = struct.unpack(">ii", msg.data)
            self.tele.update(ah=ah / 1e4, ah_chg=ah_chg / 1e4)
        elif cmd == STATUS_3:
            wh, wh_chg = struct.unpack(">ii", msg.data)
            self.tele.update(wh=wh / 1e4, wh_chg=wh_chg / 1e4)
        elif cmd == STATUS_4:
            t_fet, _t_mot, i_in, _pos = struct.unpack(">hhhh", msg.data)
            self.tele.update(temp=t_fet / 10.0, amps_in=i_in / 10.0)
        elif cmd == STATUS_5:
            tacho, v_in, _res = struct.unpack(">ihh", msg.data)
            if self.tacho_zero is None:
                self.tacho_zero = tacho
            self.tele.update(tacho=tacho - self.tacho_zero, volt=v_in / 10.0)

    def brake(self):
        self.target = 0.0
        self.sent = 0.0
        payload = struct.pack(">i", int(BRAKE_A * 1000))
        for _ in range(3):
            try:
                self.bus.send(self._frame(SET_CURRENT_BRAKE, payload))
            except can.CanError:
                pass
            time.sleep(0.01)

    def stop(self):
        self.running = False
        self.brake()


def can_rx_loop(bus: can.Bus, vescs: dict[int, Vesc], running_flag: list[bool]):
    """Één centrale listener thread voor alle VESC's over de CAN-bus."""
    while running_flag[0]:
        msg = bus.recv(timeout=0.2)
        if msg is None or not msg.is_extended_id or len(msg.data) < 8:
            continue
        vesc_id = msg.arbitration_id & 0xFF
        if vesc_id in vescs:
            vescs[vesc_id].handle_msg(msg)


def format_telemetry(vesc: Vesc, name: str) -> str:
    t = vesc.tele
    wheel_rpm = t["erpm"] / (POLE_PAIRS * GEAR_RATIO)
    speed = wheel_rpm / 60.0 * WHEEL_CIRC_M
    dist = t["tacho"] / TACHO_PER_REV * WHEEL_CIRC_M

    if vesc.last_rx is None:
        link = "geen data"
    else:
        age = time.monotonic() - vesc.last_rx
        link = f"{age * 1000:4.0f} ms" + (" (!)" if age > 1.0 else "")

    return (
        f"--- {name} (ID {vesc.id}) ---\n"
        f"Status:       {link}\n\n"
        f"Gevraagd:     {vesc.sent:8.0f} eRPM\n"
        f"Gemeten:      {t['erpm']:8d} eRPM\n"
        f"Wiel RPM:     {wheel_rpm:8.1f} rpm\n"
        f"Snelheid:     {speed * 3.6:8.2f} km/h\n"
        f"Afstand:      {dist:8.2f} m\n\n"
        f"Duty cycle:   {t['duty'] * 100:8.1f} %\n"
        f"Motorstroom:  {t['current']:8.1f} A\n"
        f"Accustroom:   {t['amps_in']:8.1f} A\n"
        f"Spanning:     {t['volt']:8.1f} V\n"
        f"FET Temp:     {t['temp']:8.1f} °C"
    )


def main():
    bus = can.Bus(channel=CHANNEL, interface="socketcan")
    vesc1 = Vesc(bus, VESC_1_ID)
    vesc2 = Vesc(bus, VESC_2_ID)
    vescs = {VESC_1_ID: vesc1, VESC_2_ID: vesc2}

    running_flag = [True]
    threading.Thread(target=can_rx_loop, args=(bus, vescs, running_flag), daemon=True).start()

    root = tk.Tk()
    root.title("Dual VESC CAN Controller")

    main_frame = tk.Frame(root, padx=16, pady=14)
    main_frame.pack()

    # Koppel checkbox
    linked_var = tk.BooleanVar(value=False)
    syncing = [False]  # Voorkomt recursieve callbacks tussen de sliders

    link_check = tk.Checkbutton(
        main_frame,
        text="Koppel wielen (beide motoren synchroon)",
        variable=linked_var,
        font=("sans-serif", 11, "bold")
    )
    link_check.pack(pady=(0, 12))

    # Frame voor de twee sliders naast elkaar
    sliders_frame = tk.Frame(main_frame)
    sliders_frame.pack(fill=tk.X)

    def on_slider1(val):
        target = float(val)
        vesc1.target = target
        if linked_var.get() and not syncing[0]:
            syncing[0] = True
            slider2.set(target)
            vesc2.target = target
            syncing[0] = False

    def on_slider2(val):
        target = float(val)
        vesc2.target = target
        if linked_var.get() and not syncing[0]:
            syncing[0] = True
            slider1.set(target)
            vesc1.target = target
            syncing[0] = False

    col1 = tk.Frame(sliders_frame)
    col1.pack(side=tk.LEFT, padx=10)
    tk.Label(col1, text=f"Wiel Links (ID {VESC_1_ID})", font=("sans-serif", 10, "bold")).pack()
    slider1 = tk.Scale(col1, from_=-ERPM_MAX, to=ERPM_MAX, resolution=10,
                       orient=tk.HORIZONTAL, length=320, command=on_slider1)
    slider1.pack()

    col2 = tk.Frame(sliders_frame)
    col2.pack(side=tk.RIGHT, padx=10)
    tk.Label(col2, text=f"Wiel Rechts (ID {VESC_2_ID})", font=("sans-serif", 10, "bold")).pack()
    slider2 = tk.Scale(col2, from_=-ERPM_MAX, to=ERPM_MAX, resolution=10,
                       orient=tk.HORIZONTAL, length=320, command=on_slider2)
    slider2.pack()

    # Stopknop
    def stop(_event=None):
        slider1.set(0)
        slider2.set(0)
        vesc1.brake()
        vesc2.brake()

    tk.Button(main_frame, text="STOP ALLES (spatie)", command=stop,
              bg="#cc3333", fg="white", font=("sans-serif", 11, "bold"),
              height=2, width=30).pack(pady=(14, 14))
    root.bind("<space>", stop)

    # Telemetrie velden naast elkaar
    tele_frame = tk.Frame(main_frame)
    tele_frame.pack(fill=tk.BOTH, expand=True)

    readout1 = tk.Label(tele_frame, font=("monospace", 10), justify=tk.LEFT, relief=tk.GROOVE, padx=8, pady=8)
    readout1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

    readout2 = tk.Label(tele_frame, font=("monospace", 10), justify=tk.LEFT, relief=tk.GROOVE, padx=8, pady=8)
    readout2.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)

    def refresh():
        readout1.config(text=format_telemetry(vesc1, "Wiel Links"))
        readout2.config(text=format_telemetry(vesc2, "Wiel Rechts"))
        root.after(100, refresh)

    refresh()

    def on_close():
        running_flag[0] = False
        vesc1.stop()
        vesc2.stop()
        time.sleep(0.1)
        bus.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
