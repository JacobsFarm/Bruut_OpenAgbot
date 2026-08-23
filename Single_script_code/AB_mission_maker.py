"""
================================================================================
 AB-MISSIE MAKER  -  bouwt een complete AB-lijn missie uit twee punten
================================================================================

Je meet twee punten in het veld op met de RTK (bv. met RTK_Waypoint_Logger.py):

    PUNT A = de hoek LINKSONDER van het veld
    PUNT B = de hoek LINKSBOVEN van het veld

Samen vormen die de AB-lijn: de richting van de banen en meteen de baanlengte.
Vul daarnaast de werkbreedte en het aantal banen in en dit script rekent de
hele missie uit:

  * de werkvolgorde van de banen ('skip pass'): eerst 0, 2, 4, 6 - dus steeds
    een baan overslaan - en op de terugweg de gaten vullen 7, 5, 3, 1. Zo is de
    zijsprong bij bijna elke kopakkerbocht 2x de werkbreedte en past er gewoon
    een halve cirkel. Alleen op het keerpunt (6 -> 7) liggen twee banen naast
    elkaar; daar draait de robot een omega-bocht.
  * de kopakkerbochten met exact dezelfde wiskunde als de robot zelf gebruikt,
    zodat je vooraf ziet hoeveel kopakker je nodig hebt.
  * een preview als JPG en als interactieve satellietkaart (HTML).

De missie wordt weggeschreven naar data/ab_line.json. Kies daarna in de
webinterface (tab 'Landbouw') het veld en druk op start.

    pip install matplotlib folium
================================================================================
"""

import json
import math
import os

import matplotlib.pyplot as plt

try:
    import folium
except ImportError:
    folium = None

# ==========================================
# CONFIGURATIE PARAMETERS
# ==========================================
VELDNAAM = "test_field"

# Punt A = hoek LINKSONDER van het veld (hier start de missie)
LAT_A = 52.0000000000000
LON_A = 4.00000000000

# Punt B = hoek LINKSBOVEN van het veld (bepaalt richting EN baanlengte)
LAT_B = 52.0000000000000
LON_B = 4.000000100000

WERKBREEDTE_M = 4.0         # hart-op-hart afstand tussen twee banen
AANTAL_BANEN = 8            # aantal banen naast elkaar
BANEN_OVERSLAAN = 1         # 1 = steeds een baan overslaan (aanbevolen)
KANT = "rechts"             # aan welke kant van de AB-lijn ligt het veld

KOPAKKER_EXTRA_M = 2.0      # meters doorrijden voorbij het veld voor de bocht
WERKSNELHEID_KMH = 3.0
BOCHTSNELHEID_KMH = 2.0

# Laat op None staan om de baanlengte uit de afstand A->B te halen.
BAANLENGTE_M = None

OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "data", "ab_line.json")
OUTPUT_KAART = "ab_missie.jpg"          # veldschets in meters (langs/haaks op de lijn)
OUTPUT_GPS_KAART = "ab_missie_gps.jpg"  # zelfde missie, maar in lat/lon
OUTPUT_HTML = "ab_missie.html"          # interactieve satellietkaart

R_AARDE = 6371000.0


# ==========================================
# VOERTUIG (uit data/config.json, met terugval)
# ==========================================
def lees_voertuig():
    """
    Haalt wielbasis, spoorbreedte en de stuurlimiet uit de config van de robot,
    zodat de preview met dezelfde draaicirkel rekent als de machine zelf.
    """
    basis = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    for naam in ("config.json", "config.example.json"):
        pad = os.path.join(basis, naam)
        if os.path.exists(pad):
            with open(pad, "r") as f:
                cfg = json.load(f)
            wielbasis = cfg.get("vehicle", {}).get("wheelbase_m", 1.2)
            spoor = cfg.get("vehicle", {}).get("track_width_m", 1.0)
            wiel_max = cfg.get("steering", {}).get("max_angle_degrees", 30.0)
            print(f"Voertuiggegevens uit {naam}")
            return wielbasis, spoor, wiel_max
    print("Geen config gevonden, val terug op standaardwaarden.")
    return 1.2, 1.0, 30.0


def max_middenhoek(wielbasis, spoor, wiel_max):
    """
    Grootste stuurhoek van het virtuele midden van de vooras waarbij het
    binnenste voorwiel nog net binnen de wiellimiet blijft (Ackermann).
    Precies dezelfde afleiding als in VehicleController.
    """
    tangens = math.tan(math.radians(wiel_max))
    if tangens <= 1e-6:
        return wiel_max
    straal = wielbasis / tangens + (spoor / 2.0)
    return math.degrees(math.atan(wielbasis / straal))


# ==========================================
# HULPFUNCTIES VOOR COORDINATEN
# ==========================================
def haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return R_AARDE * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def kompaskoers(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def frame_naar_latlon(along, cross, ref_lat, ref_lon, koers_deg):
    """Lijnframe (langs de AB-lijn, haaks erop naar rechts) -> GPS."""
    b = math.radians(koers_deg)
    noord = along * math.cos(b) - cross * math.sin(b)
    oost = along * math.sin(b) + cross * math.cos(b)
    lat = ref_lat + math.degrees(noord / R_AARDE)
    lon = ref_lon + math.degrees(oost / (R_AARDE * math.cos(math.radians(ref_lat))))
    return lat, lon


# ==========================================
# MISSIE-OPBOUW
# ==========================================
def maak_baan_volgorde(aantal_banen, banen_overslaan=1):
    """
    Werkvolgorde van de banen. Identiek aan de functie in ab_navigator.py,
    zodat de preview exact laat zien wat de robot straks rijdt.
    """
    stap = max(1, int(banen_overslaan) + 1)
    volgorde = []
    for start in range(stap):
        laag = list(range(start, aantal_banen, stap))
        if start % 2 == 1:
            laag.reverse()
        volgorde.extend(laag)
    return volgorde


def bouw_bochtpad(exit_along, cross_van, cross_naar, sign, r_min, stap_m=0.25):
    """
    Kopakkerbocht in het lijnframe. Zelfde wiskunde als ABNavigator._bouw_bochtpad:
    drie bogen (-alpha, +180+2*alpha, -alpha) die netto 180 graden draaien en
    zijwaarts 2*R*(2*cos(alpha)-1) verschuiven, met verplaatsing vooruit = 0.
    Bij een ruime zijsprong valt alpha weg en blijft er een halve cirkel over.
    """
    d_rechts = sign * (cross_naar - cross_van)
    d = abs(d_rechts)
    spiegel = 1.0 if d_rechts >= 0 else -1.0

    if d >= 2.0 * r_min:
        radius, alpha, soort = d / 2.0, 0.0, "halve cirkel"
    else:
        radius = r_min
        cos_a = max(-1.0, min(1.0, (d + 2.0 * radius) / (4.0 * radius)))
        alpha = math.degrees(math.acos(cos_a))
        soort = f"omega ({alpha:.0f} gr uitwijken)"

    u, v, psi = 0.0, 0.0, 0.0
    punten = [(u, v)]
    for hoek, r in [(-alpha, radius), (180.0 + 2.0 * alpha, radius), (-alpha, radius)]:
        hoek = spiegel * hoek
        if abs(hoek) < 1e-6:
            continue
        stappen = max(1, int(math.radians(abs(hoek)) * r / stap_m))
        dpsi = hoek / stappen
        draai = 1.0 if dpsi > 0 else -1.0
        for _ in range(stappen):
            pr = math.radians(psi)
            cu = u - draai * r * math.sin(pr)
            cv = v + draai * r * math.cos(pr)
            psi += dpsi
            pr = math.radians(psi)
            u = cu + draai * r * math.sin(pr)
            v = cv - draai * r * math.cos(pr)
            punten.append((u, v))

    diepte = max(p[0] for p in punten)
    pad = [(exit_along + sign * pu, cross_van + sign * pv) for pu, pv in punten]
    return pad, diepte, soort


def bouw_missie(r_min):
    lengte = BAANLENGTE_M if BAANLENGTE_M else haversine(LAT_A, LON_A, LAT_B, LON_B)
    koers = kompaskoers(LAT_A, LON_A, LAT_B, LON_B)
    kant_sign = -1.0 if str(KANT).lower().startswith("l") else 1.0
    volgorde = maak_baan_volgorde(AANTAL_BANEN, BANEN_OVERSLAAN)

    print(f"\nAB-lijn: {lengte:.1f} m lang, koers {koers:.1f} graden "
          f"({'noord' if lengte else ''})")
    print(f"Werkvolgorde ({len(volgorde)} banen): {volgorde}")
    print(f"Minimale draaicirkel van de robot: R_min = {r_min:.2f} m "
          f"(halve cirkel verplaatst {2 * r_min:.2f} m zijwaarts)")

    # Bouw het complete spoor: baan, doorloop de kopakker op, bocht, volgende baan.
    spoor = []          # lijst van (along, cross) in het lijnframe
    banen = []          # per baan: (baannummer, start_along, eind_along, sign)
    bochten = []        # per bocht: (padpunten, soort, diepte, van, naar)
    sign = 1.0
    max_diepte_b, max_diepte_a = 0.0, 0.0

    for pos, baan in enumerate(volgorde):
        cross = kant_sign * baan * WERKBREEDTE_M
        start_along = -KOPAKKER_EXTRA_M if sign > 0 else lengte + KOPAKKER_EXTRA_M
        eind_along = lengte + KOPAKKER_EXTRA_M if sign > 0 else -KOPAKKER_EXTRA_M
        banen.append((baan, start_along, eind_along, sign))
        spoor.append((start_along, cross))
        spoor.append((eind_along, cross))

        if pos + 1 < len(volgorde):
            volgende = volgorde[pos + 1]
            pad, diepte, soort = bouw_bochtpad(
                eind_along, cross, kant_sign * volgende * WERKBREEDTE_M, sign, r_min
            )
            bochten.append((pad, soort, diepte, baan, volgende))
            spoor.extend(pad)
            if sign > 0:
                max_diepte_b = max(max_diepte_b, diepte)
            else:
                max_diepte_a = max(max_diepte_a, diepte)
            sign = -sign

    kop_b = KOPAKKER_EXTRA_M + max_diepte_b
    kop_a = KOPAKKER_EXTRA_M + max_diepte_a
    print(f"\nKopakker nodig: {kop_b:.1f} m voorbij punt B, {kop_a:.1f} m voor punt A.")

    soorten = {}
    for _, soort, _, _, _ in bochten:
        soorten[soort] = soorten.get(soort, 0) + 1
    for soort, n in soorten.items():
        print(f"  {n}x {soort}")

    werk_m = len(volgorde) * lengte
    bocht_m = sum(len(p) * 0.25 for p, _, _, _, _ in bochten)
    tijd_min = (werk_m / (WERKSNELHEID_KMH / 3.6) + bocht_m / (BOCHTSNELHEID_KMH / 3.6)) / 60.0
    print(f"\nOppervlakte: {len(volgorde) * lengte * WERKBREEDTE_M / 10000:.2f} ha")
    print(f"Rijafstand : {werk_m:.0f} m gewas + {bocht_m:.0f} m kopakker")
    print(f"Rijtijd    : ongeveer {tijd_min:.0f} minuten (exclusief stops)")

    return {
        "lengte": lengte, "koers": koers, "kant_sign": kant_sign,
        "volgorde": volgorde, "spoor": spoor, "banen": banen, "bochten": bochten,
        "kop_a": kop_a, "kop_b": kop_b,
    }


def bewaar_ab_lijn(missie):
    """Zet het veld in data/ab_line.json (vervangt een veld met dezelfde naam)."""
    pad = os.path.normpath(OUTPUT_JSON)
    lijnen = []
    if os.path.exists(pad):
        try:
            with open(pad, "r") as f:
                lijnen = json.load(f)
        except Exception:
            lijnen = []

    veld = {
        "veldnaam": VELDNAAM,
        "lat_a": LAT_A, "lon_a": LON_A,
        "lat_b": LAT_B, "lon_b": LON_B,
        "werkbreedte_m": WERKBREEDTE_M,
        "aantal_banen": AANTAL_BANEN,
        "banen_overslaan": BANEN_OVERSLAAN,
        "baanlengte_m": round(missie["lengte"], 3),
        "kopakker_extra_m": KOPAKKER_EXTRA_M,
        "kant": KANT,
        "werksnelheid_kmh": WERKSNELHEID_KMH,
        "bochtsnelheid_kmh": BOCHTSNELHEID_KMH,
        "baan_volgorde": missie["volgorde"],
    }

    lijnen = [l for l in lijnen if l.get("veldnaam") != VELDNAAM]
    lijnen.append(veld)

    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w") as f:
        json.dump(lijnen, f, indent=4)
    print(f"\nMissie opgeslagen in '{pad}' ({len(lijnen)} veld(en) in het bestand).")


# ==========================================
# PREVIEW
# ==========================================
def teken_kaart(missie, bestand):
    lengte, kant_sign = missie["lengte"], missie["kant_sign"]

    # Gelijke assen zijn hier verplicht: anders zie je niet of een bocht echt
    # past. Daarom passen we het formaat van de figuur aan de veldvorm aan.
    breedte_m = (AANTAL_BANEN + 1) * WERKBREEDTE_M
    hoogte_m = lengte + missie["kop_a"] + missie["kop_b"]
    schaal = min(11.0 / max(breedte_m, 1.0), 11.0 / max(hoogte_m, 1.0))
    fig, ax = plt.subplots(figsize=(max(4.0, breedte_m * schaal) + 1.5,
                                    max(4.0, hoogte_m * schaal) + 2.0))

    # Het gewas: elke baan als band ter breedte van de werkbreedte
    for baan in range(AANTAL_BANEN):
        c = kant_sign * baan * WERKBREEDTE_M
        ax.add_patch(plt.Rectangle(
            (c - WERKBREEDTE_M / 2, 0), WERKBREEDTE_M, lengte,
            facecolor="#c8e6c9", edgecolor="#a5d6a7", linewidth=0.5, zorder=1
        ))

    # De kopakkers
    for y0 in (-missie["kop_a"], lengte):
        hoogte = missie["kop_a"] if y0 < 0 else missie["kop_b"]
        ax.add_patch(plt.Rectangle(
            (-WERKBREEDTE_M, y0), (AANTAL_BANEN + 1) * WERKBREEDTE_M, hoogte,
            facecolor="#fff3e0", edgecolor="#ffcc80", linewidth=0.5, zorder=0
        ))

    # De banen in werkvolgorde
    for pos, (baan, start, eind, sign) in enumerate(missie["banen"]):
        c = kant_sign * baan * WERKBREEDTE_M
        ax.plot([c, c], [0, lengte], color="#1565c0", linewidth=2.5, zorder=3)
        ax.annotate(
            f"{pos + 1}", (c, lengte / 2), ha="center", va="center", fontsize=10,
            fontweight="bold", color="white", zorder=5,
            bbox=dict(boxstyle="circle,pad=0.3", facecolor="#1565c0", edgecolor="none")
        )
        # baannummer zoals het in baan_volgorde staat
        ax.annotate(
            f"baan {baan}", (c, lengte * 0.72), ha="center", va="center", fontsize=8,
            color="#0d47a1", rotation=90, zorder=5,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8,
                      edgecolor="none")
        )
        # pijl in de rijrichting
        ax.annotate("", xy=(c, lengte / 2 + sign * lengte * 0.09),
                    xytext=(c, lengte / 2 + sign * lengte * 0.03),
                    arrowprops=dict(arrowstyle="-|>", color="#0d47a1", lw=2), zorder=4)
        # het stuk kopakker dat hij doorrijdt
        ax.plot([c, c], sorted([0 if sign > 0 else lengte, eind]),
                color="#ef6c00", linewidth=1.8, linestyle=":", zorder=3)
        ax.plot([c, c], sorted([lengte if sign > 0 else 0, start]),
                color="#ef6c00", linewidth=1.8, linestyle=":", zorder=3)

    # De kopakkerbochten
    for pad, soort, diepte, van, naar in missie["bochten"]:
        kleur = "#d32f2f" if soort.startswith("omega") else "#ef6c00"
        ax.plot([p[1] for p in pad], [p[0] for p in pad],
                color=kleur, linewidth=1.8, zorder=4)

    ax.plot([], [], color="#ef6c00", lw=1.8, label="kopakkerbocht (halve cirkel)")
    ax.plot([], [], color="#d32f2f", lw=1.8, label="kopakkerbocht (omega)")
    ax.scatter([0], [0], c="#2e7d32", s=180, marker="o", edgecolors="black",
               zorder=6, label="A (linksonder)")
    ax.scatter([0], [lengte], c="#c62828", s=180, marker="s", edgecolors="black",
               zorder=6, label="B (linksboven)")

    ax.set_aspect("equal")
    ax.set_title(
        f"{VELDNAAM}: {AANTAL_BANEN} banen x {WERKBREEDTE_M} m, {lengte:.0f} m lang\n"
        f"volgorde {missie['volgorde']} - kopakker {missie['kop_a']:.1f} / "
        f"{missie['kop_b']:.1f} m",
        fontsize=12, fontweight="bold", pad=15
    )
    ax.set_xlabel("afstand haaks op de AB-lijn (m)")
    ax.set_ylabel("afstand langs de AB-lijn (m)")
    ax.grid(True, linestyle=":", alpha=0.5)
    # Legenda onder de grafiek: bij een lang smal veld zou hij anders punt B
    # of de eerste bocht afdekken.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2, fontsize=9,
              frameon=False)

    plt.tight_layout()
    plt.savefig(bestand, dpi=170, bbox_inches="tight")
    plt.close()
    print(f"Preview opgeslagen: '{bestand}'")


def teken_gps_kaart(missie, bestand):
    """
    Dezelfde missie, maar uitgezet in echte GPS-coordinaten - net als de kaart
    die RTK_points_maker.py maakt. Handig om naast een luchtfoto of een
    perceelsregistratie te leggen: je ziet meteen of de missie op het goede
    stuk land ligt en of de kopakkerbochten niet in de sloot uitkomen.
    """
    print("Statische GPS-plot aan het tekenen...")
    koers, lengte, kant_sign = missie["koers"], missie["lengte"], missie["kant_sign"]

    def naar_gps(punt):
        return frame_naar_latlon(punt[0], punt[1], LAT_A, LON_A, koers)

    spoor = [naar_gps(p) for p in missie["spoor"]]
    lats = [p[0] for p in spoor]
    lons = [p[1] for p in spoor]

    fig, ax = plt.subplots(figsize=(9, 9))

    # Het volledige rijpad: banen en kopakkerbochten aan elkaar
    ax.plot(lons, lats, color="#2196F3", linewidth=2, alpha=0.7, label="Rijpad robot")

    # De banen zelf dik erbovenop, met hun volgnummer
    for pos, (baan, start, eind, sign) in enumerate(missie["banen"]):
        c = kant_sign * baan * WERKBREEDTE_M
        p0, p1 = naar_gps((0.0, c)), naar_gps((lengte, c))
        ax.plot([p0[1], p1[1]], [p0[0], p1[0]], color="#1565c0", linewidth=2.5, zorder=3)
        mid = naar_gps((lengte / 2.0, c))
        ax.annotate(
            f"{pos + 1}", (mid[1], mid[0]), ha="center", va="center", fontsize=9,
            fontweight="bold", color="white", zorder=5,
            bbox=dict(boxstyle="circle,pad=0.3", facecolor="#1565c0", edgecolor="none")
        )

    # De kopakkerbochten in oranje/rood, zodat je ziet waar hij het veld uitsteekt
    for pad, soort, diepte, van, naar in missie["bochten"]:
        gps = [naar_gps(p) for p in pad]
        ax.plot([p[1] for p in gps], [p[0] for p in gps],
                color="#d32f2f" if soort.startswith("omega") else "#ef6c00",
                linewidth=2, zorder=4)

    a_gps, b_gps = naar_gps((0.0, 0.0)), naar_gps((lengte, 0.0))
    ax.scatter([a_gps[1]], [a_gps[0]], c="green", s=170, marker="o", edgecolors="black",
               zorder=6, label="A (linksonder)")
    ax.scatter([b_gps[1]], [b_gps[0]], c="red", s=170, marker="s", edgecolors="black",
               zorder=6, label="B (linksboven)")
    ax.plot([], [], color="#ef6c00", lw=2, label="kopakkerbocht (halve cirkel)")
    ax.plot([], [], color="#d32f2f", lw=2, label="kopakkerbocht (omega)")

    BUFFER_MARGE = 0.0002
    ax.set_xlim([min(lons) - BUFFER_MARGE, max(lons) + BUFFER_MARGE])
    ax.set_ylim([min(lats) - BUFFER_MARGE, max(lats) + BUFFER_MARGE])

    # Een graad lengte is op onze breedtegraad korter dan een graad breedte;
    # zonder deze correctie staat het veld scheefgetrokken op de plot.
    gem_lat = sum(lats) / len(lats)
    ax.set_aspect(1.0 / math.cos(math.radians(gem_lat)))

    ax.set_title(
        f"{VELDNAAM}: {AANTAL_BANEN} banen x {WERKBREEDTE_M} m, {lengte:.0f} m lang\n"
        f"volgorde {missie['volgorde']}",
        fontsize=12, fontweight="bold", pad=15
    )
    ax.set_xlabel("Lengtegraad (Lon)", fontsize=9)
    ax.set_ylabel("Breedtegraad (Lat)", fontsize=9)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    plt.savefig(bestand, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"GPS-kaart opgeslagen: '{os.path.basename(bestand)}'")


def teken_html(missie, bestand):
    if folium is None:
        print("folium niet geinstalleerd -> HTML-kaart overgeslagen (pip install folium)")
        return

    koers = missie["koers"]
    def naar_gps(punt):
        return frame_naar_latlon(punt[0], punt[1], LAT_A, LON_A, koers)

    spoor_gps = [naar_gps(p) for p in missie["spoor"]]
    lats = [p[0] for p in spoor_gps]
    lons = [p[1] for p in spoor_gps]

    m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)],
                   zoom_start=18, max_zoom=22, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satelliet", max_zoom=22
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Wegenkaart").add_to(m)

    kant_sign = missie["kant_sign"]
    for pos, (baan, start, eind, sign) in enumerate(missie["banen"]):
        c = kant_sign * baan * WERKBREEDTE_M
        folium.PolyLine(
            [naar_gps((0.0, c)), naar_gps((missie["lengte"], c))],
            color="#00E5FF", weight=5, opacity=0.9,
            tooltip=f"Baan {baan} - als {pos + 1}e gereden"
        ).add_to(m)

    for pad, soort, diepte, van, naar in missie["bochten"]:
        folium.PolyLine(
            [naar_gps(p) for p in pad],
            color="#FF6D00" if not soort.startswith("omega") else "#D50000",
            weight=3, opacity=0.9, tooltip=f"{soort}: baan {van} -> {naar}"
        ).add_to(m)

    for naam, punt, kleur in (("A (linksonder)", (0.0, 0.0), "green"),
                              ("B (linksboven)", (missie["lengte"], 0.0), "red")):
        p = naar_gps(punt)
        folium.CircleMarker(location=p, radius=8, color="black", weight=1, fill=True,
                            fill_color=kleur, fill_opacity=1.0,
                            tooltip=f"<b>{naam}</b><br>{p[0]:.7f}, {p[1]:.7f}").add_to(m)

    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    folium.LayerControl().add_to(m)
    m.save(bestand)
    print(f"Interactieve kaart opgeslagen: '{bestand}'")


if __name__ == "__main__":
    print("=" * 70)
    print(f" AB-MISSIE MAKER  -  veld '{VELDNAAM}'")
    print("=" * 70)

    wielbasis, spoor_breedte, wiel_max = lees_voertuig()
    midden_max = max_middenhoek(wielbasis, spoor_breedte, wiel_max)
    r_min = wielbasis / math.tan(math.radians(midden_max))
    print(f"Wielbasis {wielbasis} m, wiellimiet {wiel_max} gr -> "
          f"max middenhoek {midden_max:.1f} gr")

    if WERKBREEDTE_M * max(1, BANEN_OVERSLAAN + 1) < 2 * r_min:
        print(f"\nLET OP: met {BANEN_OVERSLAAN} baan/banen overslaan is de zijsprong "
              f"{WERKBREEDTE_M * (BANEN_OVERSLAAN + 1):.1f} m, minder dan de "
              f"{2 * r_min:.1f} m van een halve cirkel. De robot draait dan overal "
              f"een omega-bocht; overweeg BANEN_OVERSLAAN te verhogen.")

    missie = bouw_missie(r_min)
    bewaar_ab_lijn(missie)

    hier = os.path.dirname(os.path.abspath(__file__))
    teken_kaart(missie, os.path.join(hier, OUTPUT_KAART))
    teken_gps_kaart(missie, os.path.join(hier, OUTPUT_GPS_KAART))
    teken_html(missie, os.path.join(hier, OUTPUT_HTML))

    print("\nKlaar. Open de kaart om te controleren of de kopakkers passen,")
    print(f"kies daarna '{VELDNAAM}' in de webinterface bij 'Landbouw' en start.")
