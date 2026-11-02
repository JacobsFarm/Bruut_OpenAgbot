"""
Veldkaarten uit de ritlog van de AgBot: hoogte, helling en ruwheid.

Leest data/logs/rit_*.csv (de ritlog met Hoogte_Grond_m, Grond_Lat/Grond_Lon, Pitch_deg en
Ruwheid_deg). Oude terreinlogs (data/terrein/terrein_*.csv) kun je nog opgeven.

Maakt per run:
  <naam>_terrein.html  interactieve kaart op de luchtfoto: de ingekleurde
                       hoogte- en hellingkaart eroverheen, plus punten voor
                       hoogte, helling in de rijrichting (|pitch|) en ruwheid
  <naam>_terrein.png   dezelfde kaarten over de luchtfoto: hoogte met
                       hoogtelijnen, de echte helling uit die hoogtekaart
                       (richtingonafhankelijk, in %) en de ruwheid.
                       De luchtfoto-tegels (Esri World Imagery) worden
                       bewaard in data/kaarttegels, dan werkt het daarna
                       ook zonder internet.
en drukt een samenvatting af.

De HELLING op de kaart komt op twee manieren:
  - pitch: wat de dubbele antenne direct meet, maar alleen IN DE RIJRICHTING.
    Rijd je dwars over een helling, dan ziet de pitch hem niet.
  - uit de hoogtekaart: de echte steilheid in de steilste richting. Werkt
    beter naarmate er meer banen naast elkaar gereden zijn.

De hoogte komt alleen uit de RTK-hoogte (GGA, gecorrigeerd voor de
antennehoogte). Oudere ritlogs hebben die niet: dan rekent hij een RELATIEVE
hoogte terug uit de pitch (hoogte_uit_pitch), met de aansluiting tussen
naast elkaar liggende banen als ijking, en zet er overal 'geschat' bij. Dat
vraagt een rit met heen-en-terug banen en geeft geen hoogte boven zeeniveau.

Daarnaast schat hij de scheefstand van de antennemontage: rijd heen en
terug, dan keert een helling om en blijft de montage gelijk. Zet die
waarde bij gnss.pitch_offset_deg in de config (staat hij goed: ~0).

Gebruik (vanuit de hoofdmap van het project):
    python Single_script_code/extract_map_terrain.py             # nieuwste rit
        python Single_script_code/extract_map_terrain.py data/logs/rit_AB_Missie_20261101_*.csv
"""
import csv
import glob
import math
import os
import re
import sys

R = 6371000.0
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def getal(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def lees(pad):
    """Geeft een lijst punten {lat, lon, hoogte, pitch, ruwheid} uit een ritlog (of een oude terreinlog)."""
    with open(pad, encoding="utf-8", errors="ignore") as f:
        rijen = list(csv.DictReader(f))
    if not rijen:
        return []
    ritlog = "Lat" in rijen[0]
    punten = []
    for r in rijen:
        if ritlog:
            if r.get("Fix") != "4":
                continue
            # Hoogte_Grond_m hoort bij de grond onder de antenne (Grond_Lat/Lon), niet bij het regelpunt.
            p = {"lat": getal(r.get("Grond_Lat")) or getal(r.get("Lat")),
                 "lon": getal(r.get("Grond_Lon")) or getal(r.get("Lon")),
                 "hoogte": getal(r.get("Hoogte_Grond_m")), "pitch": getal(r.get("Pitch_deg")),
                 "ruwheid": getal(r.get("Ruwheid_deg")), "kmh": getal(r.get("Echt_kmh")),
                 "heading": getal(r.get("Heading_Echt"))}
        else:
            p = {"lat": getal(r.get("lat")), "lon": getal(r.get("lon")),
                 "hoogte": getal(r.get("hoogte_grond_m")), "pitch": getal(r.get("pitch_deg")),
                 "ruwheid": getal(r.get("ruwheid_deg")), "kmh": getal(r.get("kmh")),
                 "heading": getal(r.get("heading"))}
        if p["lat"] and p["lon"]:
            punten.append(p)
    if ritlog:
        punten = dun_uit(punten, 0.25)
    return punten


def xy(lat, lon, lat0, lon0):
    return (math.radians(lon - lon0) * R * math.cos(math.radians(lat0)), math.radians(lat - lat0) * R)


def dun_uit(punten, stap):
    """Ritlogs hebben 25 regels per seconde: houd er een per 'stap' meter over (zo'n 4 punten per meter)."""
    uit, vorige = [], None
    for p in punten:
        if vorige is None or math.hypot(*xy(p["lat"], p["lon"], vorige["lat"], vorige["lon"])) >= stap:
            uit.append(p)
            vorige = p
    return uit


def montage_schatting(punten):
    """
    Scheefstand van de antennemontage uit de pitch: een helling keert om als
    je de andere kant op rijdt, de montage niet. Per paar tegengestelde
    rijrichtingen (vakken van 45 graden) is het gemiddelde de montage.
    Geeft None als er niet in tegengestelde richtingen gereden is.
    """
    vakken = {}
    for p in punten:
        if p["pitch"] is not None and p["heading"] is not None and (p["kmh"] or 0) > 0.5:
            vakken.setdefault(int((p["heading"] % 360) // 45), []).append(p["pitch"])
    # Alleen het paar tegengestelde richtingen waarin het meest gereden is:
    # dat zijn de banen. Kopakkerbochten vallen in de andere vakken.
    paren = [(min(len(vakken[k]), len(vakken[k + 4])), k) for k in range(4)
             if len(vakken.get(k, [])) >= 30 and len(vakken.get(k + 4, [])) >= 30]
    if not paren:
        return None
    _, k = max(paren)
    gem = lambda v: sum(v) / len(v)
    return (gem(vakken[k]) + gem(vakken[k + 4])) / 2


def vul_aan(punten):
    """Montage-scheefstand van de pitch af; ontbrekende ruwheid uit de pitch rond elk punt."""
    montage = montage_schatting(punten)
    if montage is not None:
        print(f"  Montage-scheefstand antennes uit heen-en-terug rijden: {montage:+.2f} graad "
              f"(in de config: gnss.pitch_offset_deg plus deze waarde; staat hij goed, dan is dit ~0)")
        for p in punten:
            if p["pitch"] is not None:
                p["pitch"] -= montage
    if all(p["ruwheid"] is None for p in punten):
        # ~1 s rijden bij 3-4 km/h = ongeveer 1 m = 4 punten van 0.25 m
        for i, p in enumerate(punten):
            venster = [q["pitch"] for q in punten[max(0, i - 4):i + 1] if q["pitch"] is not None]
            if len(venster) >= 3:
                g = sum(venster) / len(venster)
                p["ruwheid"] = math.sqrt(sum((v - g) ** 2 for v in venster) / len(venster))


HOOGTE_GESCHAT = False      # True als de hoogte uit de pitch is teruggerekend (dan overal 'geschat' in de titels)


def hoogte_uit_pitch(punten, buur_m=5.0, ridge=1000.0, max_paren=20000):
    """
    Relatieve hoogte uit de pitch, voor ritlogs zonder RTK-hoogte (Hoogte_Grond_m).

    Per meter rijden is de hoogtewinst tan(pitch). Optellen langs de route
    loopt echter weg zodra de pitch een kleine vaste fout heeft (1 graad op
    100 m is 1,7 m). Daarom krijgt elk rechtstuk (koers binnen 30 graden) een
    eigen onbekende restfout, en wordt die zo gekozen dat naast elkaar
    liggende banen (binnen buur_m, iets meer dan de baanafstand) dezelfde hoogte krijgen. Heen en terug
    over dezelfde strook levert dus de ijking. De restfouten worden STERK naar
    een gemeenschappelijke waarde getrokken (ridge): de montagefout is in
    werkelijkheid een vaste waarde. Laat je elk stuk vrij (ridge ~ 3), dan is een
    vlak veld altijd een geldige oplossing en verdwijnt de helling in de
    rijrichting. Vanaf ridge ~ 300 is de uitkomst stabiel.

    Resultaat: p["hoogte"] in meter RELATIEF (nul = gemiddelde van het veld),
    geen hoogte boven zeeniveau. De helling in de rijrichting is goed; de
    helling dwars daarop wordt alleen via de aansluiting tussen de banen
    bepaald en is minder zeker. Zet HOOGTE_GESCHAT op True.
    """
    import numpy as np
    from scipy.spatial import cKDTree
    pp = [p for p in punten if p["pitch"] is not None]
    if len(pp) < 200:
        return False
    lat0 = sum(p["lat"] for p in pp) / len(pp)
    lon0 = sum(p["lon"] for p in pp) / len(pp)
    xy_ = np.array([xy(p["lat"], p["lon"], lat0, lon0) for p in pp])
    ds = np.r_[0.0, np.hypot(*np.diff(xy_, axis=0).T)]
    sprongen = int((ds > 2.0).sum())
    ds[ds > 2.0] = 0.0                       # gat in de log: niet meetellen
    s = np.cumsum(ds)
    seg = np.zeros(len(pp), dtype=int)
    k, ref = 0, pp[0]["heading"]
    for i, p in enumerate(pp):
        h = p["heading"]
        if h is not None and ref is not None and abs((h - ref + 180.0) % 360.0 - 180.0) > 30.0:
            k, ref = k + 1, h
        seg[i] = k
    nseg = k + 1
    G = np.cumsum(ds * np.tan(np.radians([p["pitch"] for p in pp])))
    een = np.zeros((len(pp), nseg))
    een[np.arange(len(pp)), seg] = ds
    A = np.cumsum(een, axis=0)               # meter gereden per rechtstuk tot elk punt

    paren = cKDTree(xy_).query_pairs(buur_m, output_type="ndarray")
    if len(paren) == 0:
        return False
    i, j = paren.T
    ok = (np.abs(seg[i] - seg[j]) >= 2) & (np.abs(s[i] - s[j]) > 10.0)
    i, j = i[ok], j[ok]
    if len(i) < 50:
        print("  Hoogte uit pitch niet mogelijk: te weinig banen die naast elkaar liggen.")
        return False
    if len(i) > max_paren:
        kies = np.random.default_rng(0).choice(len(i), max_paren, replace=False)
        i, j = i[kies], j[kies]
    M = np.zeros((len(i) + nseg, nseg + 1))
    v = np.zeros(len(i) + nseg)
    M[:len(i), :nseg] = A[i] - A[j]
    v[:len(i)] = G[i] - G[j]
    for r in range(nseg):                    # restfout van elk stuk ~ gemeenschappelijke waarde
        M[len(i) + r, r], M[len(i) + r, nseg] = ridge, -ridge
    b = np.linalg.lstsq(M, v, rcond=None)[0]
    rest = M[:len(i)] @ b - v[:len(i)]
    h = G - A @ b[:nseg]
    h -= h.mean()
    for p, hh in zip(pp, h):
        p["hoogte"] = float(hh)
    print(f"  Hoogte GESCHAT uit de pitch (relatief, nul = gemiddelde): {len(i)} buurparen van banen sluiten op "
          f"gemiddeld {np.sqrt(np.mean(rest ** 2)) * 100:.1f} cm na aan; gemeenschappelijke pitchfout "
          f"{math.degrees(b[nseg]):+.2f} graad." + (f" ({sprongen} gat(en) in de log overgeslagen)" if sprongen else ""))
    return True


def kwantiel(v, q):
    v = sorted(x for x in v if x is not None)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def samenvatting(punten):
    lat0 = sum(p["lat"] for p in punten) / len(punten)
    lon0 = sum(p["lon"] for p in punten) / len(punten)
    xs, ys = zip(*[xy(p["lat"], p["lon"], lat0, lon0) for p in punten])
    hoogte = [p["hoogte"] for p in punten if p["hoogte"] is not None]
    pitch = [abs(p["pitch"]) for p in punten if p["pitch"] is not None]
    ruw = [p["ruwheid"] for p in punten if p["ruwheid"] is not None]
    print(f"  {len(punten)} punten, gebied ca. {max(xs) - min(xs):.0f} x {max(ys) - min(ys):.0f} m")
    if hoogte:
        print(f"  hoogte van de grond{' (geschat, relatief)' if HOOGTE_GESCHAT else ''}: {min(hoogte):.2f} .. {max(hoogte):.2f} m "
              f"(verschil {max(hoogte) - min(hoogte):.2f} m)")
    if pitch:
        print(f"  helling in rijrichting |pitch|: mediaan {kwantiel(pitch, .5):.1f}, P90 {kwantiel(pitch, .9):.1f}, "
              f"max {max(pitch):.1f} graad ({math.tan(math.radians(max(pitch))) * 100:.0f} %)")
    if ruw:
        print(f"  ruwheid: mediaan {kwantiel(ruw, .5):.2f}, P90 {kwantiel(ruw, .9):.2f}, max {max(ruw):.2f} graad")
    return lat0, lon0


TEGEL_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
STRAAT_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
TEGEL_CACHE = os.path.join(PROJECT_ROOT, "data", "kaarttegels")


def _tegel_xy(lat, lon, z):
    """WGS84 -> (fractionele) tegelcoordinaten in Web Mercator."""
    n = 2 ** z
    return (lon + 180.0) / 360.0 * n, (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n


def _tegel_latlon(tx, ty, z):
    n = 2 ** z
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n)))), tx / n * 360.0 - 180.0


def satelliet(lat_z, lat_n, lon_w, lon_o, max_zoom=19):
    """
    Luchtfoto (Esri World Imagery) van het gebied, als (beeld, (lat_z, lat_n, lon_w, lon_o)).
    De tegels worden bewaard in data/kaarttegels, zodat het daarna ook offline
    werkt. Geeft None als er geen internet is en de tegels niet in de cache staan.
    """
    import numpy as np
    from PIL import Image
    try:
        import requests
    except ImportError:
        requests = None

    z = max_zoom
    while True:
        x0, y0 = _tegel_xy(lat_n, lon_w, z)
        x1, y1 = _tegel_xy(lat_z, lon_o, z)
        if (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1) <= 80 or z <= 14:
            break
        z -= 1
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    os.makedirs(TEGEL_CACHE, exist_ok=True)
    mozaiek = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            pad = os.path.join(TEGEL_CACHE, f"{z}_{tx}_{ty}.jpg")
            if not os.path.exists(pad):
                if requests is None:
                    return None
                try:
                    r = requests.get(TEGEL_URL.format(z=z, x=tx, y=ty), timeout=10,
                                     headers={"User-Agent": "BruutAgbot-terreinkaart/1.0"})
                    r.raise_for_status()
                    with open(pad, "wb") as f:
                        f.write(r.content)
                except Exception as e:
                    print(f"  Geen luchtfoto ({e}); kaart zonder achtergrond.")
                    return None
            mozaiek.paste(Image.open(pad).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    # Bijsnijden op het gebied (hele pixels) en de echte randen terugrekenen.
    px0, py0 = int((x0 - tx0) * 256), int((y0 - ty0) * 256)
    px1, py1 = int((x1 - tx0) * 256) + 1, int((y1 - ty0) * 256) + 1
    beeld = np.asarray(mozaiek.crop((px0, py0, px1, py1)))
    lat_n2, lon_w2 = _tegel_latlon(tx0 + px0 / 256.0, ty0 + py0 / 256.0, z)
    lat_z2, lon_o2 = _tegel_latlon(tx0 + px1 / 256.0, ty0 + py1 / 256.0, z)
    return beeld, (lat_z2, lat_n2, lon_w2, lon_o2)


def bereken_raster(punten, lat0, lon0, cel=0.5):
    """Hoogte en echte helling (%) op een raster van 'cel' meter, alleen tot 2 m van gereden punten."""
    import numpy as np
    met_h = [p for p in punten if p["hoogte"] is not None]
    if len(met_h) < 10:
        return None
    try:
        from scipy.interpolate import griddata
        from scipy.spatial import cKDTree
    except ImportError:
        return None
    x = np.array([xy(p["lat"], p["lon"], lat0, lon0)[0] for p in met_h])
    y = np.array([xy(p["lat"], p["lon"], lat0, lon0)[1] for p in met_h])
    h = np.array([p["hoogte"] for p in met_h])
    gx, gy = np.meshgrid(np.arange(x.min(), x.max() + cel, cel), np.arange(y.min(), y.max() + cel, cel))
    raster = griddata((x, y), h, (gx, gy), method="linear")
    afstand, _ = cKDTree(np.c_[x, y]).query(np.c_[gx.ravel(), gy.ravel()])
    raster[afstand.reshape(gx.shape) > 2.0] = np.nan
    gladde = raster
    if HOOGTE_GESCHAT:
        # Teruggerekende hoogte heeft een paar cm sprong tussen banen van ~4 m; zonder
        # uitsmeren leest de gradient dat als dwarshelling van enkele procenten.
        from scipy.ndimage import gaussian_filter
        geldig = np.isfinite(raster)
        sigma = 4.0 / cel
        teller = gaussian_filter(np.where(geldig, raster, 0.0), sigma)
        noemer = gaussian_filter(geldig.astype(float), sigma)
        gladde = np.where(geldig, teller / np.maximum(noemer, 1e-6), np.nan)
    dy, dx = np.gradient(gladde, cel)
    helling = np.hypot(dx, dy) * 100.0
    return {"gx": gx, "gy": gy, "hoogte": raster, "helling": helling}


def _meters_naar_latlon(xm, ym, lat0, lon0):
    return (lat0 + math.degrees(ym / R), lon0 + math.degrees(xm / (R * math.cos(math.radians(lat0)))))


def html_kaart(punten, lat0, lon0, rast, uit_pad):
    import numpy as np
    import folium
    import branca.colormap as cm
    import matplotlib
    m = folium.Map(location=[lat0, lon0], zoom_start=19, max_zoom=22, tiles=None)
    folium.TileLayer(tiles=TEGEL_URL, attr="Esri World Imagery", name="Satelliet",
                     max_zoom=22, max_native_zoom=19).add_to(m)
    # Niet OpenStreetMap: de OSM-servers blokkeren aanvragen van scripts (403).
    folium.TileLayer(tiles=STRAAT_URL, attr="Esri World Street Map", name="Kaart",
                     max_zoom=22, max_native_zoom=19, show=False).add_to(m)

    # Ingekleurd raster (hoogte en echte helling) over de luchtfoto heen.
    if rast is not None:
        lat_z, lon_w = _meters_naar_latlon(rast["gx"].min(), rast["gy"].min(), lat0, lon0)
        lat_n, lon_o = _meters_naar_latlon(rast["gx"].max(), rast["gy"].max(), lat0, lon0)
        for naam, veld, kaart, zichtbaar in ((("Hoogtekaart (geschat uit pitch)" if HOOGTE_GESCHAT else "Hoogtekaart"), "hoogte", "terrain", True),
                                             ("Hellingkaart (%)", "helling", "RdYlGn_r", False)):
            v = rast[veld]
            lo, hi = np.nanpercentile(v, 2), np.nanpercentile(v, 98)
            norm = np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)
            rgba = (matplotlib.colormaps[kaart](np.nan_to_num(norm)) * 255).astype(np.uint8)
            rgba[..., 3] = np.where(np.isfinite(v), 170, 0)
            folium.raster_layers.ImageOverlay(image=rgba[::-1], bounds=[[lat_z, lon_w], [lat_n, lon_o]],
                                              name=naam, show=zichtbaar).add_to(m)

    def laag(naam, sleutel, kleuren, absoluut=False, eenheid="", zichtbaar=False):
        waarden = [abs(p[sleutel]) if absoluut else p[sleutel] for p in punten if p[sleutel] is not None]
        if not waarden:
            return
        lo, hi = kwantiel(waarden, 0.02), kwantiel(waarden, 0.98)
        if hi <= lo:
            hi = lo + 1e-3
        schaal = cm.LinearColormap(kleuren, vmin=lo, vmax=hi, caption=f"{naam} {eenheid}")
        groep = folium.FeatureGroup(name=naam, show=zichtbaar)
        for p in punten:
            v = p[sleutel]
            if v is None:
                continue
            v = abs(v) if absoluut else v
            folium.CircleMarker([p["lat"], p["lon"]], radius=3, weight=0, fill=True, fill_opacity=0.85,
                                fill_color=schaal(min(max(v, lo), hi)),
                                tooltip=f"{naam}: {v:.2f} {eenheid}").add_to(groep)
        groep.add_to(m)
        schaal.add_to(m)

    heeft_hoogte = any(p["hoogte"] is not None for p in punten)
    laag("Hoogte geschat (punten)" if HOOGTE_GESCHAT else "Hoogte (punten)", "hoogte", ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"],
         eenheid="m", zichtbaar=rast is None and heeft_hoogte)
    laag("Helling rijrichting", "pitch", ["#1a9641", "#ffffbf", "#d7191c"], absoluut=True,
         eenheid="graad", zichtbaar=not heeft_hoogte)
    laag("Ruwheid", "ruwheid", ["#1a9641", "#ffffbf", "#d7191c"], eenheid="graad")
    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[min(p["lat"] for p in punten), min(p["lon"] for p in punten)],
                  [max(p["lat"] for p in punten), max(p["lon"] for p in punten)]])
    m.save(uit_pad)


def png_kaart(punten, lat0, lon0, rast, titel, uit_pad):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    alle_x = [xy(p["lat"], p["lon"], lat0, lon0)[0] for p in punten]
    alle_y = [xy(p["lat"], p["lon"], lat0, lon0)[1] for p in punten]
    marge = 4.0
    xmin, xmax = min(alle_x) - marge, max(alle_x) + marge
    ymin, ymax = min(alle_y) - marge, max(alle_y) + marge

    # Luchtfoto als achtergrond onder alle drie de panelen.
    lat_z, lon_w = _meters_naar_latlon(xmin, ymin, lat0, lon0)
    lat_n, lon_o = _meters_naar_latlon(xmax, ymax, lat0, lon0)
    foto = satelliet(lat_z, lat_n, lon_w, lon_o)
    if foto is not None:
        beeld, (fz, fn, fw, fo) = foto
        fx0, fy0 = xy(fz, fw, lat0, lon0)
        fx1, fy1 = xy(fn, fo, lat0, lon0)

    # Breed veld: panelen onder elkaar, anders naast elkaar.
    if (xmax - xmin) > 1.6 * (ymax - ymin):
        paneel_h = max(3.0, 13.0 * (ymax - ymin) / (xmax - xmin) + 1.0)
        fig, assen = plt.subplots(3, 1, figsize=(15, 3 * paneel_h + 1))
    else:
        fig, assen = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(titel + ("  (luchtfoto: Esri World Imagery)" if foto is not None else ""))

    for ax in assen:
        if foto is not None:
            ax.imshow(beeld, extent=(fx0, fx1, fy0, fy1), origin="upper", zorder=0)
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal")
        ax.set_xlabel("oost (m)")
        ax.set_ylabel("noord (m)")

    def punten_laag(ax, sleutel, cmap, label, absoluut=False):
        pp = [p for p in punten if p[sleutel] is not None]
        if not pp:
            return
        waarden = [abs(p[sleutel]) if absoluut else p[sleutel] for p in pp]
        sc = ax.scatter([xy(p["lat"], p["lon"], lat0, lon0)[0] for p in pp],
                        [xy(p["lat"], p["lon"], lat0, lon0)[1] for p in pp],
                        c=waarden, s=9, cmap=cmap, edgecolors="none", zorder=2,
                        vmin=kwantiel(waarden, 0.02), vmax=kwantiel(waarden, 0.98))
        fig.colorbar(sc, ax=ax, label=label, shrink=0.9)

    # 1. Hoogte: ingekleurd raster met hoogtelijnen, half doorzichtig over de foto.
    ax = assen[0]
    if rast is not None:
        vlak = ax.contourf(rast["gx"], rast["gy"], rast["hoogte"], levels=20, cmap="terrain", alpha=0.6, zorder=1)
        lijnen = ax.contour(rast["gx"], rast["gy"], rast["hoogte"], levels=10, colors="k", linewidths=0.6, zorder=2)
        ax.clabel(lijnen, fmt="%.2f", fontsize=7)
        fig.colorbar(vlak, ax=ax, label="hoogte (m)", shrink=0.9)
        ax.set_title(("Hoogte, GESCHAT uit de pitch (relatief, 0 = gemiddelde) met hoogtelijnen" if HOOGTE_GESCHAT
                      else "Hoogte van de grond (RTK) met hoogtelijnen"))
    elif any(p["hoogte"] is not None for p in punten):
        punten_laag(ax, "hoogte", "terrain", "hoogte (m)")
        ax.set_title("Hoogte, GESCHAT uit de pitch (relatief)" if HOOGTE_GESCHAT else "Hoogte van de grond (RTK)")
    else:
        ax.plot(alle_x, alle_y, "w.", ms=1, alpha=0.6, zorder=2)
        ax.set_title("Hoogte: niet in deze log (wel in nieuwere ritlogs) - wit = gereden pad")

    # 2. Helling: echte helling uit de hoogtekaart, anders de pitch in de rijrichting.
    ax = assen[1]
    if rast is not None and np.isfinite(rast["helling"]).sum() > 20:
        hh = rast["helling"]
        vlak = ax.contourf(rast["gx"], rast["gy"], np.clip(hh, 0, np.nanpercentile(hh, 98)),
                           levels=15, cmap="RdYlGn_r", alpha=0.6, zorder=1)
        fig.colorbar(vlak, ax=ax, label="helling (%)", shrink=0.9)
        ax.set_title("Helling uit de hoogtekaart (steilste richting)" + (", uitgesmeerd over ~4 m" if HOOGTE_GESCHAT else ""))
    else:
        punten_laag(ax, "pitch", "RdYlGn_r", "|pitch| (graad)", absoluut=True)
        ax.set_title("Helling in de rijrichting (pitch)")

    # 3. Ruwheid
    ax = assen[2]
    punten_laag(ax, "ruwheid", "RdYlGn_r", "ruwheid (graad)")
    ax.set_title("Ruwheid (spreiding pitch over ~1 s)")

    fig.tight_layout()
    fig.savefig(uit_pad, dpi=150)
    plt.close(fig)


def main():
    paden = sys.argv[1:]
    if not paden:
        # Zonder argumenten: de nieuwste ritlog.
        ritten = sorted(glob.glob(os.path.join(PROJECT_ROOT, "data", "logs", "rit_*.csv")),
                        key=lambda f: (re.search(r"\d{8}_\d{6}", f) or [""])[0])
        paden = ritten[-1:]
        if paden:
            print(f"Nieuwste ritlog: {os.path.basename(paden[0])}")
    paden = [p for g in paden for p in (sorted(glob.glob(g)) or [g])]
    if not paden:
        print("Geen ritlogs gevonden in data/logs/. Rij eerst een missie met de app.")
        return
    punten = []
    for pad in paden:
        stuk = lees(pad)
        print(f"{pad}: {len(stuk)} punten")
        punten += stuk
    if len(punten) < 10:
        print("Te weinig punten met RTK fixed voor een kaart.")
        return
    vul_aan(punten)
    global HOOGTE_GESCHAT
    if not any(p["hoogte"] is not None for p in punten) and len(paden) == 1:
        HOOGTE_GESCHAT = hoogte_uit_pitch(punten)
    naam = os.path.splitext(paden[0])[0] if len(paden) == 1 else os.path.join(os.path.dirname(paden[0]), "samen")
    print("\nSamenvatting:")
    lat0, lon0 = samenvatting(punten)
    rast = bereken_raster(punten, lat0, lon0)
    png_kaart(punten, lat0, lon0, rast, os.path.basename(naam), naam + "_terrein.png")
    print(f"\nPlaatje: {naam}_terrein.png")
    try:
        html_kaart(punten, lat0, lon0, rast, naam + "_terrein.html")
        print(f"Kaart:   {naam}_terrein.html")
    except ImportError as e:
        print(f"Geen interactieve kaart ({e}); installeer folium.")


if __name__ == "__main__":
    main()
