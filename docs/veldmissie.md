# Veldmissie en geofence: een heel veld rijden zonder de sloot in te rijden

Status 2026-11-11: **ingebouwd** zijn de kaart met geofence (geldt altijd, ook handmatig), de missievolger met het
tabblad *Veldmissie*, snelheid per segment, wachten op vrijgave bij een oversteek, hervatten en de bulk-upload.
**Nog niet**: het werktuig echt schakelen (de missievolger meldt alleen of het omlaag hoort) en achteruit rijden in
een missie. Zie de lijst onderaan.

De simulator (`openagbot-fieldsim`, map `F:\sim_world`) plant een **veldmissie**: eerst een aantal rondjes langs
de rand (kopakker), dan het hart in rechte banen, met bochten die deze robot met zijn draaicirkel echt kan rijden,
en met per soort rand (sloot, weg, hek, gebouw) een eigen afstand. Hij levert drie bestanden:

| Bestand | Wat | Op de robot |
| --- | --- | --- |
| `kaart.json` | alle verboden gebieden van de boerderij: sloten en water met hun slootzone, wegen, dijken, gebouwen, verboden gebieden, nesten met hun periode; plus de velden en doorgangen om te tekenen | `data/kaart.json`, **geldt altijd** |
| `veldmissie.json` | de route als segmenten met soort, snelheid en werktuig omhoog/omlaag, plus het toegestane gebied van die missie | `data/missies/<naam>.json`, tabblad *Veldmissie* |
| `waypoints.json` | dezelfde route als losse waypoints, voor *RTK Navigatie* (pure pursuit van punt naar punt) | `data/waypoints.json` |

## Waar de gegevens staan

Alles staat als JSON in `data/` op de robot (staat in `.gitignore`: het zijn echte posities van je eigen land).

| Bestand | Geschreven door | Gelezen door |
| --- | --- | --- |
| `data/kaart.json` | `PUT /api/kaart` (sim: *Stuur*; tabblad Veldmissie: *Kaart laden*) | `GeofenceBewaker` bij het opstarten en na elke upload |
| `data/missies/<naam>.json` | `PUT /api/missies/<naam>` (sim: *Stuur*; tabblad: *Missie laden*) | `MissieVolger` bij de start, het tabblad voor de kaart |
| `data/missie_voortgang.json` | `MissieVolger`, elke 5 s en bij een stop | *Hervat* |
| `data/logs/rit_Veldmissie_*.csv` | `DriveLogger`, per rit | `Single_script_code/extract_ride_report.py` |

Een nieuwe kaart of missie wordt eerst gecontroleerd en dan pas in een keer over de oude heen gezet. Is
`data/kaart.json` onleesbaar (half geschreven, met de hand stukgemaakt), dan **rijdt de robot niet** tot er een
goede kaart staat of het bestand weg is: liever stilstaan dan zonder bewaking rijden. Zonder `kaart.json` is er
buiten een missie geen bewaking; het tabblad zegt dat dan.

## Geofence: geldt altijd (`app/services/geofence.py`)

De `GeofenceBewaker` rekent op het ritme van de GNSS (25 Hz) en is een **poort in de regellus van de
VehicleController**. Elke rijopdracht gaat daar doorheen, dus het maakt niet uit wie er rijdt: waypoints, AB-lijn,
veldmissie of de joystick van *Handmatig (RC)*.

1. De omtrek: de hoeken van de robot (spoorbreedte / 2 + 15 cm, 25 cm voor de vooras en achter de achteras) en de
   einden van het werktuig (`geofence.werktuig_halve_breedte_m`; tijdens een missie de halve werkbreedte).
2. Die omtrek wordt een **remweg vooruit en achteruit** gelegd langs de bocht die nu gestuurd wordt
   (`snelheid x 0,3 s + snelheid^2 / (2 x 1,5 m/s2)`, minstens 0,3 m). Bij 3 km/h is dat 0,5 m.
3. Komt een punt daar in een stop-gebied of buiten het werkgebied van de kaart, dan gaat **die richting dicht**: de
   wielen staan direct stil en een lopende missie eindigt met `Gestopt - geofence: sloot ...`. De andere richting
   blijft open, zodat je er met de hand weer uit rijdt.
4. Sta je er helemaal in (kaart klopt niet, robot erin gezet), dan zijn beide richtingen dicht. *Overbruggen*
   (knop in de rode balk, `POST /api/geofence/overbruggen`) geeft 60 s om er met de hand uit te rijden, hoogstens
   1,5 km/h. Een navigator starten zet de bewaking meteen weer aan.
5. Zonder RTK fixed komt er 1 m extra afstand bij. Zonder GNSS-positie kan er niet bewaakt worden: handmatig
   rijden blijft dan mogelijk (schuur), de navigators staan dan toch al stil. Reageert de bewaking zelf niet meer,
   dan is de poort dicht.

De slootzone (boerderij-instelling in de sim, standaard 2 m) zit al in de veelhoeken van `kaart.json`: de robot
stopt dus 2 m plus de remweg voor het water. `actie: "mijden"` (hek, gat in het veld) geeft alleen een
waarschuwing. Bij een doorgang (dam, brug) is de sloot over de breedte van de doorgang uit de veelhoek gesneden.

Tijdens een veldmissie komt het blok `geofence` van die missie erbij: `toegestaan` (binnen het veld blijven, met
`geofence.toegestaan_marge_m` = 0,3 m speling; telt zodra de robot er een keer helemaal in stond, want de aanloop
begint net buiten het veld) en `verboden` voor de datum van de missie.

Instellingen: blok `geofence` in `data/config.json`. Rekentijd in de sim: 0,15 ms per meting (pure Python, zonder
shapely: randen per veelhoek in banden van 2 m).

## Missievolger (`app/services/missie_volger.py`) en het tabblad Veldmissie

- Het pad is een polylijn met booglengte `s`. Voortgang = projectie van de robot op het pad, alleen vooruit en
  gezocht in een venster (1 m terug, 6 m vooruit), zodat een rondje vlak langs een eerder rondje niet verspringt.
- Rechte banen stuurt de `LijnRegelaar` (Stanley met integrator, als de AB-banen). Bochten, rondjes en overgangen
  gaan met pure pursuit op een punt `missie.lookahead_m` (1,5 m) verder **langs het pad**.
- Snelheid per segment, met op tijd afremmen voor een langzamer segment, voor een oversteek en voor het eind.
- Start kan binnen 30 m van het startpunt; de robot rijdt naar het pad en volgt het zodra hij er op 0,5 m is.
- Segment met `"bevestigen": true` (oversteek): stoppen aan het begin, status *wacht op vrijgave*, verder na de
  knop *Vrijgeven* (`POST /api/missie/vrijgeven`). In een `doorgang` stopt hij als hij verder dan
  `breedte / 2 - halve robotbreedte` naast de lijn komt.
- Stopt de missie (stopknop, storing, geofence, GNSS), dan staat de voortgang op schijf en gaat *Hervat* verder
  vanaf 2 m voor die plek.
- Een missie die de planner heeft afgekeurd (`veiligheid.ok` false of een segment met `"veilig": false`) start niet.
- `werktuig_omlaag` in `/api/missie/live` zegt of het werktuig nu omlaag hoort (segment `omlaag`, op het pad en
  rijdend). Daar kan een werktuigsturing op aangesloten worden.

Het tabblad toont de kaart (blauw = sloot met slootzone, rood = verboden, oranje = nest, groen = doorgang), de
missie (doorgetrokken = werken, gestreept = rijden met het werktuig omhoog, cyaan = nu bezig), het gereden spoor,
de robot met de omtrek die bewaakt wordt (rood als een richting dicht is) en de voortgang. Kaart en missie laad je
er ook uit een bestand. Een dichte geofence staat als rode balk op **elk** tabblad.

## API

```
GET    /api/kaart                      de kaart op de robot ({"status": "leeg"} als er geen is)
PUT    /api/kaart                      nieuwe kaart (openagbot.kaart): gecontroleerd, bewaard, geldt direct
DELETE /api/kaart
GET    /api/geofence                   toestand, reden, open richtingen, laatste stop, omtrek
POST   /api/geofence/overbruggen       {"seconden": 60}   DELETE = bewaking weer aan
GET    /api/missies                    missies op de robot, met de bewaarde voortgang
GET    /api/missies/<naam>             het missiebestand        PUT = neerzetten, DELETE = weghalen
POST   /api/missie/start               {"naam", "hervat": false, "max_kmh": null}
POST   /api/missie/stop                voortgang blijft bewaard
POST   /api/missie/vrijgeven           verder na een oversteek
POST   /api/missie/update              {"max_kmh", "lookahead_m"} tijdens het rijden
GET    /api/missie/live?spoor_vanaf=N  positie, missie, geofence en nieuw spoor (voor de kaart)
PUT    /api/waypoints                  alle waypoints in een verzoek
```

`/api/status` heeft er `missie_actief`, `missie_state`, `missie_message` en `geofence` bij.

## Formaat `kaart.json` (versie 1)

```jsonc
{
  "format": "openagbot.kaart", "versie": 1, "naam": "Boerderij", "gemaakt": "2026-11-11T13:04:01",
  "slootzone_m": 2.0,                               // zit al in de water-veelhoeken hieronder
  "werkgebied": [[lat, lon], ...],                  // daarbuiten rijdt de robot nooit (mag ontbreken)
  "verboden": [
    {"id": "sloot_ab12", "soort": "water", "naam": "Molensloot", "actie": "stoppen",
     "polygon": [[lat, lon], ...], "gaten": [[[lat, lon], ...]]},
    {"id": "nest_1", "soort": "nest", "naam": "kievit", "actie": "stoppen", "van": "03-15", "tot": "08-15",
     "polygon": [...]},                              // alleen in die periode (maand-dag)
    {"id": "hek_3", "soort": "hek", "naam": "hek", "actie": "mijden", "polygon": [...]}   // alleen waarschuwen
  ],
  "velden": [{"id": "weide", "naam": "Weide", "grens": [[lat, lon], ...]}],              // om te tekenen
  "doorgangen": [{"id": "dam_1", "naam": "Dam", "soort": "dam", "breedte_m": 4.0, "bevestigen": false,
                  "lijn": [[lat, lon], ...]}]                                            // om te tekenen
}
```

`soort`: `water`, `weg`, `dijk`, `gebouw`, `verboden`, `nest`, `hek`, `gat`. Coördinaten in ETRS89 lat/lon.

## Wat de waypoint-route niet kan

`waypoints.json` met `POST /api/nav/start_pure_pursuit` (Navigator) rijdt dezelfde route en valt nu ook onder de
geofence van de kaart, maar:

1. **Eén snelheid** voor alles: bochten gaan net zo hard als de banen (`target_speed_kmh`).
2. De Navigator volgt **lijnstuk voor lijnstuk** met de LijnRegelaar (Stanley). In een bocht van 1 m-stukjes loopt
   Stanley zonder vooruitkijken achter op de bocht (zie de metingen onderaan).
3. Een punt geldt als bereikt binnen `arrival_threshold_intermediate_m` (0,8 m) of als de loodlijn gepasseerd is.
   Bij punten die dichter dan 0,8 m bij elkaar liggen slaat hij er soms een over.
4. Geen hervatten, geen vrijgave bij een oversteek, geen toegestaan gebied van de missie.

## De aanpassingen, en wat er nog open staat

De punten uit het voorstel van 2026-11-10. **Gedaan** = zit in de code zoals hierboven beschreven; de tekst
eronder is het oorspronkelijke voorstel.

| Punt | Stand |
| --- | --- |
| 1. Bulk-upload | gedaan (`PUT /api/waypoints`, `PUT /api/missies/<naam>`, `PUT /api/kaart`) |
| 2. Rijden langs een pad | gedaan (`MissieVolger`); de kromming-voorsturing is niet nodig gebleken, pure pursuit op het pad volstaat |
| 3. Snelheid per segment | gedaan |
| 4. Werktuig omhoog/omlaag | **open**: `werktuig_omlaag` wordt gemeld, er is nog geen `WerktuigController`, voorloop of naloop |
| 5. Geofence | gedaan, en breder dan voorgesteld: ook zonder missie en bij handmatig rijden, uit `data/kaart.json` |
| 6. Hervatten | gedaan, zonder Dubins-aanloop: hervatten kan binnen 30 m van het hervatpunt |
| 7. Achteruit (K-bocht) | **open** |
| 8. Doorgangen | gedaan: snelheid per segment, breedtebewaking en wachten op vrijgave |

### 1. Bulk-upload van waypoints en missies

```
PUT  /api/waypoints            body: [{"way_point_name", "lat", "lon"}, ...]   vervangt alles in één keer
PUT  /api/veldmissie           body: veldmissie.json                          bewaart data/veldmissie.json
GET  /api/veldmissie
```

Klein, en maakt het sturen vanuit de sim (of een laptop in het veld) in één verzoek af.

### 2. Rijden langs een pad in plaats van van punt naar punt

Nieuwe klasse `PadVolger` (of uitbreiding van `Navigator`), gebruikt door de veldmissie:

- Het pad is één polylijn met booglengte `s`. Voortgang = projectie van de robot op het pad, alleen vooruit
  (zoeken in een venster rond de vorige `s`, zodat een rondje dat vlak langs een eerder rondje loopt niet
  verspringt).
- Sturen: pure pursuit met het doelpunt `lookahead` meter verder **langs het pad** (niet naar het volgende
  waypoint), plus een **kromming-voorsturing**: de sim levert bochten als Dubins-bogen, dus de kromming
  `k = 1/R` is bekend en de basis-stuurhoek is `atan(L * k)`. Stanley blijft op rechte stukken (zoals nu op de
  AB-banen); in bochten wint pure pursuit met voorsturing.
- Klaar = `s` binnen 0,3 m van het eind.
- Hergebruik `GnssBewaker`, `drive_fault`, `DriveLogger` zoals in `Navigator`; log extra kolommen `segment`,
  `segment_soort`, `s_m`, `werktuig`.

### 3. Snelheid per segment

Uit `veldmissie.json`: `snelheid_kmh` per segment (baan 3,0, bocht 2,0, rondje instelbaar). Afremmen **voor** de
bocht: de PadVolger kijkt `v^2 / (2 * decel_mps2)` meter vooruit en neemt de laagste snelheid van wat daar komt.
De VehicleController rampt al (`accel_mps2`, `decel_mps2`).

### 4. Werktuig omhoog/omlaag

`werktuig` per segment (`omlaag` = werken). Nodig:

- Een `WerktuigController` in `app/hardware/` met een simpele interface: `zet(omlaag: bool)`, `status()`. Eerste
  versie: een relais/GPIO (pomp, maaibalk aan) of de LA36 van de hefinrichting (zie aanbouwdelen
  `three point hitch`). In de sim: een emulator die de stand terugmeldt (de sim doet nu zelf 'auto omlaag in een
  veld').
- **Voorloop/naloop**: het werktuig zit niet op het regelpunt (midden achteras). Met `werktuig_offset_m`
  (vooruit +, achteruit -) en de reactietijd `werktuig_vertraging_s` schakelt de PadVolger op
  `s_wissel - offset - v * vertraging`. Zo begint de strook precies op de kopakkergrens.
- Bij een stop, GNSS-uitval of fout: werktuig omhoog/uit.

### 5. Geofence (de robot rijdt de sloot niet in)

Vanaf versie 2 heeft `veldmissie.json` een blok `geofence`:

- `toegestaan`: vlakken (met `gaten`) waarbinnen robot EN werktuig moeten blijven: het toegestane gebied van elk
  veld (al ingekort met de vrije ruimte langs sloot, weg en hek), de rijgebieden waar de route doorheen gaat en de
  vlakken van de gebruikte doorgangen.
- `verboden`: stop-gebieden binnen 30 m van de route, elk met `soort` (`water`, `weg`, `dijk`, `verboden`, `nest`,
  `gebouw`), `naam` en een veelhoek. Bij een doorgang is het stuk sloot, dijk of weg al uit de veelhoek gesneden.
- `halve_breedte_m`: halve breedte van robot of werktuig. `slootzone_m`: de verboden strook langs sloot en water
  (boerderij-instelling, standaard 2 m); die zit al in de `water`-veelhoeken van `verboden`.
- `datum`: de dag waarvoor de nesten gelden (een nest telt alleen in zijn periode).

Voorstel voor de robot, per GNSS-meting (25 Hz):

1. Reken de hoeken van robot en werktuig uit (regelpunt = midden achteras; de sim gebruikt de vier wielen plus
   15 cm en de einden van het werktuig).
2. Ligt een hoek buiten alle `toegestaan`-vlakken, of in een `verboden`-vlak: **stop**
   (dezelfde stop als `/api/stop`), werktuig omhoog, status "geofence: <soort> <naam>".
3. Verder rijden kan alleen handmatig, of na een nieuwe start van de missie.

Punt-in-veelhoek is genoeg: een missie heeft enkele tientallen veelhoeken met elk een paar honderd punten. Zonder
dit blok (versie 1) geldt de oude regel: stoppen zodra het regelpunt dichter dan `halve_breedte_m - 0,1` m bij
`veld.grens` komt.

De sim doet dit nu zelf (`missions/safety.py`): hij pauzeert en roept `/api/stop` aan. Zo is te zien wat de
robot met een stop midden in een missie doet, maar de bewaking hoort uiteindelijk in OpenAgbot.

### 6. Hervatten

Bewaar `segment` en `s` in `data/veldmissie_voortgang.json`. Na een stop (accu wisselen, storing) kan
`POST /api/nav/start_veldmissie {"hervat": true}` verder vanaf het laatste werkende segment, met een Dubins-aanloop
naar een punt een paar meter voor waar hij stopte (de sim kan die aanloop meeleveren of OpenAgbot rekent hem uit).

### 7. Later: achteruit (K-bocht)

De navigatie rijdt nooit achteruit (`max_erpm_reverse` geldt alleen handmatig). In smalle hoeken en bij
"kopakker overslaan" passen sommige bochten daardoor niet en kort de planner de banen in. Met achteruit kan een
K-bocht (Reeds-Shepp in plaats van Dubins) en blijft er minder liggen. Pas zinvol na punt 2.

### 8. Doorgangen en rijden tussen de velden

Een boerderijmissie (`"soort": "boerderij"`) rijdt meer velden achter elkaar. Tussen de velden komen twee nieuwe
segmenttypes, beide met het werktuig omhoog:

- `transport`: rijden over erf, pad of door een veld naar het volgende veld, op `snelheid_kmh`.
- `doorgang`: de rijlijn door een dam, duiker, brug, hek, oprit of oversteek, met `doorgang` (id) en een eigen,
  lagere `snelheid_kmh`. Het blok `doorgangen` geeft per id de soort, breedte, richting en `bevestigen`.

Voorstel:

- In een `doorgang`-segment de snelheid uit het segment aanhouden en de dwarsafwijking strenger bewaken: stoppen
  als die groter wordt dan `(breedte_m / 2) - halve_breedte_m`.
- Heeft het segment `"bevestigen": true` (oversteek over een weg): aan het begin van het segment stoppen, status
  "wacht op vrijgave" tonen en pas verder rijden na `POST /api/nav/vrijgeven` (knop in de webinterface). De sim
  rijdt daar nu nog doorheen, omdat de huidige navigator alleen waypoints kent.
- `niet_bereikbaar` noemt de velden die niet in de missie zitten en waarom (geen doorgang, doorgang te smal).

## Formaat `veldmissie.json` (versie 2)

Versie 2 voegt toe: `geofence`, `veiligheid` (uitkomst van de controle vooraf; een segment met `"veilig": false`
raakt een gevaar en hoort niet gereden te worden) en bij een boerderijmissie `soort`, `velden`, `volgorde`,
`doorgangen`, `niet_bereikbaar` en per segment `veld` of `doorgang`. Een lezer van versie 1 kan de rest negeren.

```jsonc
{
  "format": "openagbot.veldmissie", "versie": 2, "soort": "boerderij",
  "velden": [{"id": "weide", "naam": "Weide", "rondjes": 2, "koers_deg": 0.0, "bewerkt_m2": 44100.0}],
  "volgorde": ["weide", "zuidkavel"],
  "doorgangen": [{"id": "dam_weide", "naam": "Dam weide", "soort": "dam", "breedte_m": 4.0, "richting": "beide",
                  "max_snelheid_kmh": 2.0, "bevestigen": false, "lijn": [[lat, lon], ...]}],
  "geofence": {"toegestaan": [{"polygon": [[lat, lon], ...], "gaten": []}],
               "verboden": [{"id": "sloot_ab12cd34", "soort": "water", "naam": "sloot", "actie": "stoppen",
                             "polygon": [[lat, lon], ...]}],
               "halve_breedte_m": 1.5, "slootzone_m": 2.0, "datum": "2026-11-10"},
  "veiligheid": {"ok": true, "overtredingen": []},
  "niet_bereikbaar": [{"field": "perceel_7", "name": "...", "reason": "..."}],
  "segmenten": [
    {"nr": 0, "type": "transport", "label": "naar Weide", "werktuig": "omhoog", "snelheid_kmh": 3.0, "veld": "weide",
     "punten": [[lat, lon], ...], "koers_deg": [..]},
    {"nr": 1, "type": "doorgang", "label": "doorgang Dam weide", "werktuig": "omhoog", "snelheid_kmh": 2.0,
     "doorgang": "dam_weide", "punten": [...]},
    {"nr": 3, "type": "rondje", "label": "Weide: rondje 1", "werktuig": "omlaag", "veld": "weide", ...}
  ]
}
```

De velden van één veld (zonder `soort`) zijn die van versie 1 hieronder, plus `geofence` en `veiligheid`.

## Formaat `veldmissie.json` (versie 1)

```jsonc
{
  "format": "openagbot.veldmissie", "versie": 1, "gemaakt": "2026-11-10T03:30:00",
  "veld": {"id": "perceel_15", "naam": "Mais, snij- 15",
           "grens": [[lat, lon], ...]},          // toegestaan gebied (al ingekort), gesloten ring
  "robot": {"draaicirkel_m": 2.965, "regelpunt": "midden achteras", "halve_breedte_m": 1.5},
  "werkbreedte_m": 3.0, "overlap_m": 0.15,
  "kopakker": {"rondjes": 3, "volgorde": "eerst", "richting": "rechts"},
  "banen": {"koers_deg": 81.1, "vakken": [{"swaths": 18, "pattern": "overslaan_1"}]},
  "vrije_ruimte_m": {"water": 1.0, "weg": 1.0, "verhard": 0.3, "hek": 0.6, "gebouw": 1.5, "boom": 1.5},
  "segmenten": [
    {"nr": 0, "type": "rondje",   "label": "rondje 1", "werktuig": "omlaag", "snelheid_kmh": 3.0,
     "punten": [[lat, lon], ...], "koers_deg": [..]},
    {"nr": 1, "type": "overgang", "label": "naar rondje 2", "werktuig": "omlaag", ...},
    {"nr": 6, "type": "baan",     "label": "vak 1 baan 1", "werktuig": "omlaag", "snelheid_kmh": 3.0,
     "punten": [[lat_a, lon_a], [lat_b, lon_b]]},
    {"nr": 7, "type": "bocht",    "label": "vak 1 bocht 1", "werktuig": "omhoog", "snelheid_kmh": 2.0, ...}
  ],
  "cijfers": {"coverage_allowed_pct": 99.5, "time_min": 168, "length_m": 8100, ...},
  "waarschuwingen": []
}
```

- Segmenten sluiten op elkaar aan (eind van het ene = begin van het volgende), in rijvolgorde.
- `type`: `rondje` (kopakker), `baan` (recht, alleen begin en eind), `bocht` (tussen twee banen, Dubins),
  `overgang` (naar een volgend rondje, vak of de kopakker; bij een rondje naar het volgende rondje blijft het
  werktuig omlaag).
- `koers_deg`: kompaskoers per punt (0 = noord, met de klok mee), voor de kromming-voorsturing en de logging.
- Coördinaten in ETRS89 lat/lon, zelfde als de rest van OpenAgbot.

## Getest in de sim

`tools/drive_field_mission.py --test-field 40x30` in de sim, 2026-11-10: testveld 40 x 30 m met sloot en hek, 2
rondjes, werkbreedte 3 m, 3 km/h, 267 waypoints, de echte backend met `POST /api/nav/start_pure_pursuit`
(lookahead 2 m). Hele route gereden (573,7 van 574 m) in 12,8 min.

| Segment | Afwijking van het geplande pad: gemiddeld | 95 % | max |
| --- | --- | --- | --- |
| baan (recht) | 3 cm | 14 cm | 25 cm |
| bocht (Dubins) | 12 cm | 25 cm | 27 cm |
| overgang | 15 cm | 29 cm | 33 cm |
| rondje (kopakker) | 5 cm | 22 cm | 80 cm |

- De rechte banen gaan goed. In bochten en overgangen loopt hij 10-30 cm achter op het pad (punt 2 hierboven:
  pure pursuit langs het pad met kromming-voorsturing).
- De 80 cm zit in de hoeken van de rondjes: daar knikt de ring (binnenhoek) en de Navigator snijdt hem af. Gemeten
  1 % van de tijd stak robot of werktuig meer dan 15 cm buiten het toegestane gebied (zelfde hoeken). Met de
  PadVolger en de geofence (punt 2 en 5) moet dat weg; tot die tijd liever 0,2-0,3 m extra vrije ruimte langs
  sloot en hek instellen.
- Rendement op zo'n klein veld 75 % (veel bochten); op de echte percelen 80-97 %.
