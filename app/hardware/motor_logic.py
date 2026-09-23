import math
import time
import logging

from app.hardware.vesc_can import VescBus, fault_name

# Kolommen die deze module aan elke ritlog toevoegt (zie log_snapshot()).
LOG_COLUMNS = [
    # Per wiel
    "ERPM_Doel_L", "ERPM_Doel_R", "ERPM_L", "ERPM_R",
    "Wiel_kmh_L", "Wiel_kmh_R", "Duty_L", "Duty_R",
    "Motorstroom_L_A", "Motorstroom_R_A", "Accustroom_L_A", "Accustroom_R_A",
    "Temp_FET_L_C", "Temp_FET_R_C", "Motortemp_model_L_C", "Motortemp_model_R_C",
    "Afstand_L_m", "Afstand_R_m",
    # Accu
    "Accu_V", "Accu_A", "Accu_W", "Accu_pct",
    "Verbruikt_Ah", "Verbruikt_Wh", "Teruggeleverd_Ah", "Teruggeleverd_Wh",
    # Toestand
    "Aandrijving",
]

# Rustspanning per cel -> lading in %, voor NMC-cellen zoals de Samsung
# INR18650-25R in het EGO-pak. Een grove kromme: goed genoeg voor een balk op
# het dashboard, niet om de laatste procenten op af te rekenen.
OCV_PER_CELL = (
    (3.00, 0), (3.45, 5), (3.68, 10), (3.74, 20), (3.77, 30), (3.79, 40),
    (3.82, 50), (3.87, 60), (3.92, 70), (3.98, 80), (4.06, 90), (4.20, 100),
)


def soc_from_cell_voltage(volt):
    """Lading in % bij een rustspanning per cel, lineair tussen de punten."""
    if volt <= OCV_PER_CELL[0][0]:
        return 0.0
    for (v0, p0), (v1, p1) in zip(OCV_PER_CELL, OCV_PER_CELL[1:]):
        if volt <= v1:
            return p0 + (p1 - p0) * (volt - v0) / (v1 - v0)
    return 100.0


class _Wheel:
    """Eén achterwiel: de VESC plus de beveiligingstoestand die wij bijhouden."""

    def __init__(self, key, node):
        self.key = key            # 'left' / 'right', zoals in de API
        self.node = node
        self.erpm_cmd = 0         # laatst verstuurde eRPM
        self.stall_since = None   # sinds wanneer het wiel vast lijkt te zitten
        self.heat = 0.0           # thermisch model: kelvin boven de omgeving


class MotorController:
    """
    De twee aangedreven achterwielen als geheel: twee VESC's op één CAN-bus.

    Snelheid is een eRPM die de VESC zelf vasthoudt (SET_RPM, de regellus zit
    in de controller). Deze klasse rekent m/s om naar eRPM, bewaakt de grenzen
    en de beveiligingslagen uit VESC/README_DEV.md: verbinding, foutcodes,
    stall-detectie en het thermisch model op de gemeten motorstroom.

    Het zenden gebeurt vanuit de regellus van de VehicleController (50 Hz),
    ook bij stilstand. Stopt die lus, dan stoppen de frames en zetten beide
    VESC's zichzelf uit na hun eigen timeout.
    """

    FAULT_POLL_S = 0.5    # foutcode opvragen, per VESC
    FAULT_STALE_S = 3.0   # zo lang blijft een uitgelezen foutcode geldig

    def __init__(self, config):
        self.logger = logging.getLogger(__name__)
        cfg = config.get("vesc", {})

        # --- Omrekening -------------------------------------------------
        # eRPM = wiel-RPM x poolparen x overbrenging. De Quinder heeft 10
        # poolparen en een 5:1 kast: 50 eRPM per wielomwenteling per minuut.
        self.pole_pairs = cfg.get("pole_pairs", 10)
        self.gear_ratio = cfg.get("gear_ratio", 5.0)
        self.wheel_circumference_m = cfg.get("wheel_circumference_m", 1.277)
        self.erpm_per_wheel_rpm = self.pole_pairs * self.gear_ratio
        self.erpm_per_mps = self.erpm_per_wheel_rpm * 60.0 / self.wheel_circumference_m
        # Tacho: 6 tellen per elektrische omwenteling = 300 per wielomwenteling
        self.counts_per_rev = 6 * self.erpm_per_wheel_rpm

        # --- Werkgebied -------------------------------------------------
        # Onder min_erpm draait een wiel niet (Speed PID min ERPM in de VESC):
        # een wiel staat stil of draait minstens zo snel, daartussen bestaat niet.
        self.min_erpm = float(cfg.get("min_erpm", 900))
        self.max_erpm = float(cfg.get("max_erpm", 3000))
        self.max_erpm_reverse = float(cfg.get("max_erpm_reverse", self.max_erpm))

        self.rate_hz = float(cfg.get("send_rate_hz", 50))
        self.link_timeout_s = cfg.get("link_timeout_s", 0.5)
        self.brake_current_a = cfg.get("brake_current_a", 3.0)

        # --- Beveiliging ------------------------------------------------
        safety = cfg.get("safety", {})
        self.stall_current_a = safety.get("stall_current_a", 10.0)
        self.stall_speed_fraction = safety.get("stall_speed_fraction", 0.5)
        self.stall_time_s = safety.get("stall_time_s", 3.0)
        self.thermal_k = safety.get("thermal_k", 0.00123)
        self.thermal_tau_s = safety.get("thermal_tau_s", 600.0)
        self.ambient_c = safety.get("ambient_c", 25.0)
        self.motor_warn_c = safety.get("motor_warn_c", 90.0)
        self.motor_trip_c = safety.get("motor_trip_c", 105.0)

        # --- Accu (alleen voor dashboard en ritlog) ---------------------
        battery = config.get("battery", {})
        self.battery_cells = battery.get("cells", 14)
        self.battery_capacity_ah = battery.get("capacity_ah", 5.0)
        self.battery_resistance_ohm = battery.get("internal_resistance_ohm", 0.2)

        self.bus = VescBus(
            interface=cfg.get("can_interface", "socketcan"),
            channel=cfg.get("can_channel", "can1"),
            bitrate=cfg.get("can_bitrate", 500000),
            host_id=cfg.get("host_can_id", 254),
        )
        self.left = _Wheel("left", self.bus.add_node(cfg.get("left_id", 1), "links"))
        self.right = _Wheel("right", self.bus.add_node(cfg.get("right_id", 2), "rechts"))
        self._wheels = (self.left, self.right)

        self._latched = None      # stall / oververhitting: blijft tot reset_faults()
        self._next_fault_poll = 0.0

        print(
            f"[VESC] Links ID {self.left.node.id}, rechts ID {self.right.node.id}. "
            f"Werkgebied {self.min_erpm:.0f}-{self.max_erpm:.0f} eRPM = "
            f"{self.erpm_to_kmh(self.min_erpm):.2f}-{self.erpm_to_kmh(self.max_erpm):.2f} km/h, "
            f"achteruit tot {self.erpm_to_kmh(self.max_erpm_reverse):.2f} km/h."
        )

    def erpm_to_kmh(self, erpm):
        return erpm / self.erpm_per_mps * 3.6

    # ------------------------------------------------------------------
    # Aansturen
    # ------------------------------------------------------------------
    def command(self, erpm_left, erpm_right, dt):
        """
        Stuur beide wielen aan. Wordt op send_rate_hz aangeroepen, ook bij
        stilstand: dat onafgebroken zenden houdt de VESC-timeout tevreden.
        Is de aandrijving geblokkeerd (zie fault), dan krijgen beide wielen 0 -
        nooit één wiel alleen, want dan draait de robot om het stilstaande wiel.
        """
        now = time.monotonic()
        self._update_protection(dt, now)
        blocked = self.fault is not None

        for wheel, erpm in ((self.left, erpm_left), (self.right, erpm_right)):
            wheel.erpm_cmd = 0 if blocked else self._limit(erpm)
            wheel.node.set_rpm(wheel.erpm_cmd)

        if now >= self._next_fault_poll:
            self._next_fault_poll = now + self.FAULT_POLL_S
            for wheel in self._wheels:
                wheel.node.request_fault_code()

    def _limit(self, erpm):
        """Laatste grens per wiel: 0, of tussen min_erpm en de maximale eRPM."""
        if abs(erpm) < 1.0:
            return 0
        limit = self.max_erpm if erpm > 0 else self.max_erpm_reverse
        return int(round(math.copysign(min(max(abs(erpm), self.min_erpm), limit), erpm)))

    def stop(self):
        """Beide wielen direct op 0, zonder op de volgende tik te wachten."""
        for wheel in self._wheels:
            wheel.erpm_cmd = 0
            wheel.node.set_rpm(0)

    def close(self):
        """
        Afsluiten zoals het testscript: kort remmen en de bus dicht. Daarna
        vallen de frames weg en zet de VESC-timeout de motoren vrij.
        """
        for _ in range(3):
            for wheel in self._wheels:
                wheel.node.set_brake_current(self.brake_current_a)
            time.sleep(0.02)
        self.bus.close()

    # ------------------------------------------------------------------
    # Beveiliging
    # ------------------------------------------------------------------
    def _online(self, node, now):
        return node.last_rx is not None and now - node.last_rx <= self.link_timeout_s

    def _fault_code(self, node, now):
        if node.fault_time is None or now - node.fault_time > self.FAULT_STALE_S:
            return None
        return node.fault_code

    def _update_protection(self, dt, now):
        for wheel in self._wheels:
            node = wheel.node
            online = self._online(node, now)
            current = abs(node.motor_current) if online else 0.0

            # Laag 3: thermisch model. Warmte schaalt met I^2, afkoelen gaat met
            # tijdconstante tau. Berekende startwaarden, nog niet geijkt.
            wheel.heat += (current * current * self.thermal_k - wheel.heat / self.thermal_tau_s) * dt
            temp = self.ambient_c + wheel.heat
            if temp >= self.motor_trip_c:
                self._latch(f"motor {node.name} te heet volgens het model ({temp:.0f} °C)")

            # Laag 2: stall. Toerental gevraagd, het wiel komt nauwelijks rond en
            # de stroom staat hoog. De VESC blijft tot zijn stroomgrens duwen en
            # kookt de wikkeling; na stall_time_s zetten we alles stil.
            cmd = abs(wheel.erpm_cmd)
            stalled = (online and cmd >= self.min_erpm
                       and abs(node.erpm) < self.stall_speed_fraction * cmd
                       and current >= self.stall_current_a)
            if not stalled:
                wheel.stall_since = None
            elif wheel.stall_since is None:
                wheel.stall_since = now
            elif now - wheel.stall_since >= self.stall_time_s:
                self._latch(
                    f"wiel {node.name} loopt vast ({current:.1f} A bij {node.erpm} "
                    f"van de gevraagde {cmd} eRPM)"
                )

    def _latch(self, reason):
        if self._latched is None:
            self._latched = reason
            self.logger.error(f"[VESC] Aandrijving gestopt: {reason}. Vrijgeven via /api/motors/reset.")

    def reset_faults(self):
        """Vrijgeven na een stall of oververhitting. Is het model nog te heet, dan slaat hij meteen weer aan."""
        self._latched = None
        for wheel in self._wheels:
            wheel.stall_since = None

    @property
    def fault(self):
        """Waarom er niet gereden mag worden, of None als alles in orde is."""
        if self._latched:
            return self._latched
        if not self.bus.online:
            return f"CAN-bus niet beschikbaar: {self.bus.error}"
        now = time.monotonic()
        for wheel in self._wheels:
            node = wheel.node
            if not self._online(node, now):
                return f"VESC {node.name} (ID {node.id}) geeft geen data"
            code = self._fault_code(node, now)
            if code:
                return f"VESC {node.name} meldt {fault_name(code)}"
        return None

    # ------------------------------------------------------------------
    # Uitlezen
    # ------------------------------------------------------------------
    def battery_voltage(self):
        """Accuspanning; beide VESC's hangen aan hetzelfde pak."""
        now = time.monotonic()
        values = [w.node.v_in for w in self._wheels if w.node.v_in is not None and self._online(w.node, now)]
        return round(sum(values) / len(values), 1) if values else None

    def battery_status(self):
        """
        De accu, opgebouwd uit beide VESC's: spanning, stroom, vermogen, een
        geschatte lading en het verbruik. Het verbruik komt uit de tellers van
        de VESC's; die beginnen op nul zodra de VESC's spanning krijgen, in de
        praktijk dus bij het aansluiten van het pak.
        """
        now = time.monotonic()
        nodes = [w.node for w in self._wheels]
        volt = self.battery_voltage()
        amps = sum(n.input_current for n in nodes if self._online(n, now))
        used_ah = sum(n.amp_hours for n in nodes)
        regen_ah = sum(n.amp_hours_charged for n in nodes)
        used_wh = sum(n.watt_hours for n in nodes)
        regen_wh = sum(n.watt_hours_charged for n in nodes)

        soc = None
        if volt is not None and self.battery_cells:
            # Onder stroom zakt de spanning in; reken terug naar de rustspanning,
            # anders zakt de balk bij elke keer optrekken en veert hij terug.
            rest = volt + amps * self.battery_resistance_ohm
            soc = round(soc_from_cell_voltage(rest / self.battery_cells))

        net_ah = used_ah - regen_ah
        return {
            "voltage_v": volt,
            "current_a": round(amps, 1),
            "power_w": None if volt is None else round(volt * amps),
            "soc_pct": soc,
            "used_ah": round(used_ah, 3),
            "used_wh": round(used_wh, 1),
            "regen_ah": round(regen_ah, 3),
            "regen_wh": round(regen_wh, 1),
            "net_ah": round(net_ah, 3),
            "net_wh": round(used_wh - regen_wh, 1),
            "used_pct": round(100.0 * net_ah / self.battery_capacity_ah, 1) if self.battery_capacity_ah else None,
            "capacity_ah": self.battery_capacity_ah,
            "capacity_wh": round(self.battery_capacity_ah * self.battery_cells * 3.6),  # 3,6 V nominaal per cel
            "cells": self.battery_cells,
        }

    def _distance_m(self, wheel):
        return round(wheel.node.odo_counts / self.counts_per_rev * self.wheel_circumference_m, 2)

    def _wheel_status(self, wheel, now):
        node = wheel.node
        age = None if node.last_rx is None else now - node.last_rx
        code = self._fault_code(node, now)
        return {
            "name": node.name,
            "can_id": node.id,
            "online": self._online(node, now),
            "age_ms": None if age is None else round(age * 1000),
            "rates_hz": node.rates(now),
            # Snelheid (STATUS, 50 Hz)
            "erpm_cmd": wheel.erpm_cmd,
            "erpm": node.erpm,
            "wheel_rpm": round(node.erpm / self.erpm_per_wheel_rpm, 1),
            "speed_cmd_kmh": round(self.erpm_to_kmh(wheel.erpm_cmd), 2),
            "speed_kmh": round(self.erpm_to_kmh(node.erpm), 2),
            "duty": round(node.duty, 3),
            # Stroom: motorstroom (warmte in de wikkeling) en accustroom (zekering)
            "motor_current_a": node.motor_current,
            "input_current_a": node.input_current,
            "v_in": node.v_in,
            # Temperatuur
            "temp_fet_c": node.temp_fet,
            "temp_motor_c": node.temp_motor,
            "motor_temp_model_c": round(self.ambient_c + wheel.heat, 1),
            # Tellers sinds het opstarten van de VESC
            "amp_hours": node.amp_hours,
            "amp_hours_charged": node.amp_hours_charged,
            "watt_hours": node.watt_hours,
            "watt_hours_charged": node.watt_hours_charged,
            "tacho": node.tacho,
            "distance_m": self._distance_m(wheel),
            "pid_pos": node.pid_pos,
            "adc_v": node.adc,
            "ppm": node.ppm,
            # Toestand
            "fault_code": code,
            "fault": fault_name(code),
            "stall_s": None if wheel.stall_since is None else round(now - wheel.stall_since, 1),
            "hw_name": node.hw_name,
            "boots": node.boots,
        }

    def status(self):
        """Alles wat de VESC's binnen laten komen, per wiel, plus de accu."""
        now = time.monotonic()
        warnings = []
        for wheel in self._wheels:
            temp = self.ambient_c + wheel.heat
            if temp >= self.motor_warn_c:
                warnings.append(f"motor {wheel.node.name} warm volgens het model ({temp:.0f} °C)")
            if wheel.stall_since is not None:
                warnings.append(f"wiel {wheel.node.name} komt niet rond op zijn toerental")

        battery = self.battery_status()
        return {
            "can": {
                "interface": self.bus.interface,
                "channel": self.bus.channel,
                "online": self.bus.online,
                "error": self.bus.error,
                "tx_errors": self.bus.tx_errors,
            },
            "limits": {
                "min_erpm": self.min_erpm,
                "max_erpm": self.max_erpm,
                "max_erpm_reverse": self.max_erpm_reverse,
                "min_kmh": round(self.erpm_to_kmh(self.min_erpm), 2),
                "max_kmh": round(self.erpm_to_kmh(self.max_erpm), 2),
                "max_reverse_kmh": round(self.erpm_to_kmh(self.max_erpm_reverse), 2),
                "erpm_per_kmh": round(self.erpm_per_mps / 3.6, 1),
            },
            "fault": self.fault,
            # True = blijft staan tot POST /api/motors/reset (stall, oververhitting)
            "fault_latched": self._latched is not None,
            "warnings": warnings,
            "accu_v": battery["voltage_v"],
            "accu_a": battery["current_a"],
            "accu_w": battery["power_w"],
            "battery": battery,
            "wheels": {w.key: self._wheel_status(w, now) for w in self._wheels},
        }

    def log_snapshot(self):
        """Eén regel aandrijfdata voor de ritlog, met de namen uit LOG_COLUMNS."""
        l, r = self.left, self.right
        battery = self.battery_status()
        return {
            "ERPM_Doel_L": l.erpm_cmd,
            "ERPM_Doel_R": r.erpm_cmd,
            "ERPM_L": l.node.erpm,
            "ERPM_R": r.node.erpm,
            "Wiel_kmh_L": round(self.erpm_to_kmh(l.node.erpm), 2),
            "Wiel_kmh_R": round(self.erpm_to_kmh(r.node.erpm), 2),
            "Duty_L": round(l.node.duty, 3),
            "Duty_R": round(r.node.duty, 3),
            "Motorstroom_L_A": l.node.motor_current,
            "Motorstroom_R_A": r.node.motor_current,
            "Accustroom_L_A": l.node.input_current,
            "Accustroom_R_A": r.node.input_current,
            "Temp_FET_L_C": l.node.temp_fet,
            "Temp_FET_R_C": r.node.temp_fet,
            "Motortemp_model_L_C": round(self.ambient_c + l.heat, 1),
            "Motortemp_model_R_C": round(self.ambient_c + r.heat, 1),
            "Afstand_L_m": self._distance_m(l),
            "Afstand_R_m": self._distance_m(r),
            "Accu_V": battery["voltage_v"],
            "Accu_A": battery["current_a"],
            "Accu_W": battery["power_w"],
            "Accu_pct": battery["soc_pct"],
            "Verbruikt_Ah": battery["used_ah"],
            "Verbruikt_Wh": battery["used_wh"],
            "Teruggeleverd_Ah": battery["regen_ah"],
            "Teruggeleverd_Wh": battery["regen_wh"],
            "Aandrijving": self.fault or "",
        }
