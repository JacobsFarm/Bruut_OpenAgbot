import math
import time
import threading
import logging

try:
    from app.services.logger import DriveLogger
except ImportError:
    DriveLogger = None

R_EARTH = 6371000.0


def maak_baan_volgorde(aantal_banen, banen_overslaan=1):
    """
    Werkvolgorde van de banen ('skip pass' / racebaan-patroon).

    Bij banen_overslaan=1 sla je op de heenweg steeds een baan over
    (0, 2, 4, 6) en vul je op de terugweg de gaten (7, 5, 3, 1). Zo is de
    zijwaartse sprong bij vrijwel elke kopakkerbocht 2x de werkbreedte, en
    dat is precies wat een vierwieler nodig heeft: een halve cirkel van
    2x de minimale draaicirkel past dan gewoon binnen de kopakker.
    Alleen op het keerpunt van het patroon (6 -> 7) liggen twee banen
    naast elkaar; daar draait de robot een omega-bocht.
    """
    stap = max(1, int(banen_overslaan) + 1)
    volgorde = []
    for start in range(stap):
        laag = list(range(start, aantal_banen, stap))
        if start % 2 == 1:
            laag.reverse()          # afwisselend heen en terug door het veld
        volgorde.extend(laag)
    return volgorde


class ABNavigator:
    """
    AB-lijn navigator voor het rijden van parallelle banen ('swaths').

    Werkt - net als de waypoint-Navigator - volledig in KOMPAS-graden
    (0 graden = Noord, met de klok mee). Dit is essentieel: de GPS levert een
    kompasheading, dus alle hoek-wiskunde moet in datzelfde stelsel gebeuren.

    Alle navigatie gebeurt in het LIJNFRAME rond punt A:
        along = afstand langs de AB-lijn (0 = punt A, field_length = punt B)
        cross = afstand haaks op de lijn, positief naar rechts van A->B

    Gedrag:
      1. START : pak de AB-lijn op. Staat A == B (of liggen ze vlak bij
                 elkaar), dan wordt de baanrichting afgeleid uit de huidige
                 neus-richting (GPS-heading) en de huidige positie.
      2. BAAN  : volg de baanlijn met pure pursuit van along=0 tot along=L en
                 rijd daarna nog 'kopakker_extra_m' meter rechtdoor de kopakker
                 op. Daar is ruimte om te draaien, buiten het gewas.
      3. BOCHT : draai op de kopakker naar de VOLGENDE baan uit de werkvolgorde.
                 Past er een halve cirkel (zijsprong >= 2x de minimale
                 draaicirkel), dan draait hij die; anders een omega-bocht:
                 eerst van de baan af, dan een ruime lus terug. Beide eindigen
                 op dezelfde 'along' als waar de bocht begon, dus de robot komt
                 de kopakker weer in op precies dat punt - met nog de volle
                 'kopakker_extra_m' meter rechte aanloop om kaarsrecht op de
                 nieuwe lijn te liggen voordat het gewas begint.
      4. EIND  : als de hele werkvolgorde gereden is, stopt de missie.
    """

    def __init__(self, gps_system, vehicle_controller, config):
        self.logger = logging.getLogger(__name__)
        self.drive_logger = DriveLogger() if DriveLogger else None

        self.gps = gps_system
        self.vehicle = vehicle_controller

        # Voertuig / stuur
        self.wheelbase = config.get("vehicle", {}).get("wheelbase_m", 1.2)
        # Grootste stuurhoek van het virtuele midden van de vooras. Dit is NIET
        # de wiellimiet uit de config: het binnenste voorwiel staat bij Ackermann
        # scherper dan het midden. Via deze waarde klopt ook de minimale
        # draaicirkel hieronder, en daarmee de kopakkerbocht.
        self.max_angle = getattr(
            vehicle_controller, "max_center_angle",
            config.get("steering", {}).get("max_angle_degrees", 45.0)
        )

        # Navigatie-instellingen (met config-fallback)
        nav_cfg = config.get("navigation", {})
        self.lookahead_m = nav_cfg.get("lookahead_distance_m", 2.5)
        self.turn_speed_kmh = nav_cfg.get("turn_speed_kmh", 2.0)
        self.max_swaths = nav_cfg.get("max_swaths", 1000)
        # Kopakker: hoeveel meter voorbij het einde van de baan hij doorrijdt
        # voordat de bocht begint. Diezelfde marge gebruikt hij aan de andere
        # kant als aanloop om recht op de nieuwe lijn te komen.
        self.headland_overrun_m = nav_cfg.get("headland_overrun_m", 2.0)
        # Bochtvolgen: kortere lookahead dan op de lijn, anders snijdt pure
        # pursuit de boog af en komt hij scheef de nieuwe baan in.
        self.turn_lookahead_m = nav_cfg.get("turn_lookahead_m", 1.5)
        # Bocht klaar als de koers binnen deze tolerantie van de nieuwe
        # baanrichting ligt; de timeout voorkomt eindeloos rondjes draaien.
        self.turn_heading_tol_deg = nav_cfg.get("turn_heading_tolerance_deg", 5.0)
        self.turn_timeout_s = nav_cfg.get("turn_timeout_s", 90.0)
        # Sample-afstand van het bochtpad (m). Kleiner = gladder, meer punten.
        self.turn_step_m = 0.25

        # Missie-parameters (gezet via start_mission)
        self.work_width_m = 4.0
        self.field_length_m = 50.0
        self.target_speed_kmh = 3.0
        self.kant_sign = 1.0             # +1 = banen liggen rechts van A->B
        self.swath_order = []            # werkvolgorde, bv. [0,2,4,6,7,5,3,1]

        # Lijn-definitie (lokaal kompasframe rond een vast referentiepunt)
        self.ref_lat = 0.0
        self.ref_lon = 0.0
        self.base_bearing_deg = 0.0      # richting van baan 0 (kompas)
        self.line_initialized = False    # False = afleiden uit eerste GPS-fix
        self.ab_length_m = 0.0           # gemeten afstand A->B

        # Missie-status
        self.is_active = False
        self.nav_thread = None
        self.state = "IDLE"              # IDLE | TRACKING | TURNING
        self.status_message = "Gestopt"
        self.order_index = 0             # positie in self.swath_order
        self.current_swath = 0           # het baannummer dat nu gereden wordt
        self.pass_sign = 1.0             # +1 = richting A->B, -1 = terug
        self.first_sign = None           # rijrichting van de eerste baan
        self.in_werkzone = False         # False = op de kopakker, buiten het gewas

        # Kopakker-bocht (pad in lijnframe + pure pursuit)
        self.turn_path = []              # [(along, cross), ...]
        self.turn_idx = 0                # dichtstbijzijnde padpunt tot nu toe
        self.turn_tail_idx = 0           # vanaf hier is het pad de rechte aanloop
        self.turn_target_bearing = 0.0   # koers van de volgende baan
        self.turn_start_time = 0.0

    # ------------------------------------------------------------------ #
    #  Publieke API (gebruikt door endpoints.py)
    # ------------------------------------------------------------------ #
    def set_ab_line(self, lat_a, lon_a, lat_b, lon_b):
        if None in (lat_a, lon_a, lat_b, lon_b):
            return False

        self.ref_lat = lat_a
        self.ref_lon = lon_a

        # Verschillen A en B genoeg om er een richting uit te halen?
        ab_dist = self._haversine(lat_a, lon_a, lat_b, lon_b)
        if ab_dist > 1.0:
            self.base_bearing_deg = self._bearing(lat_a, lon_a, lat_b, lon_b)
            self.line_initialized = True
            self.ab_length_m = ab_dist
            self.logger.info(
                f"AB-lijn gezet uit A->B: richting {self.base_bearing_deg:.1f} graden "
                f"({ab_dist:.1f} m tussen A en B)."
            )
        else:
            # A == B: richting + oorsprong afleiden uit de eerste goede GPS-fix.
            self.line_initialized = False
            self.ab_length_m = 0.0
            self.logger.info(
                "A en B vallen samen -> baanrichting wordt bij start afgeleid "
                "uit de huidige neus-richting (GPS-heading)."
            )

        self.order_index = 0
        self.current_swath = 0
        return True

    def start_mission(self, work_width, field_length, speed,
                      swath_order=None, aantal_banen=None, banen_overslaan=1,
                      kopakker_extra_m=None, kant="rechts"):
        """
        Start de missie. 'swath_order' is de werkvolgorde van de banen; geef je
        die niet mee, dan wordt hij uit 'aantal_banen' + 'banen_overslaan'
        opgebouwd. Zonder allebei valt hij terug op 0,1,2,... - dat werkt, maar
        vraagt bij elke kopakker een omega-bocht omdat de banen dan tegen
        elkaar aan liggen.
        """
        self.work_width_m = max(0.1, work_width)
        # Zonder bruikbare baanlengte pakken we de gemeten afstand A->B: B is
        # tenslotte de overkant van het veld, dus die lengte staat er al in.
        if (not field_length or field_length < 1.0) and self.ab_length_m > 1.0:
            field_length = self.ab_length_m
            self.logger.info(f"Baanlengte niet opgegeven -> {field_length:.1f} m uit A->B.")
        self.field_length_m = max(1.0, field_length)
        self.target_speed_kmh = speed
        self.kant_sign = -1.0 if str(kant).lower().startswith("l") else 1.0
        if kopakker_extra_m is not None:
            self.headland_overrun_m = max(0.0, kopakker_extra_m)

        if swath_order:
            self.swath_order = [int(i) for i in swath_order]
        elif aantal_banen:
            self.swath_order = maak_baan_volgorde(int(aantal_banen), banen_overslaan)
        else:
            self.swath_order = list(range(self.max_swaths))

        if self.is_active:
            self.stop()

        self.order_index = 0
        self.current_swath = self.swath_order[0]
        self.first_sign = None
        self.pass_sign = 1.0
        self.state = "TRACKING"
        self.status_message = "Missie gestart"

        if self.drive_logger:
            self.drive_logger.start_nieuwe_rit(navigatie_modus="AB_Missie")

        # Minimale draaicirkel uit de hardware (twee gestuurde voorwielen):
        # R_min = wielbasis / tan(max middenhoek). Een halve cirkel verplaatst
        # de robot 2*R_min zijwaarts; is de zijsprong kleiner, dan draait hij
        # automatisch een omega-bocht in plaats van een halve cirkel.
        r_min = self._min_radius()
        sprong = self._kleinste_zijsprong()

        self.is_active = True
        self.nav_thread = threading.Thread(target=self._navigation_loop, daemon=True)
        self.nav_thread.start()
        self.logger.info(
            f"AB-missie gestart: {len(self.swath_order)} banen "
            f"{self.swath_order[:12]}{' ...' if len(self.swath_order) > 12 else ''}, "
            f"werkbreedte={self.work_width_m} m, baanlengte={self.field_length_m} m, "
            f"kopakker={self.headland_overrun_m} m, snelheid={self.target_speed_kmh} km/h, "
            f"R_min={r_min:.2f} m, kleinste zijsprong={sprong:.2f} m "
            f"({'halve cirkel' if sprong >= 2 * r_min else 'omega-bocht nodig'})."
        )

    def stop(self):
        self.is_active = False
        self.state = "IDLE"
        self.in_werkzone = False
        # Wachten op de navigatiethread mag NIET als we er zelf in zitten: dat
        # gebeurt zodra de missie zichzelf beeindigt na de laatste baan, en
        # join() op je eigen thread gooit een RuntimeError. Die vloog er dan
        # tussenuit voordat vehicle.stop() werd bereikt - en dan bleef het
        # voertuig op zijn laatste DAC-waarde doorrijden. is_active staat hier
        # al op False, dus de lus stopt hoe dan ook vanzelf.
        if (self.nav_thread and self.nav_thread.is_alive()
                and self.nav_thread is not threading.current_thread()):
            self.nav_thread.join(timeout=1.0)
        self.vehicle.stop()
        if self.drive_logger:
            self.drive_logger.stop_log()
        self.status_message = "Gestopt"
        self.logger.info("AB-missie gestopt.")

    # ------------------------------------------------------------------ #
    #  Hoofdlus
    # ------------------------------------------------------------------ #
    def _navigation_loop(self):
        rate_hz = 10.0
        interval = 1.0 / rate_hz

        while self.is_active:
            start_time = time.time()
            curr_pos = self.gps.get_current_position()

            # Veiligheid: geen (RTK-)fix -> stilstaan
            if not curr_pos or curr_pos.get("lat", 0.0) == 0.0 or curr_pos.get("fix", 0) < 2:
                self.vehicle.drive(0.0, 0.0)
                self.status_message = "Wacht op GPS-fix"
                time.sleep(0.1)
                continue

            # Lijn afleiden bij eerste goede fix (alleen als A == B)
            if not self.line_initialized:
                self.ref_lat = curr_pos["lat"]
                self.ref_lon = curr_pos["lon"]
                self.base_bearing_deg = curr_pos["heading"]
                self.line_initialized = True
                self.logger.info(
                    f"Baanrichting afgeleid uit neus: {self.base_bearing_deg:.1f} graden."
                )

            # Rijrichting van de EERSTE baan uit de neus-richting: sta je bij B
            # in plaats van bij A, dan rijdt hij de lijn gewoon andersom af.
            if self.first_sign is None:
                verschil = abs(self._norm180(curr_pos["heading"] - self.base_bearing_deg))
                self.first_sign = -1.0 if verschil > 90.0 else 1.0
                self.pass_sign = self.first_sign
                self.logger.info(
                    f"Eerste baan wordt gereden richting "
                    f"{'A->B' if self.first_sign > 0 else 'B->A'} "
                    f"(neus {curr_pos['heading']:.0f} graden)."
                )

            if self.state == "TRACKING":
                self._handle_tracking(curr_pos)
            elif self.state == "TURNING":
                self._handle_turning(curr_pos)

            elapsed = time.time() - start_time
            time.sleep(max(0.01, interval - elapsed))

        self.vehicle.stop()

    # ------------------------------------------------------------------ #
    #  TRACKING: volg de huidige baanlijn met pure pursuit
    # ------------------------------------------------------------------ #
    def _handle_tracking(self, curr_pos):
        along, cross = self._along_cross(curr_pos["lat"], curr_pos["lon"])
        sign = self.pass_sign
        offset = self._swath_offset(self.current_swath)
        xte = cross - offset                                 # cross-track error

        # Het gewas loopt van along=0 tot along=L; daarbuiten ligt de kopakker.
        self.in_werkzone = 0.0 <= along <= self.field_length_m
        uitrij_along = self._uitrij_along(sign)

        # Kopakker bereikt (baan + doorloop) -> bocht naar de volgende baan
        if sign * (along - uitrij_along) >= 0.0:
            if self.order_index + 1 >= len(self.swath_order):
                self.logger.info("Alle banen gereden. Missie klaar.")
                self.status_message = "Missie klaar"
                self.stop()
                return
            self._plan_turn(along)
            self.state = "TURNING"
            return

        # Carrot-punt: op de baanlijn, 'lookahead' meter vooruit.
        carrot_along = along + sign * self.lookahead_m
        target_bearing = self._frame_bearing(carrot_along - along, offset - cross)
        steering = self._pure_pursuit_steer(target_bearing, curr_pos["heading"], self.lookahead_m)

        self.vehicle.drive(self.target_speed_kmh, steering)

        rest = sign * (uitrij_along - along)
        self.status_message = (
            f"Baan {self.current_swath} ({self.order_index + 1}/{len(self.swath_order)}) - "
            f"{'gewas' if self.in_werkzone else 'kopakker'}, nog {rest:.0f} m, "
            f"afwijking {xte:+.2f} m"
        )

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=curr_pos["heading"], heading_doel=target_bearing,
                heading_fout=xte, stuurhoek=steering, doel_kmh=self.target_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                dist_wp=rest, lookahead=self.lookahead_m, dt=0.1
            )

    # ------------------------------------------------------------------ #
    #  TURNING: volg het vooraf berekende kopakkerpad met pure pursuit
    # ------------------------------------------------------------------ #
    def _handle_turning(self, curr_pos):
        heading = curr_pos["heading"]
        along, cross = self._along_cross(curr_pos["lat"], curr_pos["lon"])
        self.in_werkzone = False

        # 1. Schuif mee over het pad: zoek het dichtstbijzijnde punt VOORUIT.
        #    De index loopt alleen vooruit, zodat de robot niet terugvalt op het
        #    begin van de boog als hij daar toevallig weer langs komt.
        beste_idx = self.turn_idx
        beste_d = self._pad_afstand(self.turn_path[beste_idx], along, cross)
        for i in range(self.turn_idx + 1, min(len(self.turn_path), self.turn_idx + 60)):
            d = self._pad_afstand(self.turn_path[i], along, cross)
            if d < beste_d:
                beste_idx, beste_d = i, d
        self.turn_idx = beste_idx

        # 2. Bocht klaar? Op de rechte aanloop EN de koers ligt op de nieuwe
        #    baan. De timeout is het vangnet tegen eindeloos rondjes draaien.
        rest_hoek = abs(self._norm180(self.turn_target_bearing - heading))
        timeout = (time.time() - self.turn_start_time) > self.turn_timeout_s
        einde_pad = self.turn_idx >= len(self.turn_path) - 2
        if (self.turn_idx >= self.turn_tail_idx and rest_hoek <= self.turn_heading_tol_deg) \
                or einde_pad or timeout:
            self.order_index += 1
            self.current_swath = self.swath_order[self.order_index]
            self.pass_sign = -self.pass_sign
            self.state = "TRACKING"
            if timeout:
                self.logger.warning(
                    f"Bocht-timeout ({self.turn_timeout_s:.0f}s) -> baan "
                    f"{self.current_swath} wordt geforceerd opgepakt."
                )
            else:
                self.logger.info(f"Bocht klaar. Baan {self.current_swath} wordt opgepakt.")
            return

        # 3. Carrot: het eerste padpunt op minstens 'turn_lookahead' meter.
        doel = self.turn_path[-1]
        for i in range(self.turn_idx, len(self.turn_path)):
            if self._pad_afstand(self.turn_path[i], along, cross) >= self.turn_lookahead_m:
                doel = self.turn_path[i]
                break

        target_bearing = self._frame_bearing(doel[0] - along, doel[1] - cross)
        steering = self._pure_pursuit_steer(target_bearing, heading, self.turn_lookahead_m)
        self.vehicle.drive(self.turn_speed_kmh, steering)

        self.status_message = (
            f"Kopakkerbocht naar baan {self.swath_order[self.order_index + 1]} - "
            f"{100 * self.turn_idx // max(1, len(self.turn_path) - 1)}%, "
            f"nog {rest_hoek:.0f} graden"
        )

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=heading, heading_doel=target_bearing,
                heading_fout=rest_hoek, stuurhoek=steering, doel_kmh=self.turn_speed_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dac_links=self.vehicle.current_dac_links,
                dac_rechts=self.vehicle.current_dac_rechts,
                dist_wp=beste_d, lookahead=self.turn_lookahead_m, dt=0.1
            )

    def _plan_turn(self, along):
        """Bouw het kopakkerpad naar de volgende baan uit de werkvolgorde."""
        volgende = self.swath_order[self.order_index + 1]
        cross_van = self._swath_offset(self.current_swath)
        cross_naar = self._swath_offset(volgende)

        pad, staart_idx, diepte, soort = self._bouw_bochtpad(
            along, cross_van, cross_naar, self.pass_sign
        )
        self.turn_path = pad
        self.turn_tail_idx = staart_idx
        self.turn_idx = 0
        self.turn_start_time = time.time()

        # Richting van de volgende baan = de huidige, 180 graden omgekeerd.
        nieuw_sign = -self.pass_sign
        forward = self.base_bearing_deg if nieuw_sign > 0 else self.base_bearing_deg + 180.0
        self.turn_target_bearing = forward % 360.0

        zijsprong = abs(cross_naar - cross_van)
        self.logger.info(
            f"Kopakkerbocht ({soort}) van baan {self.current_swath} naar {volgende}: "
            f"zijsprong {zijsprong:.2f} m, {diepte:.2f} m kopakker nodig voorbij het "
            f"draaipunt, doelkoers {self.turn_target_bearing:.1f} graden."
        )

    # ------------------------------------------------------------------ #
    #  Bochtgeometrie
    # ------------------------------------------------------------------ #
    def _bouw_bochtpad(self, exit_along, cross_van, cross_naar, sign):
        """
        Bouwt het kopakkerpad als puntenlijst in het lijnframe (along, cross).

        Gerekend wordt in het VOERTUIGFRAME: u = vooruit, v = naar rechts,
        psi = gedraaide hoek (positief = naar rechts). De bocht bestaat uit
        drie bogen met dezelfde straal R:

            eerst -alpha (van de volgende baan AF), dan +(180 + 2*alpha)
            (de grote lus terug) en dan nog eens -alpha om recht te komen.

        Netto draait de robot exact 180 graden en verschuift hij
            d = 2*R*(2*cos(alpha) - 1)
        naar de kant van de volgende baan, terwijl de verplaatsing VOORUIT
        precies nul is. Dat laatste is de sleutel: de bocht eindigt op dezelfde
        'along' als waar hij begon, dus na de bocht heeft de robot weer de
        volle 'kopakker_extra_m' meter rechte aanloop voordat het gewas begint,
        en komt hij dus recht de nieuwe lijn in.

        Is de zijsprong groot genoeg (>= 2*R_min), dan valt alpha op nul weg en
        blijft er een gewone halve cirkel met straal d/2 over. Er wordt nooit
        achteruit gereden: de hubmotoren kunnen dat niet.
        """
        d_rechts = sign * (cross_naar - cross_van)     # + = de bocht gaat naar rechts
        d = abs(d_rechts)
        spiegel = 1.0 if d_rechts >= 0 else -1.0

        r_min = self._min_radius()
        if d >= 2.0 * r_min:
            radius = d / 2.0
            alpha = 0.0
            soort = "halve cirkel"
        else:
            radius = r_min
            cos_a = max(-1.0, min(1.0, (d + 2.0 * radius) / (4.0 * radius)))
            alpha = math.degrees(math.acos(cos_a))
            soort = f"omega, uitwijkhoek {alpha:.0f} graden"

        bogen = [(-alpha, radius), (180.0 + 2.0 * alpha, radius), (-alpha, radius)]

        u, v, psi = 0.0, 0.0, 0.0
        punten = [(u, v)]
        for hoek, r in bogen:
            hoek = spiegel * hoek
            if abs(hoek) < 1e-6:
                continue
            stappen = max(1, int(math.radians(abs(hoek)) * r / self.turn_step_m))
            dpsi = hoek / stappen
            draai = 1.0 if dpsi > 0 else -1.0
            for _ in range(stappen):
                # Het middelpunt van de boog ligt haaks op de rijrichting, aan de
                # kant waar we naartoe draaien. Daarna roteren we het voertuig
                # dpsi graden om dat middelpunt: een exacte boog, geen benadering.
                pr = math.radians(psi)
                cu = u - draai * r * math.sin(pr)
                cv = v + draai * r * math.cos(pr)
                psi += dpsi
                pr = math.radians(psi)
                u = cu + draai * r * math.sin(pr)
                v = cv - draai * r * math.cos(pr)
                punten.append((u, v))

        # Rechte aanloop op de nieuwe lijn, zodat de pure-pursuit carrot aan het
        # eind van de bocht niet 'opraakt' en de robot netjes uitgelijnd wordt.
        staart_idx = len(punten) - 1
        staart_m = self.turn_lookahead_m + 1.5
        pr = math.radians(psi)
        du, dv = math.cos(pr) * self.turn_step_m, math.sin(pr) * self.turn_step_m
        for _ in range(max(1, int(staart_m / self.turn_step_m))):
            u += du
            v += dv
            punten.append((u, v))

        diepte = max(p[0] for p in punten)             # hoe ver de bocht vooruit steekt
        pad = [(exit_along + sign * pu, cross_van + sign * pv) for pu, pv in punten]
        return pad, staart_idx, diepte, soort

    def _min_radius(self):
        """Minimale draaicirkel van het virtuele midden van de vooras (m)."""
        return self.wheelbase / math.tan(math.radians(self.max_angle))

    def _kleinste_zijsprong(self):
        """Kleinste zijwaartse sprong die in de werkvolgorde voorkomt (m)."""
        if len(self.swath_order) < 2:
            return float("inf")
        return min(
            abs(self.swath_order[i + 1] - self.swath_order[i]) * self.work_width_m
            for i in range(len(self.swath_order) - 1)
        )

    def _swath_offset(self, swath):
        """Afstand van baan 'swath' tot de AB-lijn, positief naar rechts."""
        return self.kant_sign * swath * self.work_width_m

    def _uitrij_along(self, sign):
        """Waar de baan eindigt: het veld plus de kopakker-doorloop."""
        if sign > 0:
            return self.field_length_m + self.headland_overrun_m
        return -self.headland_overrun_m

    @staticmethod
    def _pad_afstand(punt, along, cross):
        return math.hypot(punt[0] - along, punt[1] - cross)

    # ------------------------------------------------------------------ #
    #  Wiskunde-helpers (alles in kompas-graden)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm180(deg):
        """Normaliseer een hoekverschil naar -180 .. +180 graden."""
        return (deg + 180.0) % 360.0 - 180.0

    def _frame_bearing(self, d_along, d_cross):
        """Kompaskoers naar een punt dat (d_along, d_cross) verderop ligt."""
        return (self.base_bearing_deg + math.degrees(math.atan2(d_cross, d_along))) % 360.0

    def _pure_pursuit_steer(self, target_bearing_deg, heading_deg, lookahead_m):
        alpha = (target_bearing_deg - heading_deg + 180.0) % 360.0 - 180.0
        alpha_rad = math.radians(alpha)
        delta = math.degrees(
            math.atan2(2.0 * self.wheelbase * math.sin(alpha_rad), max(0.5, lookahead_m))
        )
        return max(-self.max_angle, min(self.max_angle, delta))

    def _along_cross(self, lat, lon):
        """Projecteer (lat,lon) op het baanframe: langs- en rechts-afstand (m)."""
        north = R_EARTH * math.radians(lat - self.ref_lat)
        east = R_EARTH * math.radians(lon - self.ref_lon) * math.cos(math.radians(self.ref_lat))
        b = math.radians(self.base_bearing_deg)
        along = north * math.cos(b) + east * math.sin(b)
        right = -north * math.sin(b) + east * math.cos(b)
        return along, right

    def _haversine(self, lat1, lon1, lat2, lon2):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _bearing(self, lat1, lon1, lat2, lon2):
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dlmb = math.radians(lon2 - lon1)
        y = math.sin(dlmb) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
