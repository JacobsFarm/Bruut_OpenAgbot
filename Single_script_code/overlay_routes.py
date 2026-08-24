"""
Overlay_ritten.py  -  alle gereden ritten over elkaar op een kaart.

Waarom dit script bestaat
-------------------------
Per rit maakt Extract_route_maps.py al een kaartje, maar daarmee zie je niet
wat je eigenlijk wilt weten: rijdt de robot elke keer OVER DEZELFDE lijn?
Dit script legt alle ritten uit data/logs in EEN interactieve HTML-kaart:

  - de geplande AB-banen uit data/ab_line.json als witte streepjeslijn
    (de lijn waar de robot op HOORT te rijden),
  - elke rit in een eigen kleur, in een eigen laag die je aan/uit klikt,
  - werkbanen (TRACKING) dik getekend, kopakkerbochten (TURNING) dun,
    zodat het beeld niet dichtslibt met 180-graden bochten,
  - hoverpunten met de afwijking van de geplande baan in centimeters,
  - een tabel met per rit en per baan de afwijking, en de SPREIDING tussen
    de ritten: het verschil tussen de rit die het meest links lag en de rit
    die het meest rechts lag. Die spreiding is het getal dat zegt hoe exact
    er over hetzelfde spoor wordt gereden.

De afwijking wordt gemeten in het lijnframe van de AB-lijn: elk GPS-punt
wordt omgerekend naar (langs de lijn, haaks op de lijn) en vergeleken met de
dichtstbijzijnde geplande baan. Positief is rechts van de baan gezien in de
richting A -> B, negatief is links.

    pip install folium

Draaien:  python Overlay_ritten.py
Uitvoer:  ritten_overlay.html naast dit script.
"""

import os
import csv
import json
import math
from datetime import datetime

try:
    import folium
except ImportError:
    folium = None

# ==========================================
# CONFIGURATIE
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
LOG_DIR = os.path.join(PROJECT_ROOT, "data", "logs")
AB_JSON = os.path.join(PROJECT_ROOT, "data", "ab_line.json")

OUTPUT_HTML = os.path.join(SCRIPT_DIR, "ritten_overlay.html")

VELDNAAM = None             # None = het eerste veld in ab_line.json
BESTAND_FILTER = "rit_"     # alleen logbestanden die hiermee beginnen
ALLEEN_DEZE_RITTEN = []     # bv ["rit_AB_Missie_20260824_154617.csv"]; leeg = alles
MAX_AFSTAND_VELD_M = 300.0  # rit verder dan dit van het veld -> ander perceel, overslaan

PUNT_STAP = 1               # 1 = alle punten tekenen, 2 = elk tweede punt, enz.
HOVER_STAP = 12             # elk zoveelste werkpunt krijgt een hoverbolletje
GAT_M = 5.0                 # sprong groter dan dit -> lijn onderbreken (GPS-gat)
TOON_BOCHTEN = True         # kopakkerbochten meetekenen (in dezelfde ritlaag)

# Dik getekend (het werkende deel van de rit):
WERK_MODI = ("TRACKING", "pure_pursuit")
# Dun getekend (kopakkerbochten):
BOCHT_MODI = ("TURNING",)
# Alleen deze modus wordt tegen de geplande AB-banen gemeten. Een waypoint-rit
# (pure_pursuit) volgt zijn eigen punten en heeft niets met de AB-banen te
# maken; die zou de afwijkingscijfers alleen maar vervuilen.
METEN_MODI = ("TRACKING",)

R_AARDE = 6371000.0

KLEUREN = ["#FF1744", "#00E676", "#2979FF", "#FFEA00", "#D500F9",
           "#FF9100", "#00E5FF", "#76FF03", "#F50057", "#FFFFFF"]


# ==========================================
# COORDINATEN (zelfde wiskunde als AB_mission_maker.py)
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


def latlon_naar_frame(lat, lon, ref_lat, ref_lon, koers_deg):
    """GPS -> lijnframe. Precies de omkering van frame_naar_latlon."""
    b = math.radians(koers_deg)
    noord = math.radians(lat - ref_lat) * R_AARDE
    oost = math.radians(lon - ref_lon) * R_AARDE * math.cos(math.radians(ref_lat))
    along = noord * math.cos(b) + oost * math.sin(b)
    cross = -noord * math.sin(b) + oost * math.cos(b)
    return along, cross


def percentiel(waarden, p):
    if not waarden:
        return 0.0
    s = sorted(waarden)
    idx = (len(s) - 1) * p / 100.0
    laag = int(idx)
    hoog = min(laag + 1, len(s) - 1)
    return s[laag] + (s[hoog] - s[laag]) * (idx - laag)


def gemiddelde(waarden):
    return sum(waarden) / len(waarden) if waarden else 0.0


# ==========================================
# HET VELD (geplande AB-banen)
# ==========================================
def lees_veld():
    """Leest data/ab_line.json en bouwt de geplande banen in het lijnframe."""
    if not os.path.exists(AB_JSON):
        print(f"! {AB_JSON} niet gevonden -> ritten worden getekend zonder")
        print("  geplande banen, dus zonder afwijkingscijfers.")
        return None

    with open(AB_JSON, "r", encoding="utf-8") as f:
        velden = json.load(f)
    if not velden:
        return None

    veld = velden[0]
    if VELDNAAM:
        for v in velden:
            if v.get("veldnaam") == VELDNAAM:
                veld = v
                break
        else:
            print(f"! veld '{VELDNAAM}' niet gevonden, ik gebruik "
                  f"'{veld.get('veldnaam')}'")

    lat_a, lon_a = veld["lat_a"], veld["lon_a"]
    lengte = veld.get("baanlengte_m") or haversine(lat_a, lon_a, veld["lat_b"], veld["lon_b"])
    koers = kompaskoers(lat_a, lon_a, veld["lat_b"], veld["lon_b"])
    kant_sign = -1.0 if str(veld.get("kant", "rechts")).lower().startswith("l") else 1.0
    breedte = float(veld.get("werkbreedte_m", 4.0))
    aantal = int(veld.get("aantal_banen", 1))

    banen = [(baan, kant_sign * baan * breedte) for baan in range(aantal)]

    return {
        "naam": veld.get("veldnaam", "veld"),
        "lat_a": lat_a, "lon_a": lon_a, "koers": koers,
        "lengte": lengte, "breedte": breedte,
        "banen": banen, "volgorde": veld.get("baan_volgorde", []),
    }


def dichtstbijzijnde_baan(cross, veld):
    """Welke geplande baan hoort bij deze cross-positie, en hoeveel scheelt het?"""
    beste, beste_dev = None, None
    for baan, baan_cross in veld["banen"]:
        dev = cross - baan_cross
        if beste_dev is None or abs(dev) < abs(beste_dev):
            beste, beste_dev = baan, dev
    if beste_dev is None or abs(beste_dev) > veld["breedte"] / 2.0:
        return None, beste_dev
    return beste, beste_dev


# ==========================================
# RITTEN INLEZEN
# ==========================================
def parse_tijd(tekst):
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            return datetime.strptime(tekst, fmt)
        except (ValueError, TypeError):
            continue
    return None


def rit_label(bestand):
    """rit_AB_Missie_20260824_154617.csv -> 'AB_Missie 24-08 15:46:17'."""
    kern = os.path.splitext(bestand)[0]
    if kern.startswith("rit_"):
        kern = kern[4:]
    delen = kern.split("_")
    if len(delen) >= 3 and len(delen[-1]) == 6 and len(delen[-2]) == 8:
        d, t = delen[-2], delen[-1]
        naam = "_".join(delen[:-2])
        return f"{naam} {d[6:8]}-{d[4:6]} {t[0:2]}:{t[2:4]}:{t[4:6]}"
    return kern


def lees_rit(pad, veld):
    """Leest een logbestand tot een lijst punten met modus en afwijking."""
    punten = []
    with open(pad, "r", encoding="utf-8", errors="replace") as f:
        for i, rij in enumerate(csv.DictReader(f)):
            if PUNT_STAP > 1 and i % PUNT_STAP:
                continue
            try:
                lat = float(rij["Lat"])
                lon = float(rij["Lon"])
            except (ValueError, KeyError, TypeError):
                continue
            if lat == 0.0 or lon == 0.0:
                continue

            modus = (rij.get("Modus") or "").strip()
            punt = {
                "lat": lat, "lon": lon, "modus": modus,
                "tijd": rij.get("Tijdstip", ""),
                "fix": rij.get("Fix", "?"),
                "kmh": rij.get("Echt_kmh", ""),
                "stuur": rij.get("Stuurhoek", ""),
                "baan": None, "dev": None,
            }
            if veld:
                along, cross = latlon_naar_frame(lat, lon, veld["lat_a"],
                                                 veld["lon_a"], veld["koers"])
                punt["along"], punt["cross"] = along, cross
                if modus in METEN_MODI:
                    punt["baan"], punt["dev"] = dichtstbijzijnde_baan(cross, veld)
            punten.append(punt)

    if not punten:
        return None

    afstand = 0.0
    for a, b in zip(punten, punten[1:]):
        afstand += haversine(a["lat"], a["lon"], b["lat"], b["lon"])

    t0, t1 = parse_tijd(punten[0]["tijd"]), parse_tijd(punten[-1]["tijd"])
    duur = (t1 - t0).total_seconds() if t0 and t1 and t1 >= t0 else 0.0

    return {
        "bestand": os.path.basename(pad),
        "label": rit_label(os.path.basename(pad)),
        "punten": punten,
        "afstand": afstand,
        "duur": duur,
    }


def zoek_ritten():
    if not os.path.isdir(LOG_DIR):
        print(f"! logmap niet gevonden: {LOG_DIR}")
        return []
    bestanden = sorted(b for b in os.listdir(LOG_DIR)
                       if b.lower().endswith(".csv") and b.startswith(BESTAND_FILTER))
    if ALLEEN_DEZE_RITTEN:
        bestanden = [b for b in bestanden if b in ALLEEN_DEZE_RITTEN]
    return [os.path.join(LOG_DIR, b) for b in bestanden]


def hoort_bij_veld(rit, veld):
    """Ligt deze rit op het veld van de AB-lijn, of op een heel ander perceel?"""
    if not veld:
        return True
    mid = rit["punten"][len(rit["punten"]) // 2]
    return haversine(mid["lat"], mid["lon"], veld["lat_a"], veld["lon_a"]) <= MAX_AFSTAND_VELD_M


# ==========================================
# SEGMENTEN (lijnstukken zonder gaten)
# ==========================================
def maak_segmenten(punten, modi):
    """Aaneengesloten stukken van de rit in de gevraagde modi, GPS-gaten geknipt."""
    segmenten, huidig, vorig = [], [], None
    for p in punten:
        if p["modus"] not in modi:
            if len(huidig) > 1:
                segmenten.append(huidig)
            huidig, vorig = [], None
            continue
        if vorig is not None and haversine(vorig["lat"], vorig["lon"],
                                           p["lat"], p["lon"]) > GAT_M:
            if len(huidig) > 1:
                segmenten.append(huidig)
            huidig = []
        huidig.append(p)
        vorig = p
    if len(huidig) > 1:
        segmenten.append(huidig)
    return segmenten


# ==========================================
# STATISTIEK
# ==========================================
def rit_statistiek(rit):
    """Afwijking van de geplande baan, voor de hele rit en per baan."""
    devs = [p["dev"] for p in rit["punten"] if p["dev"] is not None and p["baan"] is not None]
    per_baan = {}
    for p in rit["punten"]:
        if p["dev"] is None or p["baan"] is None:
            continue
        per_baan.setdefault(p["baan"], []).append(p["dev"])

    return {
        "n": len(devs),
        "gem_abs": gemiddelde([abs(d) for d in devs]),
        "p95_abs": percentiel([abs(d) for d in devs], 95),
        "max_abs": max((abs(d) for d in devs), default=0.0),
        "bias": gemiddelde(devs),
        "per_baan": {b: {"gem": gemiddelde(v), "max": max(abs(x) for x in v), "n": len(v)}
                     for b, v in per_baan.items()},
    }


def lege_statistiek():
    return {"n": 0, "gem_abs": 0.0, "p95_abs": 0.0, "max_abs": 0.0,
            "bias": 0.0, "per_baan": {}}


def stats_tabellen(ritten, veld):
    """Twee HTML-tabellen: per rit, en per baan met de spreiding tussen ritten."""
    kop = ("<table><tr><th>rit</th><th>punten</th><th>duur</th><th>afstand</th>"
           "<th>gem. afw.</th><th>p95</th><th>max</th><th>bias</th></tr>")
    rijen = []
    for rit in ritten:
        s = rit["stats"]
        leeg = "<td class='leeg'>-</td>"
        cijfers = (f"<td>{s['gem_abs'] * 100:.0f} cm</td>"
                   f"<td>{s['p95_abs'] * 100:.0f} cm</td>"
                   f"<td>{s['max_abs'] * 100:.0f} cm</td>"
                   f"<td>{s['bias'] * 100:+.0f} cm</td>") if s["n"] else leeg * 4
        rijen.append(
            f"<tr><td><span class='dot' style='background:{rit['kleur']}'></span>"
            f"{rit['label']}</td>"
            f"<td>{len(rit['punten'])}</td>"
            f"<td>{rit['duur'] / 60.0:.1f} min</td>"
            f"<td>{rit['afstand']:.0f} m</td>" + cijfers + "</tr>")
    tabel1 = kop + "".join(rijen) + "</table>"

    if not veld:
        return tabel1, ""

    # Per baan: waar lag elke rit gemiddeld, en hoe ver liggen de ritten uiteen?
    banen = sorted({b for rit in ritten for b in rit["stats"]["per_baan"]})
    if not banen:
        return tabel1, ""

    kop2 = "<tr><th>baan</th>" + "".join(
        f"<th><span class='dot' style='background:{r['kleur']}'></span></th>" for r in ritten
    ) + "<th>spreiding</th></tr>"
    rijen2, spreidingen = [], []
    for baan in banen:
        cellen, gemiddelden = [], []
        for rit in ritten:
            info = rit["stats"]["per_baan"].get(baan)
            if info:
                gemiddelden.append(info["gem"])
                cellen.append(f"<td>{info['gem'] * 100:+.0f}</td>")
            else:
                cellen.append("<td class='leeg'>-</td>")
        if len(gemiddelden) > 1:
            spreiding = max(gemiddelden) - min(gemiddelden)
            spreidingen.append(spreiding)
            kleur = ("#00E676" if spreiding < 0.10 else
                     "#FFEA00" if spreiding < 0.25 else "#FF1744")
            sp_cel = f"<td style='color:{kleur};font-weight:bold'>{spreiding * 100:.0f} cm</td>"
        else:
            sp_cel = "<td class='leeg'>-</td>"
        rijen2.append(f"<tr><td>baan {baan}</td>" + "".join(cellen) + sp_cel + "</tr>")

    slot = ""
    if spreidingen:
        slot = (f"<p class='slot'>Spreiding tussen de ritten: gemiddeld "
                f"<b>{gemiddelde(spreidingen) * 100:.0f} cm</b>, slechtste baan "
                f"<b>{max(spreidingen) * 100:.0f} cm</b>.</p>")

    tabel2 = ("<table>" + kop2 + "".join(rijen2) + "</table>"
              "<p class='uitleg'>Getallen in cm ten opzichte van de geplande baan: "
              "+ is rechts, - is links (kijkrichting A naar B). De spreiding is het "
              "verschil tussen de rit die het meest rechts lag en de rit die het "
              "meest links lag; dat is wat je merkt als je twee keer over hetzelfde "
              "gewas rijdt.</p>" + slot)
    return tabel1, tabel2


PANEEL_CSS = """
<style>
#ritpaneel {
  position: fixed; top: 10px; right: 10px; z-index: 9999;
  max-height: 88vh; width: 430px; overflow: auto;
  background: rgba(20,20,20,0.88); color: #eee; padding: 10px 14px;
  border-radius: 8px; font-family: system-ui, sans-serif; font-size: 12px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.6);
}
#ritpaneel h3 { margin: 0 0 6px 0; font-size: 14px; }
#ritpaneel table { border-collapse: collapse; width: 100%; margin-top: 4px; }
#ritpaneel th, #ritpaneel td { padding: 2px 5px; text-align: right;
  border-bottom: 1px solid rgba(255,255,255,0.12); white-space: nowrap; }
#ritpaneel th:first-child, #ritpaneel td:first-child { text-align: left; }
#ritpaneel td.leeg { color: #666; }
#ritpaneel .dot { display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; margin-right: 5px; border: 1px solid #000; }
#ritpaneel .uitleg, #ritpaneel .slot { color: #bbb; margin: 6px 0 0 0; line-height: 1.35; }
#ritpaneel summary { cursor: pointer; margin-top: 8px; }
</style>
"""


# ==========================================
# KAART
# ==========================================
def teken_kaart(ritten, veld):
    lats = [p["lat"] for rit in ritten for p in rit["punten"]]
    lons = [p["lon"] for rit in ritten for p in rit["punten"]]

    m = folium.Map(location=[gemiddelde(lats), gemiddelde(lons)],
                   zoom_start=18, max_zoom=22, tiles=None)
    # De laatst toegevoegde tegellaag staat aan: satelliet als eerste beeld.
    folium.TileLayer("OpenStreetMap", name="Wegenkaart", max_zoom=22).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satelliet", max_zoom=22).add_to(m)

    # --- geplande banen als referentie ---
    if veld:
        groep = folium.FeatureGroup(name="Geplande AB-banen", show=True)
        for baan, cross in veld["banen"]:
            p1 = frame_naar_latlon(0.0, cross, veld["lat_a"], veld["lon_a"], veld["koers"])
            p2 = frame_naar_latlon(veld["lengte"], cross, veld["lat_a"],
                                   veld["lon_a"], veld["koers"])
            # Donkere onderlijn, zodat de witte streepjes ook op een licht
            # luchtfoto of op de wegenkaart zichtbaar blijven.
            folium.PolyLine([p1, p2], color="#000000", weight=5,
                            opacity=0.35).add_to(groep)
            folium.PolyLine([p1, p2], color="#FFFFFF", weight=2, opacity=0.95,
                            dash_array="8,8",
                            tooltip=f"Geplande baan {baan}").add_to(groep)
        groep.add_to(m)

    # --- de ritten ---
    for rit in ritten:
        kleur = rit["kleur"]
        s = rit["stats"]
        titel = f"{rit['label']} ({s['gem_abs'] * 100:.0f} cm gem.)" if s["n"] else rit["label"]
        laag = folium.FeatureGroup(
            name=f"<span style='color:{kleur}'>&#9679;</span> {titel}", show=True)

        for segment in maak_segmenten(rit["punten"], WERK_MODI):
            banen = {p["baan"] for p in segment if p["baan"] is not None}
            baan_tekst = ("baan " + "/".join(str(b) for b in sorted(banen))
                          if banen else "werkbaan")
            folium.PolyLine([(p["lat"], p["lon"]) for p in segment],
                            color=kleur, weight=4, opacity=0.95,
                            tooltip=f"{rit['label']} - {baan_tekst}").add_to(laag)

        if TOON_BOCHTEN:
            for segment in maak_segmenten(rit["punten"], BOCHT_MODI):
                folium.PolyLine([(p["lat"], p["lon"]) for p in segment],
                                color=kleur, weight=2, opacity=0.45, dash_array="4,6",
                                tooltip=f"{rit['label']} - kopakkerbocht").add_to(laag)

        folium.CircleMarker(location=(rit["punten"][0]["lat"], rit["punten"][0]["lon"]),
                            radius=6, color="#000", weight=1, fill=True,
                            fill_color=kleur, fill_opacity=1.0,
                            tooltip=f"START {rit['label']}").add_to(laag)
        laag.add_to(m)

        # Hoverpunten met de afwijking; standaard uit, want het zijn er veel.
        if veld and s["n"]:
            punten_laag = folium.FeatureGroup(
                name=f"&nbsp;&nbsp;&#8627; afwijkingspunten {rit['label']}", show=False)
            werkpunten = [p for p in rit["punten"] if p["dev"] is not None and p["baan"] is not None]
            for p in werkpunten[::max(1, HOVER_STAP)]:
                dev_cm = p["dev"] * 100
                kleur_punt = ("#00E676" if abs(dev_cm) < 10 else
                              "#FFEA00" if abs(dev_cm) < 25 else "#FF1744")
                folium.CircleMarker(
                    location=(p["lat"], p["lon"]), radius=3, weight=0,
                    fill=True, fill_color=kleur_punt, fill_opacity=0.9,
                    tooltip=(f"<b>{rit['label']}</b><br>{p['tijd']}<br>"
                             f"baan {p['baan']} - afwijking <b>{dev_cm:+.0f} cm</b><br>"
                             f"{p['kmh']} km/h, stuurhoek {p['stuur']} gr, fix {p['fix']}")
                ).add_to(punten_laag)
            punten_laag.add_to(m)

    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    # Lagenmenu linksboven: rechtsboven staat de tabel met de cijfers.
    folium.LayerControl(collapsed=False, position="topleft").add_to(m)

    try:
        from folium.plugins import MeasureControl
        m.add_child(MeasureControl(primary_length_unit="meters"))
    except Exception:
        pass

    tabel1, tabel2 = stats_tabellen(ritten, veld)
    veldnaam = veld["naam"] if veld else "geen AB-lijn gevonden"
    paneel = (PANEEL_CSS + "<div id='ritpaneel'>"
              f"<h3>Ritten over elkaar &ndash; veld '{veldnaam}'</h3>"
              "<details open><summary><b>Per rit</b></summary>" + tabel1 + "</details>"
              + ("<details open><summary><b>Per baan: liggen de ritten op elkaar?"
                 "</b></summary>" + tabel2 + "</details>" if tabel2 else "")
              + "</div>")
    m.get_root().html.add_child(folium.Element(paneel))

    m.save(OUTPUT_HTML)
    print(f"\nKaart opgeslagen: {OUTPUT_HTML}")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("=" * 70)
    print(" RITTEN OVER ELKAAR LEGGEN")
    print("=" * 70)

    if folium is None:
        raise SystemExit("folium ontbreekt -> pip install folium")

    veld = lees_veld()
    if veld:
        print(f"Veld '{veld['naam']}': {len(veld['banen'])} banen van "
              f"{veld['lengte']:.1f} m, werkbreedte {veld['breedte']} m, "
              f"koers {veld['koers']:.1f} graden")

    ritten = []
    for pad in zoek_ritten():
        rit = lees_rit(pad, veld)
        if rit is None:
            print(f"  overgeslagen (geen geldige GPS): {os.path.basename(pad)}")
            continue
        if not hoort_bij_veld(rit, veld):
            print(f"  overgeslagen (ander perceel): {rit['bestand']}")
            continue
        rit["stats"] = rit_statistiek(rit) if veld else lege_statistiek()
        ritten.append(rit)
        s = rit["stats"]
        extra = (f", gem. afwijking {s['gem_abs'] * 100:.0f} cm over {s['n']} werkpunten"
                 if s["n"] else ", geen werkpunten op een geplande baan")
        print(f"  {rit['bestand']}: {len(rit['punten'])} punten, "
              f"{rit['afstand']:.0f} m, {rit['duur'] / 60.0:.1f} min" + extra)

    if not ritten:
        raise SystemExit("Geen bruikbare ritten gevonden in " + LOG_DIR)

    for i, rit in enumerate(ritten):
        rit["kleur"] = KLEUREN[i % len(KLEUREN)]

    teken_kaart(ritten, veld)
    print(f"{len(ritten)} ritten getekend. Open het bestand in je browser en klik "
          "de ritten aan/uit met het lagenmenu linksboven.")
