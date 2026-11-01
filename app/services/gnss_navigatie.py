"""
Gedeelde bouwstenen voor de navigators, gebouwd op wat de ZED-X20D levert:
een echte neus-heading (THS) en RTK-positie op 25 Hz, met de draaisnelheid,
de leeftijd van de data en de leeftijd van de RTK-correcties erbij.

  GnssBewaker     - mag er op deze meting gereden worden, en hoe hard?
  LijnRegelaar    - stuurhoek om een rechte lijn te volgen: Stanley (standaard)
                    of pure pursuit.

Alle hoeken in KOMPAS-graden (0 = noord, met de klok mee) en een positieve
stuurhoek is naar rechts, net als in de rest van het systeem.
"""
import math

R_EARTH = 6371000.0


def norm180(hoek):
    """Hoekverschil naar -180 .. +180 graden."""
    return (hoek + 180.0) % 360.0 - 180.0


def lijn_frame(lat, lon, ref_lat, ref_lon, koers_deg):
    """(lat, lon) in het frame van een lijn door ref met richting koers: (langs, rechts) in meters."""
    noord = R_EARTH * math.radians(lat - ref_lat)
    oost = R_EARTH * math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat))
    b = math.radians(koers_deg)
    return noord * math.cos(b) + oost * math.sin(b), -noord * math.sin(b) + oost * math.cos(b)


def peiling(lat1, lon1, lat2, lon2):
    """Kompasrichting van punt 1 naar punt 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    return math.degrees(math.atan2(y, x)) % 360.0


class GnssBewaker:
    """
    Beoordeelt per regelstap de GNSS-meting en geeft de toegestane snelheid.

    Positie en koers worden APART beoordeeld: de heading uit de twee
    antennes werkt ook zonder RTK-correcties, de centimeterpositie niet.

      - geen positie, geen fix, of de laatste meting ouder dan
        max_position_age_s (op 25 Hz hoort er elke 40 ms een te komen) -> stop
      - geen geldige heading -> stop
      - RTK fixed -> rijden
      - RTK float -> beleid 'rtk_float' (standaard langzaam)
      - DGPS / GPS / geschat -> beleid 'dgps' (standaard stop: een meter
        naast de lijn is in het gewas niet goed te maken)
      - RTK, maar de correcties zijn ouder dan max_correction_age_s -> als
        float behandelen: de ontvanger rekent dan nog even door op oude data
    Een beleid is "rijden", "langzaam" of "stop".
    """

    def __init__(self, config):
        c = config.get("navigation", {}).get("gnss", {})
        self.float_beleid = c.get("rtk_float", "langzaam")
        self.float_max_kmh = float(c.get("float_max_kmh", 1.0))
        self.dgps_beleid = c.get("dgps", "stop")
        self.dgps_max_kmh = float(c.get("dgps_max_kmh", 1.0))
        self.max_positie_leeftijd_s = float(c.get("max_position_age_s", 0.3))
        self.max_correctie_leeftijd_s = float(c.get("max_correction_age_s", 10.0))
        # Langzamer op ruwe grond (spreiding van de pitch over 1 s). Boven
        # start_deg gaat de snelheid lineair omlaag tot min_kmh bij vol_deg.
        # start_deg = 0 zet het uit.
        r = config.get("navigation", {}).get("ruwheid", {})
        self.ruw_start = float(r.get("start_deg", 0.0))
        self.ruw_vol = float(r.get("vol_deg", 2.0))
        self.ruw_min_kmh = float(r.get("min_kmh", 1.5))

    def beoordeel(self, pos, gevraagd_kmh):
        """Geeft (toegestane km/h, melding). 0 km/h = stilstaan; melding None = alles in orde."""
        kmh, melding = self._beoordeel_gnss(pos, gevraagd_kmh)
        if kmh > 0.0 and self.ruw_start > 0.0:
            ruw = pos.get("ruwheid_deg")
            if ruw is not None and ruw > self.ruw_start and kmh > self.ruw_min_kmh:
                deel = min(1.0, (ruw - self.ruw_start) / max(0.01, self.ruw_vol - self.ruw_start))
                kmh = kmh - (kmh - self.ruw_min_kmh) * deel
                ruw_melding = f"ruw veld ({ruw:.1f} graad) - {kmh:.1f} km/h"
                melding = f"{melding} | {ruw_melding}" if melding else ruw_melding
        return kmh, melding

    def _beoordeel_gnss(self, pos, gevraagd_kmh):
        if not pos or (pos.get("lat", 0.0) == 0.0 and pos.get("lon", 0.0) == 0.0):
            return 0.0, "Wacht op GNSS-positie"
        fix = pos.get("fix", 0)
        if fix == 0:
            return 0.0, "Geen GNSS-fix"
        leeftijd = pos.get("positie_leeftijd_s")
        if leeftijd is not None and leeftijd > self.max_positie_leeftijd_s:
            return 0.0, f"GNSS-positie {leeftijd:.2f} s oud (max {self.max_positie_leeftijd_s:.2f} s)"
        if not pos.get("heading_geldig", False):
            return 0.0, "Wacht op GNSS-heading (THS)"

        correctie = pos.get("correctie_leeftijd_s")
        if fix == 4 and (correctie is None or correctie <= self.max_correctie_leeftijd_s):
            return gevraagd_kmh, None
        if fix in (4, 5):
            reden = ("RTK float" if fix == 5
                     else f"RTK-correcties {correctie:.0f} s oud")
            return self._beleid(self.float_beleid, self.float_max_kmh, gevraagd_kmh, reden,
                                "navigation.gnss.rtk_float")
        soort = {1: "standaard GPS", 2: "DGPS", 6: "geschatte positie"}.get(fix, f"fix {fix}")
        return self._beleid(self.dgps_beleid, self.dgps_max_kmh, gevraagd_kmh,
                            f"geen RTK ({soort})", "navigation.gnss.dgps")

    @staticmethod
    def _beleid(beleid, max_kmh, gevraagd_kmh, reden, sleutel):
        if beleid == "rijden":
            return gevraagd_kmh, f"{reden} - rijdt door"
        if beleid == "langzaam":
            return min(gevraagd_kmh, max_kmh), f"{reden} - langzaam (max {max_kmh:.1f} km/h)"
        return 0.0, f"{reden} - stilstaan (instelling {sleutel})"


class LijnRegelaar:
    """
    Stuurhoek om een rechte lijn te volgen.

    STANLEY (standaard) stuurt op twee dingen tegelijk: de koersfout (neus
    t.o.v. de lijn) en de zijdelingse afwijking van de VOORAS, die met
    atan(k*e / (v_zacht + v)) wordt teruggestuurd. Daar komt een demping op
    de draaisnelheid bij. Dat werkt alleen met een betrouwbare neus-heading
    en draaisnelheid op hoge rate - precies wat de dubbele antenne geeft.
    Anders dan pure pursuit heeft hij geen vaste 'lookahead': hij trekt
    kaarsrecht op de lijn zonder de lijn af te snijden, ook op lage snelheid.

    PURE PURSUIT stuurt op een punt 'lookahead' meter verderop op de lijn.
    Robuust en vergevingsgezind, maar met een blijvende kleine afwijking en
    trager bij lage snelheid. Nog te kiezen via navigation.line_controller.

    Bij Stanley komt een INTEGRERENDE term: een helling (de robot glijdt
    zijwaarts weg) of een voorwiel dat net niet recht staat geeft anders een
    vaste afwijking van centimeters naast de lijn. Met RTK en een stabiele
    heading is die term veilig te gebruiken. Hij is begrensd, telt alleen
    dicht bij de lijn en tijdens het rijden, en begint per lijn opnieuw.
    In de simulatie (1.5 graad scheef stuur / 3 cm/s zijdrift) haalt dat de
    afwijking terug van 3.7 / 9.2 cm naar 1.5 / 2.3 cm RMS. Pure pursuit
    houdt bewust zijn oude gedrag (zonder integrator) als terugvaloptie.
    """

    def __init__(self, config, wielbasis, max_hoek):
        nav = config.get("navigation", {})
        self.soort = nav.get("line_controller", "stanley")
        st = nav.get("stanley", {})
        self.k = float(st.get("gain", 1.0))                 # 1/s: hoe hard de afwijking terugstuurt
        self.v_zacht = float(st.get("soft_speed_mps", 0.5))  # voorkomt overreactie bij lage snelheid
        self.k_koers = float(st.get("heading_gain", 1.0))
        self.k_draai = float(st.get("yaw_damping_s", 0.05))  # graden stuur per graad/s draaien
        self.k_i = float(nav.get("integral_gain", 4.0))     # graden stuur per meter.seconde afwijking
        self.i_max = float(nav.get("integral_max_deg", 6.0))
        self.i_zone = float(nav.get("integral_zone_m", 0.3))
        self.wielbasis = wielbasis
        self.max_hoek = max_hoek
        self._integraal = 0.0                                # graden stuur
        self._lijn = None

    def stuur(self, heading, lijn_koers, afwijking_m, snelheid_kmh, draaisnelheid_dps, lookahead_m,
              lijn_id=None, dt=0.04):
        """
        heading      - neus (graden)
        lijn_koers   - richting van de lijn in de rijrichting (graden)
        afwijking_m  - regelpunt (midden achteras) t.o.v. de lijn, + = rechts ervan
        lijn_id      - wisselt per baan / lijnstuk: dan begint de integrator opnieuw
        Geeft de stuurhoek van het virtuele midden van de vooras (graden, + = rechts).
        """
        if self.soort == "pure_pursuit":
            doel = lijn_koers + math.degrees(math.atan2(-afwijking_m, max(0.5, lookahead_m)))
            return self.pure_pursuit(doel, heading, lookahead_m)

        if lijn_id != self._lijn:
            self._lijn, self._integraal = lijn_id, 0.0
        v = max(0.0, snelheid_kmh / 3.6)
        # Integreren alleen als hij rijdt, dicht bij de lijn en ongeveer in de
        # goede richting; anders (oppakken van de lijn) zou hij oplopen.
        if v > 0.2 and abs(afwijking_m) < self.i_zone and abs(norm180(lijn_koers - heading)) < 20.0:
            self._integraal -= self.k_i * afwijking_m * min(dt, 0.2)
            self._integraal = max(-self.i_max, min(self.i_max, self._integraal))

        koersfout = norm180(lijn_koers - heading)          # + = lijn ligt rechts van de neus
        # Afwijking van de vooras: wijst de neus schuin weg, dan ligt de vooras
        # verder van de lijn dan de achteras.
        e_voor = afwijking_m + self.wielbasis * math.sin(math.radians(-koersfout))
        terug = math.degrees(math.atan2(-self.k * e_voor, self.v_zacht + v))
        hoek = self.k_koers * koersfout + terug - self.k_draai * draaisnelheid_dps + self._integraal
        return max(-self.max_hoek, min(self.max_hoek, hoek))

    def pure_pursuit(self, doel_peiling, heading, lookahead_m):
        """Stuurhoek naar een punt op 'lookahead_m' meter in richting doel_peiling."""
        alpha = math.radians(norm180(doel_peiling - heading))
        hoek = math.degrees(math.atan2(2.0 * self.wielbasis * math.sin(alpha), max(0.5, lookahead_m)))
        return max(-self.max_hoek, min(self.max_hoek, hoek))
