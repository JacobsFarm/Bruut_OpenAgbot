import math
import time
import threading
import logging

from app.services.gnss_navigatie import GnssBewaker, LijnRegelaar, pad_krommingen

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

    De regellus loopt op het ritme van de GNSS (25 Hz): hij rekent zodra er
    een complete meting (positie + heading) binnen is. Op de rechte banen
    stuurt de LijnRegelaar (Stanley: koersfout + afwijking van de vooras +
    demping op de draaisnelheid), in de bochten pure pursuit over het
    bochtpad. De GnssBewaker bepaalt per meting of en hoe hard er gereden mag
    worden (RTK fixed / float / geen RTK, leeftijd van data en correcties).
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
        # Hoe de bocht gevolgd wordt. 'pad' = vooruitsturing op de kromming
        # van het bochtpad plus Stanley op de raaklijn (LijnRegelaar.stuur_pad);
        # 'pure_pursuit' = sturen op een punt turn_lookahead_m verderop, zoals
        # vroeger.
        self.turn_controller = nav_cfg.get("turn_controller", "pad")
        # De vorm van het bochtpad: 'vloeiend' = de kromming loopt geleidelijk
        # op en af, zodat de stuurmotoren het kunnen volgen (_vloeiende_bocht);
        # 'bogen' = drie cirkelbogen op de kleinste draaicirkel, zoals vroeger.
        self.turn_shape = nav_cfg.get("turn_shape", "vloeiend")
        self.turn_radius_margin = max(1.0, float(nav_cfg.get("turn_radius_margin", 1.1)))
        self.turn_rate_fraction = min(1.0, max(0.1, float(nav_cfg.get("turn_rate_fraction", 0.6))))
        self._bocht_cache = {}
        self.turn_kappa = []             # kromming per padpunt (1/m, + = rechts)
        self.turn_s = []                 # booglengte per padpunt (m)
        # Baan oppakken: na een bocht (en bij de start) komt hij centimeters
        # naast de lijn en een paar graden scheef binnen. Tot hij binnen deze
        # afwijking EN koersfout op de lijn ligt, staat de integrator van de
        # LijnRegelaar stil: wat die in de aanloop optelt is geen vaste fout,
        # en het kost daarna meters om het weer kwijt te raken. In de sim:
        # afwijking na de eerste 5 m gewas van 1,3-2,3 naar 0,4-1,1 cm RMS.
        # Na de timeout integreert hij hoe dan ook (een vaste fout groter dan
        # de drempel moet ook weg). lane_capture_xte_m = 0 zet het uit.
        self.capture_xte_m = float(nav_cfg.get("lane_capture_xte_m", 0.05))
        self.capture_heading_deg = float(nav_cfg.get("lane_capture_heading_deg", 3.0))
        self.capture_timeout_s = float(nav_cfg.get("lane_capture_timeout_s", 20.0))
        self._baan_opgepakt = False
        self._baan_start = None          # moment van de eerste regelstap op deze baan
        # Van de baan af: heeft hij de lijn eenmaal te pakken (binnen de helft
        # van max_cross_track_m) en raakt hij daarna verder dan
        # max_cross_track_m ervan af, dan klopt er iets niet - een stuurmotor
        # die stappen verliest, een voorwiel dat vastzit, wegglijden op een
        # talud - en stopt de missie in plaats van naast de baan door te
        # rijden. In een kopakkerbocht geldt max_turn_deviation_m tot het
        # bochtpad. 0 = uit.
        self.max_xte_m = float(nav_cfg.get("max_cross_track_m", 1.0))
        self.max_turn_dev_m = float(nav_cfg.get("max_turn_deviation_m", 2.0))
        self._lijn_bereikt = False

        self.bewaker = GnssBewaker(config)
        self.regelaar = LijnRegelaar(config, self.wheelbase, self.max_angle)
        self.toegestaan_kmh = 0.0        # wat de GnssBewaker deze stap toestaat
        self.gnss_melding = None         # bv. "RTK float - langzaam", of None
        self._dt = 0.04                  # werkelijke tijd sinds de vorige regelstap

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

        # Kaart in de webinterface. Het gereden spoor van deze missie, en een
        # versienummer dat ophoogt zodra het geplande rijpad verandert: dan
        # haalt de kaart het plan alleen opnieuw op als het echt anders is.
        self.spoor = []                  # [[lat, lon, 0 = baan / 1 = bocht], ...]
        self.spoor_stap_m = 0.25         # nieuw spoorpunt na zoveel meter
        self.spoor_max_punten = 100000   # ruim 25 km; daarna stopt het bijhouden
        self.plan_versie = 0
        self.missie_nr = 0               # telt per start, zodat de kaart een nieuw spoor herkent
        self.voltooid = False            # alle banen gereden
        self.punt_b = None               # B zoals ingemeten, alleen voor de kaart

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
        self.punt_b = (lat_b, lon_b) if ab_dist > 1.0 else None
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
        if (not field_length or field_length < 1.0) and self.ab_length_m > 1.0:
            self.logger.info(f"Baanlengte niet opgegeven -> {self.ab_length_m:.1f} m uit A->B.")
        (self.work_width_m, self.field_length_m, self.swath_order,
         self.kant_sign, self.headland_overrun_m) = self._missie_instellingen(
            work_width, field_length, swath_order, aantal_banen, banen_overslaan,
            kopakker_extra_m, kant, self.ab_length_m
        )
        self.target_speed_kmh = speed

        if self.is_active:
            self.stop()

        self.order_index = 0
        self.current_swath = self.swath_order[0]
        self.first_sign = None
        self.pass_sign = 1.0
        self._baan_opgepakt, self._baan_start, self._lijn_bereikt = False, None, False
        self.state = "TRACKING"
        self.status_message = "Missie gestart"
        self.voltooid = False
        self.spoor = []
        self.missie_nr += 1
        self.plan_versie += 1

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
        # voertuig op zijn laatste snelheid doorrijden. is_active staat hier
        # al op False, dus de lus stopt hoe dan ook vanzelf.
        if (self.nav_thread and self.nav_thread.is_alive()
                and self.nav_thread is not threading.current_thread()):
            self.nav_thread.join(timeout=1.0)
        self.vehicle.stop()
        if self.drive_logger:
            self.drive_logger.stop_log()
        self.status_message = "Gestopt"
        self.logger.info("AB-missie gestopt.")

    def _missie_instellingen(self, work_width, field_length, swath_order, aantal_banen,
                             banen_overslaan, kopakker_extra_m, kant, ab_length_m):
        """
        Zet de missie-invoer om naar de waarden waarmee gereden wordt:
        (werkbreedte, baanlengte, werkvolgorde, kant_sign, kopakker). Gedeeld
        door start_mission() en preview(), zodat de kaart vooraf precies het
        plan laat zien dat de robot na de start ook rijdt.
        """
        breedte = max(0.1, work_width)
        # Zonder bruikbare baanlengte pakken we de gemeten afstand A->B: B is
        # tenslotte de overkant van het veld, dus die lengte staat er al in.
        if (not field_length or field_length < 1.0) and ab_length_m > 1.0:
            field_length = ab_length_m
        lengte = max(1.0, field_length or 0.0)
        kant_sign = -1.0 if str(kant).lower().startswith("l") else 1.0
        kopakker = (self.headland_overrun_m if kopakker_extra_m is None
                    else max(0.0, kopakker_extra_m))

        if swath_order:
            volgorde = [int(i) for i in swath_order]
        elif aantal_banen:
            volgorde = maak_baan_volgorde(int(aantal_banen), banen_overslaan)
        else:
            volgorde = list(range(self.max_swaths))
        return breedte, lengte, volgorde, kant_sign, kopakker

    # ------------------------------------------------------------------ #
    #  Kaart (webinterface): het rijpad in GPS-coordinaten en het spoor
    # ------------------------------------------------------------------ #
    def plan(self):
        """
        Het rijpad van de lopende of laatst gestarte missie, of None zolang er
        geen lijn is (nog nooit gestart, of A == B en nog geen GPS-fix gehad).
        """
        versie = self.plan_versie        # eerst lezen: verandert hij tijdens het rekenen, dan haalt de kaart hem opnieuw
        if not self.line_initialized or not self.swath_order:
            return None
        plan = self._bouw_plan(
            self.ref_lat, self.ref_lon, self.base_bearing_deg, self.field_length_m,
            self.work_width_m, self.swath_order, self.kant_sign, self.headland_overrun_m,
            self.first_sign or 1.0, self.punt_b
        )
        plan["richting_bekend"] = self.first_sign is not None
        plan["versie"] = versie
        return plan

    def preview(self, lat_a, lon_a, lat_b, lon_b, work_width, field_length,
                swath_order=None, aantal_banen=None, banen_overslaan=1,
                kopakker_extra_m=None, kant="rechts"):
        """
        Het plan voor instellingen die nog niet gestart zijn. Een lopende missie
        merkt er niets van. Maakt dezelfde keuzes als de robot bij de start: de
        lijn uit A->B (of uit de huidige positie en neus als A en B samenvallen)
        en de rijrichting van de eerste baan uit de neus-richting. Geeft None
        als er zonder GPS-fix geen lijn te maken is.
        """
        pos = self.gps.get_current_position()
        gps_ok = bool(pos) and pos.get("lat", 0.0) != 0.0 and pos.get("fix", 0) >= 2

        ab_dist = self._haversine(lat_a, lon_a, lat_b, lon_b)
        if ab_dist > 1.0:
            ref_lat, ref_lon = lat_a, lon_a
            koers = self._bearing(lat_a, lon_a, lat_b, lon_b)
            punt_b = (lat_b, lon_b)
        elif gps_ok:
            ref_lat, ref_lon, koers = pos["lat"], pos["lon"], pos["heading"]
            ab_dist, punt_b = 0.0, None
        else:
            return None

        breedte, lengte, volgorde, kant_sign, kopakker = self._missie_instellingen(
            work_width, field_length, swath_order, aantal_banen, banen_overslaan,
            kopakker_extra_m, kant, ab_dist
        )
        eerste = self._eerste_richting(pos["heading"], koers) if gps_ok else None
        plan = self._bouw_plan(ref_lat, ref_lon, koers, lengte, breedte, volgorde,
                               kant_sign, kopakker, eerste or 1.0, punt_b)
        plan["richting_bekend"] = eerste is not None
        return plan

    def spoor_vanaf(self, vanaf, max_punten=5000):
        """
        Het gereden spoor vanaf punt 'vanaf': de kaart vraagt alleen op wat hij
        nog niet heeft. Vraagt hij verder dan er is (er is intussen een nieuwe
        missie met een kort spoor), dan krijgt hij alles vanaf het begin.
        """
        spoor = self.spoor               # vaste verwijzing: start_mission() zet een nieuwe lijst neer
        if vanaf < 0 or vanaf > len(spoor):
            vanaf = 0
        return vanaf, spoor[vanaf:vanaf + max_punten]

    def _bouw_plan(self, ref_lat, ref_lon, koers, lengte, breedte, volgorde,
                   kant_sign, kopakker, eerste_sign, punt_b=None):
        """
        Het complete rijpad in GPS-coordinaten. Elke baan loopt van kopakker tot
        kopakker (net als _uitrij_along), en de bochten ertussen komen uit
        _bouw_bochtpad(): dezelfde functie die de robot tijdens het rijden
        gebruikt. In het echt begint een bocht een paar centimeter later, op
        het punt waar de robot het einde van de baan passeert.
        """
        def gps(along, cross):
            return self._frame_naar_latlon(along, cross, ref_lat, ref_lon, koers)

        banen, bochten = [], []
        sign = eerste_sign
        for pos, baan in enumerate(volgorde):
            cross = kant_sign * baan * breedte
            ingang = -kopakker if sign > 0 else lengte + kopakker
            uitgang = lengte + kopakker if sign > 0 else -kopakker
            banen.append({
                "baan": baan,
                "pad": [gps(ingang, cross), gps(uitgang, cross)],
                "koers": round((koers if sign > 0 else koers + 180.0) % 360.0, 1),
            })
            if pos + 1 < len(volgorde):
                volgende = volgorde[pos + 1]
                pad, _, _, soort = self._bouw_bochtpad(
                    uitgang, cross, kant_sign * volgende * breedte, sign
                )
                bochten.append({
                    "van": baan, "naar": volgende, "soort": soort,
                    "pad": [gps(a, c) for a, c in pad],
                })
                sign = -sign

        # Het gewas: van along 0 tot de baanlengte, over alle banen plus een
        # halve werkbreedte aan weerskanten.
        kruis = [kant_sign * b * breedte for b in set(volgorde)]
        links, rechts = min(kruis) - breedte / 2.0, max(kruis) + breedte / 2.0
        return {
            "koers": round(koers, 2),
            "baanlengte_m": round(lengte, 2),
            "werkbreedte_m": breedte,
            "kopakker_m": kopakker,
            "eerste_richting": "A->B" if eerste_sign > 0 else "B->A",
            "a": gps(0.0, 0.0),
            "b": [round(punt_b[0], 7), round(punt_b[1], 7)] if punt_b else None,
            "veld": [gps(0.0, links), gps(lengte, links), gps(lengte, rechts), gps(0.0, rechts)],
            "banen": banen,
            "bochten": bochten,
        }

    def _leg_spoor_vast(self, pos):
        """Het gereden spoor voor de kaart: een punt per spoor_stap_m, en altijd bij een wissel tussen baan en bocht."""
        if len(self.spoor) >= self.spoor_max_punten:
            return
        punt = [round(pos["lat"], 7), round(pos["lon"], 7), 1 if self.state == "TURNING" else 0]
        if self.spoor:
            vorig = self.spoor[-1]
            if (vorig[2] == punt[2]
                    and self._haversine(vorig[0], vorig[1], punt[0], punt[1]) < self.spoor_stap_m):
                return
        self.spoor.append(punt)

    # ------------------------------------------------------------------ #
    #  Hoofdlus
    # ------------------------------------------------------------------ #
    def _navigation_loop(self):
        try:
            self._run_loop()
        except Exception as e:
            # Zelfde vangnet als in navigator.py: een stil stervende thread zou
            # het voertuig op zijn laatste commando laten doorrijden.
            self.logger.exception(f"Onverwachte fout in de AB-navigatie: {e}")
            self.stop()
            self.status_message = f"Navigatiefout: {e}"
        finally:
            self.vehicle.stop()

    def _run_loop(self):
        epoch = -1
        vorige = time.time()

        while self.is_active:
            # Rekenen zodra er een nieuwe meting is (25 Hz). Komt er 0.1 s
            # niets, dan toch een rondje: de GnssBewaker zet hem dan stil.
            epoch = self.gps.wacht_op_epoch(epoch, timeout=0.1)
            nu = time.time()
            self._dt, vorige = nu - vorige, nu

            # Aandrijving in orde? CAN weg, een VESC-fout of een vastgelopen
            # wiel beeindigt de missie; opnieuw rijden gaat via een nieuwe start.
            fout = self.vehicle.drive_fault
            if fout:
                self.logger.error(f"AB-missie gestopt, aandrijving: {fout}")
                self.stop()
                self.status_message = f"Gestopt - aandrijving: {fout}"
                break
            # Geofence: vooruit zou hij een verboden gebied (sloot) in rijden.
            grens = self.vehicle.blokkade
            if grens:
                self.logger.error(f"AB-missie gestopt, {grens}")
                self.stop()
                self.status_message = f"Gestopt - {grens}"
                break

            curr_pos = self.gps.get_current_position()

            # Positie en heading goed genoeg? Zo niet: stilstaan, of langzaam
            # bij RTK float (instelbaar in navigation.gnss).
            gevraagd = self.turn_speed_kmh if self.state == "TURNING" else self.target_speed_kmh
            self.toegestaan_kmh, self.gnss_melding = self.bewaker.beoordeel(curr_pos, gevraagd)
            if self.toegestaan_kmh <= 0.0:
                self.vehicle.drive(0.0, 0.0)
                self.status_message = self.gnss_melding
                continue

            # Lijn afleiden bij eerste goede fix (alleen als A == B)
            if not self.line_initialized:
                self.ref_lat = curr_pos["lat"]
                self.ref_lon = curr_pos["lon"]
                self.base_bearing_deg = curr_pos["heading"]
                self.line_initialized = True
                self.plan_versie += 1
                self.logger.info(
                    f"Baanrichting afgeleid uit neus: {self.base_bearing_deg:.1f} graden."
                )

            # Rijrichting van de EERSTE baan uit de neus-richting: sta je bij B
            # in plaats van bij A, dan rijdt hij de lijn gewoon andersom af.
            if self.first_sign is None:
                self.first_sign = self._eerste_richting(curr_pos["heading"], self.base_bearing_deg)
                self.pass_sign = self.first_sign
                self.plan_versie += 1
                self.logger.info(
                    f"Eerste baan wordt gereden richting "
                    f"{'A->B' if self.first_sign > 0 else 'B->A'} "
                    f"(neus {curr_pos['heading']:.0f} graden)."
                )

            self._leg_spoor_vast(curr_pos)

            if self.state == "TRACKING":
                self._handle_tracking(curr_pos)
            elif self.state == "TURNING":
                self._handle_turning(curr_pos)
            # Rijdt hij met beperkingen (bv. RTK float), dan staat dat erbij.
            # Niet dubbel: na het afronden van een bocht is de melding nog die van vorige stap.
            if self.gnss_melding and self.is_active and not self.status_message.endswith(self.gnss_melding):
                self.status_message += f" | {self.gnss_melding}"

        # Stilzetten gebeurt in _navigation_loop(), ook na een fout.

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
                self.voltooid = True
                self.stop()
                self.status_message = "Missie klaar"
                return
            self._plan_turn(along)
            self.state = "TURNING"
            return

        # Van de baan af (zie max_cross_track_m): stoppen, niet doorrijden.
        if self.max_xte_m > 0.0:
            if abs(xte) <= 0.5 * self.max_xte_m:
                self._lijn_bereikt = True
            elif self._lijn_bereikt and abs(xte) > self.max_xte_m:
                self._stop_met_fout(
                    f"{abs(xte):.2f} m naast baan {self.current_swath} (max {self.max_xte_m:.2f} m): "
                    f"controleer het stuur en de voorwielen"
                )
                return

        # Rechte baan: de LijnRegelaar (Stanley of pure pursuit). Hij krijgt de
        # lijn in de RIJRICHTING: terug (B->A) is de koers 180 graden om en
        # ligt 'rechts' aan de andere kant.
        lijn_koers = (self.base_bearing_deg + (0.0 if sign > 0 else 180.0)) % 360.0
        self._oppakken_bijwerken(xte, self._norm180(lijn_koers - curr_pos["heading"]))
        steering = self.regelaar.stuur(
            curr_pos["heading"], lijn_koers, sign * xte, curr_pos.get("speed_kmh", 0.0),
            curr_pos.get("draaisnelheid_dps", 0.0), self.lookahead_m,
            lijn_id=(self.missie_nr, self.order_index), dt=self._dt,
            # Banen in dezelfde rijrichting beginnen met wat de vorige geleerd heeft.
            leer_id=(self.missie_nr, sign),
            # Tijdens het oppakken van de lijn staat de integrator stil.
            integreer=self._baan_opgepakt
        )
        target_bearing = lijn_koers

        self.vehicle.drive(self.toegestaan_kmh, steering, timeout_s=self.vehicle.nav_timeout_s)

        rest = sign * (uitrij_along - along)
        self.status_message = (
            f"Baan {self.current_swath} ({self.order_index + 1}/{len(self.swath_order)}) - "
            f"{'gewas' if self.in_werkzone else 'kopakker'}, nog {rest:.0f} m, "
            f"afwijking {xte:+.2f} m{'' if self._baan_opgepakt else ', lijn oppakken'}"
        )

        if self.drive_logger:
            self.drive_logger.log_regel(
                wp_idx=self.current_swath, modus=self.state,
                lat=curr_pos["lat"], lon=curr_pos["lon"],
                fix=curr_pos.get("fix", 0), hdop=curr_pos.get("hdop", 99.0),
                heading_echt=curr_pos["heading"], heading_doel=target_bearing,
                heading_fout=self._norm180(target_bearing - curr_pos["heading"]),
                stuurhoek=steering, doel_kmh=self.toegestaan_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dist_wp=rest, lookahead=self.lookahead_m, dt=self._dt,
                motor=self.vehicle.log_snapshot(),
                xte=xte, regelaar=self.regelaar.soort, gnss=curr_pos
            )

    def _stop_met_fout(self, reden):
        """Missie afbreken met een reden die in de webinterface blijft staan."""
        self.logger.error(f"AB-missie gestopt: {reden}")
        self.stop()
        self.status_message = f"Gestopt - {reden}"

    def _oppakken_bijwerken(self, xte, koersfout):
        """
        Houdt bij of de lijn van deze baan is opgepakt: binnen
        lane_capture_xte_m en lane_capture_heading_deg, of na de timeout.
        Eenmaal opgepakt blijft dat zo tot de volgende bocht.
        """
        if self._baan_opgepakt:
            return
        nu = time.time()
        if self._baan_start is None:
            self._baan_start = nu
        op_lijn = abs(xte) <= self.capture_xte_m and abs(koersfout) <= self.capture_heading_deg
        if self.capture_xte_m <= 0.0 or op_lijn or nu - self._baan_start > self.capture_timeout_s:
            self._baan_opgepakt = True

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
            self._baan_opgepakt, self._baan_start, self._lijn_bereikt = False, None, False
            self.state = "TRACKING"
            if timeout:
                self.logger.warning(
                    f"Bocht-timeout ({self.turn_timeout_s:.0f}s) -> baan "
                    f"{self.current_swath} wordt geforceerd opgepakt."
                )
            else:
                self.logger.info(f"Bocht klaar. Baan {self.current_swath} wordt opgepakt.")
            return

        # 2b. Te ver van het bochtpad: zelfde vangnet als op de baan.
        if self.max_turn_dev_m > 0.0 and beste_d > self.max_turn_dev_m:
            self._stop_met_fout(
                f"{beste_d:.2f} m van het bochtpad (max {self.max_turn_dev_m:.2f} m): "
                f"controleer het stuur en de voorwielen"
            )
            return

        if self.turn_controller == "pad":
            # 3a. Het pad zelf volgen: waar ligt de robot t.o.v. het stuk pad
            #     waar hij nu is, en welke bocht maakt het pad daar (en vlak
            #     daarna)? Zie LijnRegelaar.stuur_pad().
            i = min(self.turn_idx, len(self.turn_path) - 2)
            for _ in range(2):
                a0, c0 = self.turn_path[i]
                da, dc = self.turn_path[i + 1][0] - a0, self.turn_path[i + 1][1] - c0
                lengte2 = da * da + dc * dc
                t = ((along - a0) * da + (cross - c0) * dc) / lengte2
                if t >= 0.0 or i == 0:
                    break
                i -= 1                   # de robot ligt nog voor dit punt: het vorige stuk
            rechts = ((cross - c0) * da - (along - a0) * dc) / math.sqrt(lengte2)
            target_bearing = self._frame_bearing(da, dc)
            kmh = curr_pos.get("speed_kmh", 0.0)
            kromming = self.regelaar.kromming_vooruit(self.turn_kappa, self.turn_s, self.turn_idx, kmh)
            steering = self.regelaar.stuur_pad(heading, target_bearing, rechts, kromming, kmh,
                                               curr_pos.get("draaisnelheid_dps", 0.0))
            regelaar = "pad"
        else:
            # 3b. Carrot: het eerste padpunt op minstens 'turn_lookahead' meter.
            doel = self.turn_path[-1]
            for i in range(self.turn_idx, len(self.turn_path)):
                if self._pad_afstand(self.turn_path[i], along, cross) >= self.turn_lookahead_m:
                    doel = self.turn_path[i]
                    break

            target_bearing = self._frame_bearing(doel[0] - along, doel[1] - cross)
            steering = self.regelaar.pure_pursuit(target_bearing, heading, self.turn_lookahead_m)
            regelaar = "pure_pursuit"
        self.vehicle.drive(self.toegestaan_kmh, steering, timeout_s=self.vehicle.nav_timeout_s)

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
                heading_fout=rest_hoek, stuurhoek=steering, doel_kmh=self.toegestaan_kmh,
                echt_kmh=curr_pos.get("speed_kmh", 0.0),
                dist_wp=beste_d, lookahead=self.turn_lookahead_m, dt=self._dt,
                motor=self.vehicle.log_snapshot(),
                xte=beste_d, regelaar=regelaar, gnss=curr_pos
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
        # Kromming en booglengte per padpunt, voor de padregelaar. In het
        # baanframe is 'cross' naar rechts en 'along' vooruit.
        self.turn_kappa = pad_krommingen([p[1] for p in pad], [p[0] for p in pad],
                                         max_kromming=1.0 / self._min_radius())
        self.turn_s = [0.0]
        for (a0, c0), (a1, c1) in zip(pad, pad[1:]):
            self.turn_s.append(self.turn_s[-1] + math.hypot(a1 - a0, c1 - c0))

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

        if self.turn_shape == "bogen":
            punten, psi, soort = self._bogen_bocht(d, spiegel)
        else:
            basis, soort = self._vloeiende_bocht(d)
            punten = [(pu, spiegel * pv) for pu, pv in basis]
            psi = spiegel * 180.0
        u, v = punten[-1]

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

    def _bogen_bocht(self, d, spiegel):
        """
        De bocht als drie cirkelbogen met dezelfde straal (zie _bouw_bochtpad),
        zoals vroeger: navigation.turn_shape = "bogen". De stuurhoek springt
        daarbij op elke overgang in een keer om.
        """
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
        return punten, psi, soort

    def _vloeiende_bocht(self, d):
        """
        De bocht als pad dat de robot ECHT kan rijden: de kromming verandert
        geleidelijk in plaats van in sprongen (navigation.turn_shape = "vloeiend").

        Een stuurmotor heeft tijd nodig om van de ene uitslag naar de andere te
        komen. Bij drie cirkelbogen moet de stuurhoek op elke overgang in een
        keer om (bij een omega-bocht van vol links naar vol rechts): dat lukt
        niet, de robot raakt naast het pad, en omdat het pad al de scherpste
        bocht vraagt is er geen uitslag over om dat goed te maken (in de sim
        tot 75 cm ernaast, 7 cm scheef het gewas in). Hier loopt de kromming
        daarom met een vaste helling op en af, zo traag dat de stuurmotoren het
        op turn_rate_fraction van hun snelheid kunnen volgen bij de
        bochtsnelheid van nu, en blijft de scherpste bocht turn_radius_margin
        ruimer dan de draaicirkel: dan is er altijd uitslag over om bij te sturen.

        De opbouw is die van _bouw_bochtpad (uitwijken, de lus, rechtkomen), en
        omdat het krommingsverloop van voor naar achter hetzelfde is, eindigt
        ook deze bocht op dezelfde 'along' als waar hij begon. Hoe ruim de lus
        wordt (of hoe ver hij uitwijkt) wordt gezocht tot de zijsprong klopt.

        Geeft (punten in het voertuigframe voor een bocht naar RECHTS, soort).
        """
        kappa_max = 1.0 / (self._min_radius() * self.turn_radius_margin)
        v = max(0.3, self.turn_speed_kmh / 3.6)
        # Stuurhoek -> kromming is tan(hoek) / wielbasis; rond rechtuit is dat
        # het traagst (1 / wielbasis per radiaal), dus daarmee is het veilig.
        sigma = (math.radians(self.regelaar.stuursnelheid_dps * self.turn_rate_fraction)
                 / self.wheelbase / v)                      # 1/m per meter pad
        sleutel = (round(d, 3), round(kappa_max, 5), round(sigma, 4), self.turn_step_m)
        if sleutel in self._bocht_cache:
            return self._bocht_cache[sleutel]

        def rijd(alpha, kappa, stap=None):
            stukken = []
            for theta in (-alpha, math.pi + 2.0 * alpha, -alpha):
                stukken += self._overgangsboog(theta, kappa, sigma)
            return self._integreer(stukken, stap)

        if d >= rijd(0.0, kappa_max)[1]:
            # Ruimte genoeg: een U-bocht. Zoek de kromming waarmee hij precies
            # d opzij uitkomt (ruimer = verder opzij).
            laag, hoog = 1e-3, kappa_max
            for _ in range(40):
                mid = 0.5 * (laag + hoog)
                if rijd(0.0, mid)[1] > d:
                    laag = mid
                else:
                    hoog = mid
            alpha, kappa = 0.0, hoog
            soort = "halve cirkel"
        else:
            # Te krap: eerst uitwijken (omega). Verder uitwijken = minder opzij.
            laag, hoog = 0.0, math.radians(80.0)
            for _ in range(40):
                mid = 0.5 * (laag + hoog)
                if rijd(mid, kappa_max)[1] > d:
                    laag = mid
                else:
                    hoog = mid
            alpha, kappa = hoog, kappa_max
            soort = f"omega, uitwijkhoek {math.degrees(alpha):.0f} graden"

        resultaat = (rijd(alpha, kappa, self.turn_step_m)[2], soort)
        if len(self._bocht_cache) > 64:
            self._bocht_cache.clear()
        self._bocht_cache[sleutel] = resultaat
        return resultaat

    @staticmethod
    def _overgangsboog(theta, kappa, sigma):
        """
        Een bocht van theta radialen (+ = rechts) als stukken (lengte,
        kromming begin, kromming eind): oplopen met helling sigma tot kappa,
        vasthouden, en weer aflopen. Is de bocht te kort om kappa te halen,
        dan loopt hij op tot wat wel past en meteen weer af.
        """
        if abs(theta) < 1e-9:
            return []
        teken = 1.0 if theta > 0 else -1.0
        hoek = abs(theta)
        if kappa * kappa / sigma >= hoek:
            piek = math.sqrt(hoek * sigma)
            helling = piek / sigma
            return [(helling, 0.0, teken * piek), (helling, teken * piek, 0.0)]
        helling = kappa / sigma
        return [(helling, 0.0, teken * kappa),
                (hoek / kappa - helling, teken * kappa, teken * kappa),
                (helling, teken * kappa, 0.0)]

    @staticmethod
    def _integreer(stukken, stap=None):
        """
        Rijdt de stukken van _overgangsboog af vanaf (0, 0) met de neus langs
        u. Geeft (u, v, punten): de eindpositie, en met 'stap' de punten van
        het pad om de 'stap' meter (anders None).
        """
        ds = 0.01
        u, v, psi, s = 0.0, 0.0, 0.0, 0.0
        punten = [(0.0, 0.0)] if stap else None
        volgende = stap
        for lengte, k0, k1 in stukken:
            n = max(1, int(round(lengte / ds)))
            h = lengte / n
            for i in range(n):
                k = k0 + (k1 - k0) * (i + 0.5) / n
                midden = psi + 0.5 * k * h
                u += math.cos(midden) * h
                v += math.sin(midden) * h
                psi += k * h
                s += h
                if stap and s >= volgende - 1e-9:
                    punten.append((u, v))
                    volgende += stap
        if stap:
            # Het eindpunt hoort er precies in: daar begint de rechte aanloop.
            if math.hypot(u - punten[-1][0], v - punten[-1][1]) < 0.3 * stap and len(punten) > 1:
                punten[-1] = (u, v)
            else:
                punten.append((u, v))
        return u, v, punten

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

    def _eerste_richting(self, heading_deg, lijn_koers_deg):
        """Rijrichting van de eerste baan: +1 = A->B, -1 = B->A (neus meer dan 90 graden van de lijn af)."""
        return -1.0 if abs(self._norm180(heading_deg - lijn_koers_deg)) > 90.0 else 1.0

    def _frame_bearing(self, d_along, d_cross):
        """Kompaskoers naar een punt dat (d_along, d_cross) verderop ligt."""
        return (self.base_bearing_deg + math.degrees(math.atan2(d_cross, d_along))) % 360.0

    def _along_cross(self, lat, lon):
        """Projecteer (lat,lon) op het baanframe: langs- en rechts-afstand (m)."""
        north = R_EARTH * math.radians(lat - self.ref_lat)
        east = R_EARTH * math.radians(lon - self.ref_lon) * math.cos(math.radians(self.ref_lat))
        b = math.radians(self.base_bearing_deg)
        along = north * math.cos(b) + east * math.sin(b)
        right = -north * math.sin(b) + east * math.cos(b)
        return along, right

    @staticmethod
    def _frame_naar_latlon(along, cross, ref_lat, ref_lon, koers_deg):
        """Precies de omkering van _along_cross(): baanframe -> [lat, lon] (7 decimalen, ca. 1 cm)."""
        b = math.radians(koers_deg)
        north = along * math.cos(b) - cross * math.sin(b)
        east = along * math.sin(b) + cross * math.cos(b)
        lat = ref_lat + math.degrees(north / R_EARTH)
        lon = ref_lon + math.degrees(east / (R_EARTH * math.cos(math.radians(ref_lat))))
        return [round(lat, 7), round(lon, 7)]

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
