import json
import os
import logging


class ThrottleMap:
    """
    Vertaalt wielsnelheid (m/s) naar een DAC-waarde voor de MCP4728 en terug.

    De tabel komt uit 'setup/information/throttle_dac_speed_table.json' en is
    op de echte robot ingemeten. We interpoleren lineair TUSSEN de meetpunten
    in plaats van blind de formule te gebruiken: zodra je de tabel opnieuw
    inmeet (bv. na een andere bandenmaat of zwaardere accu) rijdt de robot
    meteen weer op de juiste snelheid, zonder code aan te passen.

    Belangrijk detail van deze hardware: de motoren draaien ALLEEN VOORUIT en
    er zit een dode zone onderin. Onder 'dac_min_start' (1200 = 0.24 m/s) komt
    het wiel niet in beweging; de enige andere geldige stand is 'dac_stop'
    (700 = motor uit). De VehicleController gebruikt min_speed_mps om die dode
    zone netjes te omzeilen.
    """

    DEFAULT_TABLE = os.path.join("setup", "information", "throttle_dac_speed_table.json")

    def __init__(self, config=None):
        self.logger = logging.getLogger(__name__)
        cfg = (config or {}).get("motor_control", {})

        self.dac_stop = int(cfg.get("dac_stop", 700))
        self.dac_min_start = int(cfg.get("dac_min_start", 1200))
        self.dac_max = int(cfg.get("dac_max", 3100))

        table_path = cfg.get("speed_table_path", self.DEFAULT_TABLE)
        # Punten als (dac, snelheid in m/s), oplopend op dac.
        self._points = self._load_table(table_path)

        self.min_speed_mps = self.dac_to_speed(self.dac_min_start)
        self.max_speed_mps = self.dac_to_speed(self.dac_max)
        self.max_speed_kmh = self.max_speed_mps * 3.6

        self.logger.info(
            f"ThrottleMap geladen ({len(self._points)} punten): "
            f"DAC {self.dac_min_start}-{self.dac_max} = "
            f"{self.min_speed_mps:.2f}-{self.max_speed_mps:.2f} m/s."
        )

    # ------------------------------------------------------------------ #
    #  Inladen
    # ------------------------------------------------------------------ #
    def _load_table(self, path):
        try:
            with open(path, "r") as f:
                data = json.load(f)

            punten = []
            for rij in data.get("dac_speed_mapping", []):
                dac = rij.get("dac_value")
                mps = rij.get("expected_speed_mps")
                if dac is None or mps is None:
                    continue
                punten.append((float(dac), float(mps)))

            punten.sort(key=lambda p: p[0])
            if len(punten) >= 2:
                return punten

            self.logger.warning(f"Snelheidstabel {path} bevat te weinig punten.")
        except Exception as e:
            self.logger.warning(f"Kan snelheidstabel {path} niet laden ({e}).")

        # Terugval op de formule uit de tabel: v = 0.001 * DAC - 0.96
        self.logger.warning("Terugval op de lineaire formule v = 0.001 * DAC - 0.96.")
        return [
            (float(self.dac_min_start), 0.001 * self.dac_min_start - 0.96),
            (float(self.dac_max), 0.001 * self.dac_max - 0.96),
        ]

    # ------------------------------------------------------------------ #
    #  Omrekenen
    # ------------------------------------------------------------------ #
    def dac_to_speed(self, dac):
        """DAC-waarde -> snelheid in m/s (geëxtrapoleerd buiten de tabel)."""
        return self._interpolate(float(dac), index_in=0, index_out=1)

    def speed_to_dac(self, speed_mps):
        """
        Snelheid in m/s -> DAC-waarde binnen [dac_min_start, dac_max].

        Een snelheid van 0 (of iets in de dode zone) hoort hier NIET thuis:
        die wordt door de VehicleController al afgevangen en naar dac_stop
        gestuurd. Alles wat hier binnenkomt wordt dus als 'rijden' behandeld.
        """
        dac = self._interpolate(float(speed_mps), index_in=1, index_out=0)
        return int(round(max(self.dac_min_start, min(self.dac_max, dac))))

    def clamp_speed(self, speed_mps):
        """Begrens een rijsnelheid op wat de motoren fysiek kunnen leveren."""
        return max(self.min_speed_mps, min(self.max_speed_mps, speed_mps))

    def _interpolate(self, waarde, index_in, index_out):
        """Stuksgewijs lineair interpoleren, met lineaire extrapolatie aan de randen."""
        punten = self._points

        if waarde <= punten[0][index_in]:
            p0, p1 = punten[0], punten[1]
        elif waarde >= punten[-1][index_in]:
            p0, p1 = punten[-2], punten[-1]
        else:
            p0, p1 = punten[0], punten[1]
            for i in range(len(punten) - 1):
                if punten[i][index_in] <= waarde <= punten[i + 1][index_in]:
                    p0, p1 = punten[i], punten[i + 1]
                    break

        spanwijdte = p1[index_in] - p0[index_in]
        if abs(spanwijdte) < 1e-9:
            return p0[index_out]

        fractie = (waarde - p0[index_in]) / spanwijdte
        return p0[index_out] + fractie * (p1[index_out] - p0[index_out])
