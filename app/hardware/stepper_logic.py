import serial
import time
import logging
import threading


class StepperSteering:
    """
    Klasse voor de aansturing van de TWEE gestuurde voorwielen via een Arduino.

    Protocol : setup/information/steppermotor_information.json
    Firmware : Arduino/arduino_controlling_dual_steppercontroller.cpp

    Elk commando dat we sturen krijgt precies een antwoordregel terug. Die lezen
    we altijd uit, anders loopt de seriële buffer vol met oude bevestigingen en
    krijgt een uitleesopdracht het antwoord van een vorig commando te pakken.
    """

    # Regels waarmee de firmware een transactie afsluit
    _REPLY_PREFIXES = ("OK:", "ERR:", "POS:", "STA:", "ID:")

    def __init__(self, config):
        self.logger = logging.getLogger(__name__)

        # Lees poort en baudrate uit de config
        hardware_config = config.get("hardware", {})
        self.port = hardware_config.get("arduino_stepper_port", "/dev/ttyACM3")
        self.baudrate = hardware_config.get("arduino_stepper_baudrate", 115200)

        steering_config = config.get("steering", {})

        # Lees limieten uit de config
        self.max_angle = steering_config.get("max_angle_degrees", 45.0)

        # --- SOFTWARE INVERT (per wiel) ---
        # De twee stuurmotoren zitten gespiegeld aan weerszijden van de machine.
        # Vrijwel altijd moet er dus per wiel apart bepaald worden of de
        # draairichting omgedraaid moet worden. invert_direction blijft als
        # terugvaloptie bestaan voor de oude configs met een enkel zwenkwiel.
        legacy_invert = steering_config.get("invert_direction", False)
        self.invert_left = steering_config.get("invert_left", legacy_invert)
        self.invert_right = steering_config.get("invert_right", legacy_invert)

        if "invert_left" not in steering_config and "invert_right" not in steering_config:
            self.logger.warning(
                "Config gebruikt nog het oude 'invert_direction'; beide stuurmotoren "
                f"draaien nu dezelfde kant op (invert={legacy_invert}). De motoren zitten "
                "gespiegeld, dus zet 'invert_left' en 'invert_right' apart in config.json."
            )

        # --- SNELHEID EN ACCELERATIE (optioneel, wordt naar de firmware gestuurd) ---
        self.min_step_delay_us = steering_config.get("min_step_delay_us")
        self.start_step_delay_us = steering_config.get("start_step_delay_us")
        self.ramp_steps = steering_config.get("ramp_steps")

        # --- ONDERDRUKKEN VAN OVERBODIG SERIEEL VERKEER ---
        # De navigatielus roept drive() tientallen keren per seconde aan. Elk
        # commando kost een USB-round-trip (schrijven + antwoord lezen), en die
        # latentie is de echte kostenpost - niet de baudrate, want Serial is op
        # de R4 Minima native USB CDC. We sturen daarom alleen bij een echte
        # verandering, met een periodieke herhaling als levensteken.
        self.min_change_degrees = steering_config.get("min_change_degrees", 0.1)
        self.resend_interval_sec = steering_config.get("resend_interval_sec", 1.0)

        self._last_sent = None
        self._last_send_time = 0.0

        self.serial_conn = None
        self._lock = threading.Lock()

        try:
            # Korte timeout: _read_reply doet zelf het wachten tot zijn deadline.
            self.serial_conn = serial.Serial(
                self.port, self.baudrate, timeout=0.1, write_timeout=1.0
            )
            time.sleep(2)  # Geef de Arduino de tijd om te herstarten
            self.serial_conn.reset_input_buffer()  # gooi de READY-regel weg
            self.logger.info(f"Verbonden met Arduino Stuur-Controller op {self.port}")
            self._configure_firmware()
        except serial.SerialException as e:
            self.logger.error(f"Kan geen verbinding maken met stuur-Arduino op {self.port}: {e}")

    # ------------------------------------------------------------------
    # Seriële laag
    # ------------------------------------------------------------------
    def _configure_firmware(self):
        """Zet de firmware bij het opstarten gelijk met de config."""
        firmware_id = self._transaction("I:?")
        if firmware_id:
            self.logger.info(f"Stuur-firmware: {firmware_id}")
        else:
            self.logger.warning(
                "Stuur-Arduino antwoordt niet op I:? - draait er wel de dual-stepper firmware?"
            )

        self._transaction(f"M:{self.max_angle:.2f}")

        if self.min_step_delay_us:
            parts = [str(int(self.min_step_delay_us))]
            if self.start_step_delay_us:
                parts.append(str(int(self.start_step_delay_us)))
                if self.ramp_steps is not None:
                    parts.append(str(int(self.ramp_steps)))
            self._transaction("V:" + ",".join(parts))

    def _read_reply(self, deadline):
        """Lees regels tot er een geldig antwoord komt of de deadline verstrijkt."""
        while time.time() < deadline:
            try:
                raw = self.serial_conn.readline()
            except Exception as e:
                self.logger.error(f"Fout bij lezen van stuur-Arduino: {e}")
                return None

            if not raw:
                continue  # readline-timeout, opnieuw proberen tot de deadline

            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith(self._REPLY_PREFIXES):
                return line

            # Losse regels zoals READY horen bij een herstart van de Arduino.
            self.logger.debug(f"Ongevraagde regel van stuur-Arduino: {line}")
        return None

    def _transaction(self, command, timeout=0.3):
        """Verstuur een commando en lees het bijbehorende antwoord."""
        with self._lock:
            if not (self.serial_conn and self.serial_conn.is_open):
                self.logger.warning(
                    f"Kan commando '{command}' niet sturen: Seriële verbinding is dicht."
                )
                return None
            try:
                # Restjes van een eerder afgekapt antwoord opruimen, zodat we
                # gegarandeerd het antwoord op dit commando lezen.
                self.serial_conn.reset_input_buffer()
                self.serial_conn.write(f"{command}\n".encode("utf-8"))
            except Exception as e:
                self.logger.error(f"Fout bij verzenden commando '{command}': {e}")
                return None

            reply = self._read_reply(time.time() + timeout)

        if reply is None:
            self.logger.warning(f"Geen antwoord van de stuur-Arduino op '{command}'")
        elif reply.startswith("ERR:"):
            self.logger.error(f"Stuur-Arduino weigerde '{command}': {reply}")
        return reply

    # ------------------------------------------------------------------
    # Omrekenen tussen voertuigframe en motorframe
    # ------------------------------------------------------------------
    def _limit(self, angle):
        """Beveiliging: beperk de maximale uitslag van een wiel."""
        if angle > self.max_angle:
            self.logger.warning(f"Gevraagde hoek te groot. Beperkt tot {self.max_angle} graden.")
            return self.max_angle
        if angle < -self.max_angle:
            self.logger.warning(f"Gevraagde hoek te klein. Beperkt tot -{self.max_angle} graden.")
            return -self.max_angle
        return angle

    def _to_motor(self, left, right):
        """Voertuighoeken omzetten naar wat de motoren moeten draaien."""
        return (-left if self.invert_left else left,
                -right if self.invert_right else right)

    def _from_motor(self, left, right):
        """Motorhoeken terugrekenen naar het voertuigframe (voor de UI)."""
        return self._to_motor(left, right)  # omkeren is zijn eigen inverse

    # ------------------------------------------------------------------
    # Stuurcommando's
    # ------------------------------------------------------------------
    def _should_send(self, left, right):
        """Alleen sturen bij een echte verandering, of als levensteken."""
        if self._last_sent is None:
            return True
        if time.time() - self._last_send_time >= self.resend_interval_sec:
            return True
        return (abs(left - self._last_sent[0]) >= self.min_change_degrees or
                abs(right - self._last_sent[1]) >= self.min_change_degrees)

    def set_angles(self, left_angle, right_angle, force=False):
        """
        Stuur beide voorwielen naar hun eigen hoek (Ackermann).
        De VehicleController rekent de meetkunde uit; hier gebeurt alleen de
        begrenzing, de richtingsomkering per wiel en het seriële verkeer.
        """
        left = self._limit(left_angle)
        right = self._limit(right_angle)

        if not force and not self._should_send(left, right):
            return

        tx_left, tx_right = self._to_motor(left, right)
        reply = self._transaction(f"A:{tx_left:.2f},{tx_right:.2f}")

        if reply is None:
            # Niet aangekomen: onthoud niets, dan wordt het volgende commando
            # sowieso verstuurd in plaats van weggefilterd.
            self._last_sent = None
            return

        self._last_sent = (left, right)
        self._last_send_time = time.time()

        if reply.endswith(";CLAMPED"):
            self.logger.warning(
                f"Firmware begrensde de stuurhoek (L:{left:.1f}° R:{right:.1f}°) "
                f"op zijn eigen limiet."
            )
        self.logger.debug(f"Stuurhoeken ingesteld op L:{left:.2f}° R:{right:.2f}°")

    def set_angle(self, angle):
        """
        Zet beide voorwielen op dezelfde hoek.
        Bedoeld voor handmatig sturen en kalibreren; tijdens het rijden hoort
        set_angles() gebruikt te worden, want gelijke hoeken laten de twee
        wielen via de grond tegen elkaar vechten.
        """
        self.set_angles(angle, angle)

    def jog(self, left_delta, right_delta=None):
        """Relatieve verplaatsing in graden, voor het kalibreren van het nulpunt."""
        if right_delta is None:
            right_delta = left_delta
        tx_left, tx_right = self._to_motor(left_delta, right_delta)
        self._transaction(f"J:{tx_left:.2f},{tx_right:.2f}")
        self._last_sent = None  # de doelhoek is nu buiten onze administratie om verzet

    # ------------------------------------------------------------------
    # Vast / vrij zetten en kalibreren
    # ------------------------------------------------------------------
    @staticmethod
    def _suffix(wheel):
        if wheel is None:
            return ""
        wheel = str(wheel).lower()
        if wheel in ("left", "links", "l"):
            return "L"
        if wheel in ("right", "rechts", "r"):
            return "R"
        raise ValueError(f"Onbekend wiel: {wheel!r} (gebruik 'left', 'right' of None)")

    def enable(self, wheel=None):
        """
        Zet de motor(en) vast (houdt positie).
        Let op: de firmware zet de doelhoek daarbij gelijk aan de huidige stand,
        zodat een met de hand verdraaid wiel niet terugschiet naar een oud doel.
        """
        self._transaction(f"E{self._suffix(wheel)}:1")
        self._last_sent = None  # firmware heeft de doelhoek gereset
        self.logger.info(f"Stuurmotor(en) VASTGEZET (Enabled){self._label(wheel)}")

    def disable(self, wheel=None):
        """Zet de motor(en) in de vrijloop (kan met de hand gedraaid worden)."""
        self._transaction(f"E{self._suffix(wheel)}:0")
        self._last_sent = None
        self.logger.info(f"Stuurmotor(en) VRIJGEZET (Disabled){self._label(wheel)}")

    def set_zero(self, wheel=None):
        """
        Stel de huidige stand in als het nieuwe nulpunt (rechtuit).
        Elk voorwiel heeft zijn eigen mechanische nulpunt; bij een verschil van
        een halve graad staat er permanent spanning op de vooras. Kalibreer ze
        daarom apart met set_zero('left') en set_zero('right').
        """
        self._transaction(f"Z{self._suffix(wheel)}:0")
        self._last_sent = None
        self.logger.info(f"Nulpunt stuurmotor(en) opnieuw gekalibreerd{self._label(wheel)}")

    @staticmethod
    def _label(wheel):
        return "" if wheel is None else f" [{wheel}]"

    # ------------------------------------------------------------------
    # Uitlezen
    # ------------------------------------------------------------------
    def get_positions(self):
        """
        Vraag de huidige hoek van beide wielen op.
        Geeft (links, rechts) in graden terug in het voertuigframe, of None.
        """
        reply = self._transaction("P:?")
        if not reply or not reply.startswith("POS:"):
            return None
        try:
            left, right = (float(v) for v in reply[4:].split(","))
        except ValueError:
            self.logger.error(f"Onleesbaar positie-antwoord: {reply}")
            return None
        return self._from_motor(left, right)

    def get_position(self):
        """
        Gemiddelde stuurhoek van beide voorwielen, oftewel de hoek van het
        virtuele midden van de vooras. Dat is de waarde die de frontend toont.
        """
        positions = self.get_positions()
        if positions is None:
            return None
        return (positions[0] + positions[1]) / 2.0

    def get_status(self):
        """Volledige status van de stuurcontroller als dict, of None."""
        reply = self._transaction("S:?")
        if not reply or not reply.startswith("STA:"):
            return None

        fields = {}
        for chunk in reply[4:].split(";"):
            key, sep, value = chunk.partition("=")
            if sep:
                fields[key] = value

        def as_pair(key, cast=float):
            try:
                left, right = (cast(v) for v in fields[key].split(","))
            except (KeyError, ValueError):
                return None
            return left, right

        def as_single(key, cast=float):
            try:
                return cast(fields[key])
            except (KeyError, ValueError):
                return None

        positions = as_pair("POS")
        targets = as_pair("TGT")
        enabled = as_pair("EN", int)

        return {
            "position": self._as_wheels(self._from_motor(*positions) if positions else None),
            "target": self._as_wheels(self._from_motor(*targets) if targets else None),
            "enabled": {"left": bool(enabled[0]), "right": bool(enabled[1])} if enabled else None,
            "moving": fields.get("MOV") == "1",
            "max_angle_degrees": as_single("LIM"),
            "min_step_delay_us": as_single("VMIN", int),
            "start_step_delay_us": as_single("VSTART", int),
            "ramp_steps": as_single("RAMP", int),
        }

    @staticmethod
    def _as_wheels(pair):
        return None if pair is None else {"left": pair[0], "right": pair[1]}

    # ------------------------------------------------------------------
    # Instellingen live aanpassen
    # ------------------------------------------------------------------
    def set_speed(self, min_step_delay_us, start_step_delay_us=None, ramp_steps=None):
        """Snelheid en acceleratieramp aanpassen. Lagere delay = sneller."""
        parts = [str(int(min_step_delay_us))]
        if start_step_delay_us is not None:
            parts.append(str(int(start_step_delay_us)))
            if ramp_steps is not None:
                parts.append(str(int(ramp_steps)))
        self._transaction("V:" + ",".join(parts))

    def set_max_angle(self, degrees):
        """Softwarelimiet op de stuuruitslag aanpassen, in Python en in de firmware."""
        self.max_angle = degrees
        self._transaction(f"M:{degrees:.2f}")
        self._last_sent = None

    def close(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.logger.info("Seriële verbinding met stuur-Arduino gesloten.")
