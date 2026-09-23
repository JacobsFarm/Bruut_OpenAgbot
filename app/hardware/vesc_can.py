"""
VESC-protocol over CAN: frames bouwen en uitpakken, telemetrie per controller.

Extended frames, 29-bits ID = (commando << 8) | vesc_id, payload big-endian.
De VESC's sturen hun statusframes uit zichzelf (App Settings -> CAN Status
Message Mode), dus die hoeven niet gepold te worden. Alleen de foutcode zit in
geen enkel statusframe; die vragen we zelf een paar keer per seconde op.

Commando-ID's: bldc/datatypes.h. Bedrading en instellingen: VESC/README_can.md.
"""

import logging
import struct
import threading
import time

try:
    import can
except ImportError:  # zonder python-can draait de rest van de backend gewoon door
    can = None

# --- CAN_PACKET_ID uit bldc/datatypes.h -----------------------------------
CAN_PACKET_SET_CURRENT_BRAKE = 2
CAN_PACKET_SET_RPM = 3
CAN_PACKET_PROCESS_SHORT_BUFFER = 8
CAN_PACKET_STATUS = 9
CAN_PACKET_STATUS_2 = 14
CAN_PACKET_STATUS_3 = 15
CAN_PACKET_STATUS_4 = 16
CAN_PACKET_STATUS_5 = 27
CAN_PACKET_NOTIFY_BOOT = 57
CAN_PACKET_STATUS_6 = 58

STATUS_NAMES = {
    CAN_PACKET_STATUS: "status_1",
    CAN_PACKET_STATUS_2: "status_2",
    CAN_PACKET_STATUS_3: "status_3",
    CAN_PACKET_STATUS_4: "status_4",
    CAN_PACKET_STATUS_5: "status_5",
    CAN_PACKET_STATUS_6: "status_6",
}

# Een gewoon VESC-commando (COMM_PACKET_ID), over CAN verpakt in
# PROCESS_SHORT_BUFFER. We vragen alleen bit 15 op, de foutcode: het antwoord
# is dan precies 6 bytes en past in een enkel frame terug.
COMM_GET_VALUES_SELECTIVE = 50
FAULT_CODE_MASK = 1 << 15

# mc_fault_code uit bldc/datatypes.h
FAULT_NAMES = (
    "NONE", "OVER_VOLTAGE", "UNDER_VOLTAGE", "DRV", "ABS_OVER_CURRENT",
    "OVER_TEMP_FET", "OVER_TEMP_MOTOR", "GATE_DRIVER_OVER_VOLTAGE",
    "GATE_DRIVER_UNDER_VOLTAGE", "MCU_UNDER_VOLTAGE", "BOOTING_FROM_WATCHDOG_RESET",
    "ENCODER_SPI", "ENCODER_SINCOS_BELOW_MIN_AMPLITUDE",
    "ENCODER_SINCOS_ABOVE_MAX_AMPLITUDE", "FLASH_CORRUPTION",
    "HIGH_OFFSET_CURRENT_SENSOR_1", "HIGH_OFFSET_CURRENT_SENSOR_2",
    "HIGH_OFFSET_CURRENT_SENSOR_3", "UNBALANCED_CURRENTS", "BRK",
    "RESOLVER_LOT", "RESOLVER_DOS", "RESOLVER_LOS", "FLASH_CORRUPTION_APP_CFG",
    "FLASH_CORRUPTION_MC_CFG", "ENCODER_NO_MAGNET", "ENCODER_MAGNET_TOO_STRONG",
    "PHASE_FILTER",
)


def fault_name(code):
    if code is None:
        return None
    return FAULT_NAMES[code] if code < len(FAULT_NAMES) else f"FAULT_{code}"


class VescNode:
    """
    Eén VESC op de bus: de laatst ontvangen telemetrie plus de commando's
    ernaartoe. Wordt gevuld door de ontvangstthread van VescBus.
    """

    # Grootste tacho-sprong tussen twee STATUS_5-frames die we nog als echte
    # beweging tellen. Bij 4000 eRPM komen er ~400 tellen per seconde bij;
    # een grotere sprong is een herstart van de VESC (teller terug op nul).
    MAX_TACHO_STEP = 2000

    def __init__(self, bus, vesc_id, name):
        self.bus = bus
        self.id = vesc_id
        self.name = name

        # STATUS (1)
        self.erpm = 0
        self.motor_current = 0.0   # A; + = aandrijven, - = remmen
        self.duty = 0.0            # -1 .. 1
        # STATUS_2 en _3: tellers sinds het opstarten van de VESC
        self.amp_hours = 0.0
        self.amp_hours_charged = 0.0
        self.watt_hours = 0.0
        self.watt_hours_charged = 0.0
        # STATUS_4
        self.temp_fet = None       # °C, de echte sensor op het board
        self.temp_motor = None     # °C, zinloos zolang Motor Temp Sensor op Disabled staat
        self.input_current = 0.0   # A uit de accu; negatief bij terugleveren
        self.pid_pos = 0.0         # graden, alleen zinvol bij positieregeling
        # STATUS_5
        self.tacho = None          # ruwe teller, 6 per elektrische omwenteling
        self.v_in = None           # accuspanning, gefilterd door de VESC
        # STATUS_6, alleen als die in de VESC aan staat
        self.adc = None            # (ADC1, ADC2, ADC3) in volt
        self.ppm = None
        # Opgevraagd, zit in geen statusframe
        self.fault_code = None     # None = (nog) geen antwoord gehad
        self.fault_time = None
        # NOTIFY_BOOT
        self.hw_name = None
        self.boots = 0             # herstarts gezien sinds de backend draait

        self.odo_counts = 0        # tacho-stappen, opgeteld sinds de backend draait
        self.last_rx = None        # time.monotonic() van het laatste frame
        self._last_tacho = None
        self._last_seen = {}
        self._period = {}

    # ------------------------------------------------------------------
    # Ontvangen
    # ------------------------------------------------------------------
    def handle(self, cmd, data, now):
        """Verwerk een frame van deze VESC. False = geen frame dat wij kennen."""
        if cmd == CAN_PACKET_STATUS and len(data) >= 8:
            erpm, current, duty = struct.unpack_from(">ihh", data)
            self.erpm = erpm
            self.motor_current = current / 10.0
            self.duty = duty / 1000.0
        elif cmd == CAN_PACKET_STATUS_2 and len(data) >= 8:
            ah, ah_charged = struct.unpack_from(">ii", data)
            self.amp_hours = ah / 1e4
            self.amp_hours_charged = ah_charged / 1e4
        elif cmd == CAN_PACKET_STATUS_3 and len(data) >= 8:
            wh, wh_charged = struct.unpack_from(">ii", data)
            self.watt_hours = wh / 1e4
            self.watt_hours_charged = wh_charged / 1e4
        elif cmd == CAN_PACKET_STATUS_4 and len(data) >= 8:
            t_fet, t_motor, i_in, pid_pos = struct.unpack_from(">hhhh", data)
            self.temp_fet = t_fet / 10.0
            self.temp_motor = t_motor / 10.0
            self.input_current = i_in / 10.0
            self.pid_pos = pid_pos / 50.0
        elif cmd == CAN_PACKET_STATUS_5 and len(data) >= 6:
            tacho, v_in = struct.unpack_from(">ih", data)
            self._count_tacho(tacho)
            self.tacho = tacho
            self.v_in = v_in / 10.0
        elif cmd == CAN_PACKET_STATUS_6 and len(data) >= 8:
            adc1, adc2, adc3, ppm = struct.unpack_from(">hhhh", data)
            self.adc = (adc1 / 1000.0, adc2 / 1000.0, adc3 / 1000.0)
            self.ppm = ppm / 1000.0
        elif cmd == CAN_PACKET_NOTIFY_BOOT:
            self.hw_name = bytes(data).split(b"\0")[0].decode("ascii", "replace") or None
            self.boots += 1
            self._last_tacho = None
        else:
            return False

        self.last_rx = now
        last = self._last_seen.get(cmd)
        if last is not None:
            interval = now - last
            prev = self._period.get(cmd)
            self._period[cmd] = interval if prev is None else prev + 0.1 * (interval - prev)
        self._last_seen[cmd] = now
        return True

    def handle_reply(self, packet, now):
        """Antwoord op request_fault_code(): [50, masker (4 bytes), foutcode]."""
        if (len(packet) >= 6 and packet[0] == COMM_GET_VALUES_SELECTIVE
                and struct.unpack_from(">I", packet, 1)[0] == FAULT_CODE_MASK):
            self.fault_code = packet[5]
            self.fault_time = now

    def _count_tacho(self, tacho):
        if self._last_tacho is not None:
            step = tacho - self._last_tacho
            if abs(step) <= self.MAX_TACHO_STEP:
                self.odo_counts += step
        self._last_tacho = tacho

    def rates(self, now):
        """Gemeten frequentie per statusframe dat binnenkomt (Hz)."""
        out = {}
        for cmd, name in STATUS_NAMES.items():
            last, period = self._last_seen.get(cmd), self._period.get(cmd)
            if last is not None and period and now - last < 2.0:
                out[name] = round(1.0 / period, 1)
        return out

    # ------------------------------------------------------------------
    # Zenden
    # ------------------------------------------------------------------
    def set_rpm(self, erpm):
        return self.bus.send(self.id, CAN_PACKET_SET_RPM, struct.pack(">i", int(erpm)))

    def set_brake_current(self, amps):
        return self.bus.send(self.id, CAN_PACKET_SET_CURRENT_BRAKE,
                             struct.pack(">i", int(amps * 1000)))

    def request_fault_code(self):
        # [afzender-ID, 0 = uitvoeren en antwoorden, commando, masker]
        payload = struct.pack(">BBBI", self.bus.host_id, 0,
                              COMM_GET_VALUES_SELECTIVE, FAULT_CODE_MASK)
        return self.bus.send(self.id, CAN_PACKET_PROCESS_SHORT_BUFFER, payload)


class VescBus:
    """
    Eén CAN-bus voor alle VESC's, met een ontvangstthread die elk frame bij de
    juiste VescNode aflevert. Is de bus er niet - adapter los, can0 down,
    python-can niet geïnstalleerd - dan blijft de backend gewoon draaien en
    probeert hij het elke RETRY_S seconden opnieuw.
    """

    RETRY_S = 2.0

    def __init__(self, interface="socketcan", channel="can0", bitrate=500000, host_id=254):
        self.logger = logging.getLogger(__name__)
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.host_id = host_id     # ons eigen adres, voor antwoorden van de VESC's
        self.nodes = {}
        self.bus = None
        self.error = None
        self.tx_errors = 0
        self._tx_lock = threading.Lock()
        self._next_open = 0.0
        self._last_tx_warning = 0.0
        self._running = True

        self._open()
        self._thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._thread.start()

    def add_node(self, vesc_id, name):
        node = VescNode(self, vesc_id, name)
        self.nodes[vesc_id] = node
        return node

    @property
    def online(self):
        return self.bus is not None

    # ------------------------------------------------------------------
    # Openen en herstellen
    # ------------------------------------------------------------------
    def _open(self):
        self._next_open = time.monotonic() + self.RETRY_S
        if can is None:
            self._set_error("python-can is niet geïnstalleerd (pip install python-can)")
            return
        kwargs = {"interface": self.interface, "channel": self.channel}
        if self.interface != "socketcan":
            kwargs["bitrate"] = self.bitrate  # socketcan krijgt zijn bitrate van 'ip link'
        try:
            self.bus = can.Bus(**kwargs)
        except Exception as e:
            self._set_error(f"{self.interface} '{self.channel}' niet te openen: {e}")
            return
        self.error = None
        print(f"[VESC] CAN-bus geopend: {self.interface} {self.channel}")

    def _set_error(self, reason):
        if reason != self.error:  # één keer melden, niet bij elke nieuwe poging
            print(f"[VESC ERROR] {reason}")
        self.error = reason

    def _drop(self, reason):
        bus, self.bus = self.bus, None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass
        self._set_error(reason)
        self._next_open = time.monotonic() + self.RETRY_S

    # ------------------------------------------------------------------
    # Zenden en ontvangen
    # ------------------------------------------------------------------
    def send(self, vesc_id, cmd, payload):
        bus = self.bus
        if bus is None:
            return False
        msg = can.Message(arbitration_id=(cmd << 8) | vesc_id, data=payload, is_extended_id=True)
        try:
            with self._tx_lock:
                bus.send(msg)
            return True
        except Exception as e:
            # Meestal: niemand bevestigt het frame (VESC's uit) of can0 staat op
            # BUS-OFF. gs_usb kent geen restart-ms, dus dan helpt alleen can0
            # down/up. Melden, maar niet 100x per seconde.
            self.tx_errors += 1
            now = time.monotonic()
            if now - self._last_tx_warning > 5.0:
                self._last_tx_warning = now
                self.logger.warning(
                    f"[VESC] CAN-frame niet verstuurd ({self.tx_errors}x): {e}. Staat {self.channel} "
                    f"op BUS-OFF? Herstel: sudo ip link set {self.channel} down && "
                    f"sudo ip link set {self.channel} up type can bitrate {self.bitrate}"
                )
            return False

    def _rx_loop(self):
        while self._running:
            bus = self.bus
            if bus is None:
                if time.monotonic() >= self._next_open:
                    self._open()
                if self.bus is None:
                    time.sleep(0.2)
                continue
            try:
                msg = bus.recv(timeout=0.2)
            except Exception as e:
                if self._running:
                    self._drop(f"ontvangen op {self.channel} mislukt: {e}")
                continue
            if msg is None or msg.is_error_frame or not msg.is_extended_id:
                continue
            self._dispatch(msg.arbitration_id, bytes(msg.data))

    def _dispatch(self, arbitration_id, data):
        cmd, target = arbitration_id >> 8, arbitration_id & 0xFF
        now = time.monotonic()

        if cmd == CAN_PACKET_PROCESS_SHORT_BUFFER:
            # Antwoord op een opgevraagd commando: aan ons gericht, met de
            # afzender in byte 0 en de 'send'-vlag in byte 1.
            if target == self.host_id and len(data) >= 2:
                node = self.nodes.get(data[0])
                if node is not None:
                    node.handle_reply(data[2:], now)
            return

        node = self.nodes.get(target)
        if node is not None and node.handle(cmd, data, now) and cmd == CAN_PACKET_NOTIFY_BOOT:
            self.logger.warning(
                f"[VESC] {node.name} (ID {node.id}) is (her)opgestart: {node.hw_name}"
            )

    def close(self):
        self._running = False
        bus, self.bus = self.bus, None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass
        self._thread.join(timeout=1.0)
