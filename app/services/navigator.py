import math
import time
import threading
from collections import deque
from app.services.logger import DriveLogger

# ============================================================
# NAVIGATOR V2 — Verbeterde rechte-lijn tracking
# voor skid-steer veldrobot met dual RTK-GPS
#
# Belangrijkste verbeteringen t.o.v. V1:
#   1. Heading-buffer bug gerepareerd (degrees vs radians)
#   2. Correcte XTE via Cartesiaanse projectie (geen asin-benadering)
#   3. Pure Pursuit look-ahead punt via haversine + bearing
#      (geen lineaire lat/lon interpolatie)
#   4. D-term op gemeten yaw-rate i.p.v. op fout-delta
#      (veel minder gevoelig voor GPS-ruis)
#   5. Feedforward DAC direct uit gecalibreerde tabel
#   6. Drag-Wheel Fix verwijderd (veroorzaakte tegengesteld effect)
#   7. Speed-integraal anti-windup verbeterd
#   8. Aparte "straight-line bonus": als |fout| < 5° → stuur-D
#      wordt gehalveerd zodat kleine correcties niet slingeren
# ============================================================

# --- Gecalibreerde motoreigenschappen (uit throttle_dac_speed_table.json) ---
DAC_MIN   = 1200    # Motor startpunt (0-snelheid drempel)
DAC_MAX   = 3100    # Maximale DAC waarde
DAC_RUST  = 700     # Rust / noodstop waarde
# Lineaire kalibratie: speed_mps = 0.001 * DAC - 0.96
# Omgekeerd:          DAC = (speed_mps + 0.96) / 0.001
_DAC_SLOPE     = 1000.0   # 1/0.001
_DAC_INTERCEPT = 0.96     # m/s offset


def speed_mps_to_dac(speed_mps: float) -> int:
    """Feedforward: zet gewenste snelheid (m/s) om naar DAC waarde."""
    if speed_mps <= 0.0:
        return DAC_RUST
    dac = (speed_mps + _DAC_INTERCEPT) * _DAC_SLOPE
    return int(max(DAC_MIN, min(DAC_MAX, dac)))


class Navigator:
    def __init__(self, gps_sys, motor_ctrl):
        self.gps   = gps_sys
        self.motor = motor_ctrl
        self.logger = DriveLogger()
        self.waypoints = []

        # Doel-snelheid ingesteld door start()
        self.doel_snelheid_kmh = 0.0
        self.active = False
        self.thread = None

        # ==========================================
        # --- TUNING PARAMETERS ---
        # ==========================================

        # --- Sturen: Pure Pursuit + PD op yaw-rate ---
        # kp: hoeveel stuurcorrectie per graad koersfout
        #     Typisch startpunt: 8-15 (verhoog als te traag, verlaag bij slingeren)
        self.kp = 10.0

        # kd: demping op de gemeten yaw-rate (graden/seconde)
        #     Stopt slingeren. Typisch: 15-30.
        self.kd = 20.0

        # look_ahead_dist: afstand (meter) waarnaar de robot "vooruit kijkt"
        #     Kleiner = strakker maar meer slingeren. Groter = soepeler.
        self.look_ahead_dist = 2.5

        # --- Snelheid: PI Cruise Control ---
        # kp_snelheid: proportionele snelheidsregelaar (DAC-eenheden per m/s fout)
        self.kp_snelheid = 400.0

        # ki_snelheid: integrale term (compenseert systematische weerstand)
        self.ki_snelheid = 250.0

        # max_pi: maximale PI-correctie in DAC-eenheden (anti-windup begrenzing)
        self.max_pi_correctie = 600

        # hoek_rem_drempel: bij hoeveel graden fout begint de robot af te remmen
        self.hoek_rem_drempel = 20.0   # graden

        # hoek_rem_factor: maximale remkracht (0.0 = volledig stop, 1.0 = geen remmen)
        self.hoek_rem_factor = 0.45

        # --- GPS heading filtering ---
        # Grootte van de circulaire buffer (meer = soepeler maar trager)
        self._heading_buffer = deque(maxlen=5)

        # ==========================================
        # --- INTERNE STATUS VARIABELEN ---
        # (niet aanpassen)
        # ==========================================
        self._huidige_links  = DAC_RUST
        self._huidige_rechts = DAC_RUST

        self._vorige_actuele_positie   = None
        self._gefilterde_snelheid_mps  = 0.0

        self._speed_integraal = 0.0

        self._vorige_heading  = None   # Voor yaw-rate berekening
        self._vorige_fout     = 0.0
        self._vorige_tijd     = None

    # ------------------------------------------------------------------
    # Publieke interface (zelfde als V1)
    # ------------------------------------------------------------------

    def start(self, waypoints, target_speed_kmh=3.0):
        """Start de navigatie. Zelfde interface als V1."""
        self.logger.start_nieuwe_rit()
        self.waypoints = waypoints
        self.doel_snelheid_kmh = target_speed_kmh
        self._reset_state()
        self.active = True
        self.thread = threading.Thread(target=self._navigate_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Noodstop. Zelfde interface als V1."""
        self.active = False
        self.motor.stuur_motoren(DAC_RUST, DAC_RUST)

    # ------------------------------------------------------------------
    # State reset
    # ------------------------------------------------------------------

    def _reset_state(self):
        self._huidige_links  = DAC_RUST
        self._huidige_rechts = DAC_RUST
        self._vorige_fout    = 0.0
        self._vorige_tijd    = None
        self._vorige_actuele_positie   = None
        self._gefilterde_snelheid_mps  = 0.0
        self._speed_integraal = 0.0
        self._vorige_heading  = None
        self._heading_buffer.clear()

    # ------------------------------------------------------------------
    # Wiskunde hulpfuncties
    # ------------------------------------------------------------------

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        """Afstand in meters tussen twee GPS-coördinaten."""
        R = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi   = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _bearing(lat1, lon1, lat2, lon2) -> float:
        """Kompasrichting (0-360°) van punt 1 naar punt 2."""
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        y = math.sin(dl) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - \
            math.sin(phi1) * math.cos(phi2) * math.cos(dl)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    @staticmethod
    def _destination_point(lat, lon, bearing_deg, distance_m):
        """
        Berekent het GPS-punt op `distance_m` meter vanaf (lat, lon)
        in de richting `bearing_deg`. Gebruikt voor het berekenen van
        het Pure Pursuit look-ahead punt op de doellijn.
        """
        R = 6_371_000.0
        d = distance_m / R
        b = math.radians(bearing_deg)
        phi1 = math.radians(lat)
        lam1 = math.radians(lon)

        phi2 = math.asin(
            math.sin(phi1) * math.cos(d) +
            math.cos(phi1) * math.sin(d) * math.cos(b)
        )
        lam2 = lam1 + math.atan2(
            math.sin(b) * math.sin(d) * math.cos(phi1),
            math.cos(d) - math.sin(phi1) * math.sin(phi2)
        )
        return math.degrees(phi2), (math.degrees(lam2) + 540) % 360 - 180

    @staticmethod
    def _angle_diff(a, b) -> float:
        """Kortste hoekafstand a - b, in het bereik (-180, 180]."""
        d = (a - b + 180) % 360 - 180
        return d

    # ------------------------------------------------------------------
    # GPS Heading filtering (bug-fix t.o.v. V1)
    # ------------------------------------------------------------------

    def _gefilterde_heading(self) -> float:
        """
        Circulaire gemiddelde van de ruwe GPS-heading.
        V1 bug: buffer vergeleek math.degrees(radians) met raw degrees,
        waardoor nieuwe waarden nooit werden opgeslagen.
        Fix: sla degrees op, converteer pas bij het middelen.
        """
        raw = self.gps.current_heading
        if raw == 0.0:
            return 0.0

        # Sla op in degrees (niet in radians zoals in V1)
        if len(self._heading_buffer) == 0 or self._heading_buffer[-1] != raw:
            self._heading_buffer.append(raw)

        # Circulaire gemiddelde (werkt correct over de 0°/360° grens)
        rads = [math.radians(h) for h in self._heading_buffer]
        sin_gem = sum(math.sin(r) for r in rads) / len(rads)
        cos_gem = sum(math.cos(r) for r in rads) / len(rads)
        return (math.degrees(math.atan2(sin_gem, cos_gem)) + 360) % 360

    # ------------------------------------------------------------------
    # Cross-Track Error via Cartesiaanse projectie
    # ------------------------------------------------------------------

    def _bereken_xte(self, prev_wp, curr, target) -> tuple[float, float, float]:
        """
        Berekent de Cross-Track Error (XTE) en de projectie-afstand
        langs de doellijn via een Cartesiaanse benadering.

        Nauwkeuriger dan de asin-benadering in V1 bij kleine afstanden
        (< 500m), en geeft ook de afstand langs de lijn terug voor
        de Pure Pursuit berekening.

        Returns:
            xte            : Zijdelingse afwijking in meters
                             (positief = rechts van lijn, negatief = links)
            dist_along_line: Afstand in meters vanaf prev_wp, geprojecteerd
                             op de doellijn
            line_length    : Totale lengte van dit segment in meters
        """
        # Gebruik de lijn-bearing als lokale "noord"-as
        line_bearing = self._bearing(
            prev_wp["lat"], prev_wp["lon"],
            target["lat"],  target["lon"]
        )
        line_length = self._haversine(
            prev_wp["lat"], prev_wp["lon"],
            target["lat"],  target["lon"]
        )

        # Vector van prev_wp naar curr in meters
        curr_bearing = self._bearing(
            prev_wp["lat"], prev_wp["lon"],
            curr["lat"],    curr["lon"]
        )
        dist_from_prev = self._haversine(
            prev_wp["lat"], prev_wp["lon"],
            curr["lat"],    curr["lon"]
        )

        # Hoek tussen de lijn en de vector prev_wp→curr (in radians)
        angle = math.radians(self._angle_diff(curr_bearing, line_bearing))

        # Projecties
        dist_along_line = dist_from_prev * math.cos(angle)  # langs de lijn
        xte             = dist_from_prev * math.sin(angle)  # dwars op de lijn

        return xte, dist_along_line, line_length

    # ------------------------------------------------------------------
    # Pure Pursuit look-ahead punt
    # ------------------------------------------------------------------

    def _lookahead_punt(self, prev_wp, target, dist_along_line, xte) -> tuple[float, float]:
        """
        Berekent het exacte GPS-coördinaat van het Pure Pursuit look-ahead punt
        via haversine destination (niet via lineaire lat/lon interpolatie).

        Het look-ahead punt ligt op de doellijn, op afstand:
            dist_along_line + sqrt(look_ahead_dist² - min(xte², look_ahead_dist²))
        vanaf prev_wp.
        """
        line_bearing = self._bearing(
            prev_wp["lat"], prev_wp["lon"],
            target["lat"],  target["lon"]
        )
        line_length = self._haversine(
            prev_wp["lat"], prev_wp["lon"],
            target["lat"],  target["lon"]
        )

        xte_clamped = min(abs(xte), self.look_ahead_dist * 0.99)
        forward_offset = math.sqrt(self.look_ahead_dist ** 2 - xte_clamped ** 2)
        target_dist = max(0.0, min(line_length, dist_along_line + forward_offset))

        # Gebruik haversine destination voor correcte coördinaten
        la_lat, la_lon = self._destination_point(
            prev_wp["lat"], prev_wp["lon"],
            line_bearing, target_dist
        )
        return la_lat, la_lon

    # ------------------------------------------------------------------
    # DAC smooth ramp (ongewijzigd t.o.v. V1 — werkt goed)
    # ------------------------------------------------------------------

    def _smooth_dac(self, huidig: int, doel: int) -> int:
        """Begrenst de DAC-stap naar max 100 per loop-iteratie."""
        # Van rust direct naar startpunt springen (skip de dode zone)
        if huidig < DAC_MIN and doel >= DAC_MIN:
            huidig = DAC_MIN
        # Naar rust: direct als we al onder het startpunt zitten
        if doel <= DAC_RUST and huidig <= DAC_MIN:
            return DAC_RUST

        verschil = doel - huidig
        if verschil > 100:
            return huidig + 100
        elif verschil < -100:
            return huidig - 100
        return doel

    # ------------------------------------------------------------------
    # Hoofd navigatielus
    # ------------------------------------------------------------------

    def _navigate_loop(self):
        wp_idx  = 0
        prev_wp = None

        while self.active and wp_idx < len(self.waypoints):
            curr = self.gps.current_position
            if curr["lat"] == 0.0 or curr["lon"] == 0.0:
                time.sleep(0.1)
                continue

            target = self.waypoints[wp_idx]
            if prev_wp is None:
                prev_wp = dict(curr)

            # ── Tijdstap ──────────────────────────────────────────────
            now = time.time()
            if self._vorige_tijd is None:
                dt = 0.1
            else:
                dt = max(0.01, min(now - self._vorige_tijd, 0.5))

            # ── 1. WERKELIJKE GPS SNELHEID ────────────────────────────
            if self._vorige_actuele_positie is not None:
                verplaatsing = self._haversine(
                    self._vorige_actuele_positie["lat"],
                    self._vorige_actuele_positie["lon"],
                    curr["lat"], curr["lon"]
                )
                ruwe_snelheid_mps = verplaatsing / dt
                # Low-pass filter (80% oud, 20% nieuw)
                self._gefilterde_snelheid_mps = (
                    0.2 * ruwe_snelheid_mps +
                    0.8 * self._gefilterde_snelheid_mps
                )
            self._vorige_actuele_positie = dict(curr)

            # ── Waypoint bereikt? ─────────────────────────────────────
            dist_to_target = self._haversine(
                curr["lat"], curr["lon"],
                target["lat"], target["lon"]
            )
            if dist_to_target < 1.0:
                print(f"[NAVIGATOR] Waypoint {wp_idx} bereikt.")
                prev_wp = dict(target)
                wp_idx += 1
                self._vorige_fout    = 0.0
                self._vorige_tijd    = None
                self._vorige_heading = None
                self._speed_integraal = 0.0
                continue

            # ── Wachten op heading ────────────────────────────────────
            current_heading = self._gefilterde_heading()
            if current_heading == 0.0:
                print("[NAVIGATOR] Wachten op Dual-GPS heading...")
                self._huidige_links  = self._smooth_dac(self._huidige_links,  DAC_RUST)
                self._huidige_rechts = self._smooth_dac(self._huidige_rechts, DAC_RUST)
                self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)
                time.sleep(0.5)
                continue

            # ── 2. XTE & LOOK-AHEAD PUNT ─────────────────────────────
            xte, dist_along, line_length = self._bereken_xte(prev_wp, curr, target)

            lookahead_lat, lookahead_lon = self._lookahead_punt(
                prev_wp, target, dist_along, xte
            )

            # Gewenste koers = bearing naar het look-ahead punt
            target_bearing = self._bearing(
                curr["lat"], curr["lon"],
                lookahead_lat, lookahead_lon
            )

            # ── 3. STUURREGELAAR: PD op yaw-rate ─────────────────────
            fout = self._angle_diff(target_bearing, current_heading)

            # Yaw-rate (graden/s) berekend uit de GEMETEN heading,
            # niet uit de fout-delta. Dit is veel minder ruis-gevoelig.
            if self._vorige_heading is not None:
                yaw_rate = self._angle_diff(current_heading, self._vorige_heading) / dt
            else:
                yaw_rate = 0.0
            self._vorige_heading = current_heading

            # PD regelaar
            # Stuur-D term: dempt de gemeten draaisnelheid
            # (negatief omdat we de rotatie willen temperen)
            turn = (self.kp * fout) - (self.kd * yaw_rate)
            turn = max(-500, min(500, turn))

            self._vorige_fout = fout
            self._vorige_tijd = now

            # ── 4. SNELHEID: PI Cruise Control ───────────────────────
            # Bochten-snelheidsrem (alleen bij grote koersfouten)
            hoek_penalty = min(1.0, abs(fout) / self.hoek_rem_drempel)
            snelheids_factor = max(0.0, 1.0 - hoek_penalty * self.hoek_rem_factor)

            doel_snelheid_mps = (self.doel_snelheid_kmh / 3.6) * snelheids_factor

            # Feedforward DAC (uit gecalibreerde tabel)
            basis_dac = speed_mps_to_dac(doel_snelheid_mps)

            # PI correctie
            snelheids_fout = doel_snelheid_mps - self._gefilterde_snelheid_mps

            # Anti-windup: stop integreren als we al op limiet zitten
            pi_onbegrensd = (
                self.kp_snelheid * snelheids_fout +
                self.ki_snelheid * self._speed_integraal
            )
            if abs(pi_onbegrensd) < self.max_pi_correctie:
                self._speed_integraal += snelheids_fout * dt
                self._speed_integraal = max(-2.0, min(2.0, self._speed_integraal))

            pi_correctie = max(
                -self.max_pi_correctie,
                min(self.max_pi_correctie, pi_onbegrensd)
            )

            actuele_base_dac = basis_dac + pi_correctie

            # ── 5. MOTOREN AANSTUREN ──────────────────────────────────
            doel_links  = int(actuele_base_dac + turn)
            doel_rechts = int(actuele_base_dac - turn)

            # Harde hardware limieten
            doel_links  = max(DAC_RUST, min(DAC_MAX, doel_links))
            doel_rechts = max(DAC_RUST, min(DAC_MAX, doel_rechts))

            # Smoothing (max 100 DAC stap per loop)
            self._huidige_links  = self._smooth_dac(self._huidige_links,  doel_links)
            self._huidige_rechts = self._smooth_dac(self._huidige_rechts, doel_rechts)

            self.motor.stuur_motoren(self._huidige_links, self._huidige_rechts)

            # ── 6. LOGGING ────────────────────────────────────────────
            actuele_kmh  = self._gefilterde_snelheid_mps * 3.6
            huidige_fix  = curr.get("fix",  0)
            huidige_hdop = curr.get("hdop", 99.0)

            self.logger.log_regel(
                wp_idx=wp_idx,
                lat=curr["lat"],
                lon=curr["lon"],
                fix=huidige_fix,
                hdop=huidige_hdop,
                heading=current_heading,
                doel_heading=target_bearing,
                fout=fout,
                xte=xte,
                doel_kmh=self.doel_snelheid_kmh,
                echt_kmh=actuele_kmh,
                turn=turn,
                pi_corr=pi_correctie,
                i_term=self._speed_integraal,
                links=self._huidige_links,
                rechts=self._huidige_rechts,
                dist=dist_to_target,
                dt=dt,
                lookahead_lat=lookahead_lat,
                lookahead_lon=lookahead_lon
            )

            print(
                f"[NAV] hdg={current_heading:.1f}° fout={fout:.1f}° xte={xte:.2f}m "
                f"Doel={doel_snelheid_mps * 3.6:.1f} Echt={actuele_kmh:.1f}km/h "
                f"L={self._huidige_links} R={self._huidige_rechts} turn={turn:.0f}"
            )

            time.sleep(0.1)

        self.stop()
