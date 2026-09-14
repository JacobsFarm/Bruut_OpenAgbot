# Aandrijving: twee VESC's op CAN

De twee hubmotoren achterop lopen sinds september 2026 op twee **VESC Classic
100V** controllers in plaats van op de Quinder DC-controller (art. 10301059).
De Jetson praat er rechtstreeks mee over **CAN**. De Arduino is daarmee uit het
aandrijfpad verdwenen; hij stuurt alleen nog de twee stappenmotoren van de
voorwielen.

| | |
|---|---|
| Motor | Quinder 8" 48V 550W · art. 10101025 |
| Controller | VESC Classic 100V, twee stuks |
| Vervangt | Quinder DC-controller 10301059 + Arduino/MCP4728-DAC |
| Aansturing | Jetson · CAN 500 kbit/s · 2 × VESC |

Bron van alle getallen hieronder: `CD-Quinder HUB motor specifications 2024-1`,
de VESC Classic 100V datasheet, en eigen metingen aan de stock-controller en de
EGO-accu (12 sep 2026).

---

## Waarom weg van de DAC

De oude keten was: Python → USB-serieel → Arduino → MCP4728 → een spanning van
0,77–3,4 V op de gashendel-ingang van de Quinder-controller. Die keten kon drie
dingen niet:

* **Terugmelden.** Er kwam geen enkel getal terug. Snelheid was een spanning
  waarvan we aannamen dat er een snelheid uit kwam.
* **Achteruit en remmen.** De gashendel-ingang kent alleen vooruit.
* **Beveiligen.** Zonder stroom- en toerentalmeting is stall-detectie onmogelijk.

Met de VESC's is snelheid een gevraagde eRPM die de controller zelf vasthoudt,
komt er op 50 Hz telemetrie terug (toerental, stroom, temperatuur, accuspanning,
tacho) en zijn achteruit en remmen gewone commando's.

---

## Bus en adressering

```
Jetson ──CAN──┬── VESC links  (ID 0)
              └── VESC rechts (ID 1)     500 kbit/s
```

Waarom beide controllers rechtstreeks aan de bus, en niet UART naar de ene en
CAN doorlussen naar de andere: bij doorlussen wordt de eerste VESC een single
point of failure voor het rechterwiel, en moet je telemetrie van de tweede gaan
pollen. USB is alleen voor de werkbank (VESC Tool) — in het veld her-enumereert
die bij elke spanningsdip.

### Wat je online vindt: de F1TENTH-driver

Zoek je op "VESC ROS", dan kom je uit bij de [F1TENTH vesc-repo](https://github.com/f1tenth/vesc)
en bij adviezen om gewoon een USB- of UART-kabel te trekken. Dat klopt — voor
een F1TENTH-auto. Die heeft **één** VESC en een stuurservo, en `vesc_ackermann`
vertaalt precies dat: één motorsnelheid plus één servostand.

Bruut is een ander voertuig: **twee** aangedreven wielen die onafhankelijk moeten
kunnen draaien, plus twee stuurstappenmotoren op een Arduino. Daarmee vervalt
zowel `vesc_ackermann` (verkeerde voertuigvorm) als de USB-aanname (`vesc_driver`
praat met één seriële poort per node, dus twee VESC's is twee kabels en twee
`/dev/ttyACM*`-nummers die bij elke boot kunnen wisselen).

Gaat dit project later naar ROS 2, dan is `vesc_msgs` een nuttige referentie voor
de berichtvorm, maar de aansturing hoort dan op `ros2_socketcan` te zitten — niet
op de seriële driver.

### App Settings per controller (VESC Tool)

| Parameter | Links | Rechts | Waarom |
|---|---|---|---|
| VESC ID | 0 | 1 | Moet uniek zijn; het is de onderste byte van elk CAN-adres |
| CAN Baud Rate | 500k | 500k | Ruim genoeg voor twee knopen op 50 Hz, robuust over lengte |
| CAN Status Message Mode | 1 – 5 | 1 – 5 | Levert eRPM, stroom, duty, temperaturen, tacho en `v_in` zonder pollen |
| CAN Status Rate | 50 Hz | 50 Hz | 20 ms per meting; snel genoeg voor stall- en runaway-detectie |
| Multiple VESCs Over CAN | uit | uit | Die functie spiegelt één gascommando naar alle VESC's — aan betekent: niet kunnen sturen |
| Timeout | 500 ms | 500 ms | Gratis deadman, zie hieronder |
| Timeout Brake Current | 0 A | 0 A | Uitrollen bij verlies van commando, niet remmen op een onbekende situatie |
| App to Use | UART / CAN | UART / CAN | Niet ADC — dat houdt AD2 vrij voor het temperatuursignaal |
| Speed PID min ERPM | 150 | 150 | Standaard staat dit veel hoger; met een hoge waarde regelt hij onder ~1,4 km/h niet |

**De timeout is de belangrijkste failsafe.** Stopt de Jetson met sturen — crash,
kernel panic, kabel eruit getrild — dan zetten beide VESC's zichzelf na 500 ms
uit. Dat werkt óók als deze software niet meer draait. Daarom zendt
`app/hardware/motor_logic.py` onafgebroken op 50 Hz, ook als er niets verandert.

### Waarom geen Arduino in het stuurpad

De verleiding is groot: er ligt er al een, en een MCP2515-module kost drie euro.
Toch niet doen, en de zwaarste reden is niet de latency maar de failsafe.

**Een tussenliggende Arduino maakt de VESC-timeout stuk.** Die timeout beschermt
tegen een dode Jetson doordat er dán geen frames meer komen. Zet je er een
Arduino tussen die het laatste commando blijft herhalen, dan blijven de frames
komen terwijl het brein al dood is — en rijdt de robot vrolijk door. Je kunt dat
repareren met een heartbeat-timeout in je eigen firmware, maar dan hangt je
belangrijkste beveiliging aan code die jij geschreven hebt in plaats van aan een
instelling in de controller. Dat is een ruil de verkeerde kant op.

Daar komt bij: **je ontsnapt niet aan de transceiver.** Of je nu een
MCP2515-module pakt of de CAN-controller die in de UNO R4 zelf zit (D4/D5, met
`CanExtendedId()` voor de 29-bits ID's die de VESC gebruikt) — er moet hoe dan
ook een transceiver tussen, en langs 48 V fasedraden bij voorkeur een
geïsoleerde. De Arduino vervangt dus niet het onderdeel dat je wilde vermijden;
hij komt er alleen vóór te staan.

En je raakt je gereedschap kwijt. Met socketcan debug je met `candump`,
`cangen` en python-can; met een brug debug je met `Serial.print` in firmware die
je zelf onderhoudt. Dat verschil voel je precies tijdens het in bedrijf stellen,
wanneer je het nodig hebt.

*Doorvoersnelheid is hier overigens niet het bezwaar:* op een UNO R4 is `Serial`
native USB CDC, dus die 500 frames per seconde passen er ruim door. Bij een
klassieke Arduino met MCP2515 op 115200 baud is dat wél het plafond, en dan komt
daar nog bij dat de MCP2515 maar twee ontvangstbuffers heeft.

**Waar de Arduino wél hoort:** de twee stuurstappenmotoren (daar zit hij al, en
step/dir-timing is precies microcontrollerwerk), en als inleeskanaal voor 5 V
dingen die de Jetson niet heeft — een RC-ontvanger voor handbediening,
bumperschakelaars, eindschakelaars. Die meldt hij via USB aan de Jetson.

**En niet als noodstop.** Die hoort een fysieke contactor in de acculeiding te
zijn met de knop in de spoelkring — geen microcontroller die zelf ook kan
vastlopen.

### De CAN-connector op de VESC

JST-GH, 4-polig. Tabel 2 van de VESC Classic 100V datasheet:

| Pin | Naam | Functie | Limiet |
|---|---|---|---|
| 1 | 5V | Power Out | 1 A |
| 2 | CANH | CAN | ±60 V |
| 3 | CANL | CAN | ±60 V |
| 4 | GND | Ground | 1 A |

> **Er zit één CAN-connector op een board.** Drie knopen op één bus (Jetson +
> twee VESC's) betekent dus een T-split of een klein verdeelprintje in de
> kabelboom — je kunt niet netjes doorlussen zoals bij boards met twee
> CAN-poorten.

> **Verbind pin 1 (5 V) niet tussen de twee VESC's door.** Dat is bij allebei
> een *uitgang*; twee voedingen tegen elkaar aan knopen levert een kringstroom
> op. Tussen de boards lopen alleen **CANH, CANL en GND**. Die 5 V is wél
> bruikbaar om de veldzijde van een geïsoleerde transceiver te voeden.

### De Jetson-kant: twee routes

De Jetson in deze machine is een **Orin Nano 16GB dev kit**.

**Route A — geïsoleerde USB-CAN-adapter (aanbevolen om mee te beginnen).**
Hij verschijnt als een gewone socketcan-interface, dus `can0` en hetzelfde
`ip link`-commando als hieronder, en je hoeft niets aan de device tree te doen.
Neem er een met echte galvanische isolatie: de bus loopt langs 48 V fasedraden,
en de datasheet waarschuwt zelf voor aardlussen bij USB-verbindingen. Let op het
verschil tussen twee soorten:

* **gs_usb / candleLight** (bijvoorbeeld een CANable): native socketcan, werkt
  met `can_interface: "socketcan"` en `can_channel: "can0"` uit de config.
* **slcan** (seriële CAN over een `/dev/ttyACM*`): daar hoort `slcand` bij, of
  je zet `can_interface` op `"slcan"` met het tty-pad als `can_channel`.

#### Welke adapter wel, en welke niet

Er zijn twee soorten die allebei "USB naar CAN" heten en niet hetzelfde zijn.

**Wel bruikbaar: een socketcan-adapter.** De productpagina noemt dan
*SocketCAN*, *gs_usb*, *candleLight* of een mainline Linux-driver (`peak_usb`).
Hij verschijnt als netwerkinterface `can0` en werkt met `ip link`, `candump` en
python-can zonder verdere software.

Een model dat aan alle eisen voldoet is de **InnoMaker USB2CAN-Module**: een
STM32F0 met gs_usb-firmware (dus `can0`, driverloos vanaf kernel 5.4) en een
**ISO1050** als transceiver — letterlijk de geïsoleerde transceiver die hierboven
wordt aanbevolen, met 1,5 kVDC/min isolatie. Hij heeft een **120 Ω terminator op
een jumper** aan boord, en zowel een D-SUB 9 als een schroefklem. Alternatieven
in dezelfde categorie: CANable 2.0 / CANable Pro (geïsoleerd) en PEAK PCAN-USB.

**Niet bruikbaar: een UART-CAN-brug met een CH340.** Dat zijn de goedkope
€15-modules die je bedient met een meegeleverd Windows-programma en AT-commando's
over een seriële poort. Ze verschijnen als `/dev/ttyUSB0`, nooit als `can0`. Je
kunt er geen willekeurige 29-bits extended ID's mee sturen zonder hun protocol
zelf na te bouwen, en het ontvangstverkeer hier — vijf statusframes per
controller op 50 Hz, dus circa 500 frames per seconde — loopt tegen de
bandbreedte van de seriële poort aan.

#### Wat die isolatie wel en niet doet

**Wel:** de CAN-kabel is geen massalus meer. Er loopt geen retourstroom door je
signaalmassa, en gaat er iets mis aan de 48 V-kant, dan plant die fout zich niet
voort naar de Jetson. Dat is de reden om hem te kopen. De ISO1050 heeft een
SiO₂-barrière (2,5 kVrms voor de DUB-uitvoering) en een transiëntimmuniteit van
50 kV/µs, dus de barrière zelf glitcht niet van een steile flank.

**Niet:** de buszijde van de adapter zelf beschermen. De CANH/CANL-pinnen van de
ISO1050 mogen **−27 V tot +40 V** zien; de CAN-pinnen van de VESC mogen ±60 V.
De adapter is daar dus de zwakkere van de twee. Schuurt er een fasedraad tegen
een CAN-draad, dan overleeft de VESC het mogelijk en de adapter niet.

**Ook niet:** overspanning wegvangen. Isolatie is geen TVS. Wil je dat er wel
bij, dan horen er TVS-diodes van CANH en CANL naar de busmassa en eventueel een
common-mode smoorspoel. Belangrijker en gratis: de CAN-bundel uit de buurt van
de fasedraden houden.

**En let op waar de echte spanningspieken in deze machine zitten:** niet op de
CAN-bus, maar op de DC-bus — teruglevering in een vol pak, en slepen met de
wielen aan de grond terwijl de hoofdschakelaar uit staat. Daar doet de isolatie
van je CAN-adapter niets tegen; dat is waar de taper op `v_in`, de precharge en
de sleepregels voor zijn. Zie *Remmen, hellingen en de accu*.

**In deze machine pakt dat gunstig uit.** De Jetson hangt aan een EGO-omvormer
(230 V AC) met zijn eigen netvoeding erachter, en de VESC's aan een 56 V
EGO-accu. Tussen die twee zitten dus al twee transformatoren: de massa's zijn
niet via de voeding verbonden. Zonder geïsoleerde adapter zou de CAN-massadraad
de *enige* verbinding tussen beide domeinen worden — een dunne signaaldraad als
massaverbinding tussen een zwevend 230 V-eiland en de accukring. Met de ISO1050
ertussen blijven ze gescheiden, en dat is hier dus geen halve maatregel maar
echte scheiding.

> Was de Jetson wél met een gewone, niet-geïsoleerde buck-converter uit hetzelfde
> pak gevoed, dan waren de massa's via de voeding alsnog verbonden en zat de winst
> alleen in het weghalen van de massalus.

**De test in één regel**, als je er al een hebt of twijfelt: steek hem in de
Jetson en kijk wat er verschijnt.

```bash
ip link | grep can        # can0 -> goed
ls /dev/ttyUSB* /dev/ttyACM*   # alleen dit -> seriële brug, niet bruikbaar
dmesg | tail -20          # welke driver hem heeft opgepakt
```

**Je hebt er één nodig, geen twee.** CAN is een bus: de adapter zet de Jetson
erop, en beide VESC's hangen aan diezelfde twee draden. Een tweede adapter zou
een tweede, losse bus maken — dat is precies de topologie die je met CAN wilde
vermijden. Zit de adapter aan een uiteinde van de bus, zet dan daar de ene
120 Ω terminator (veel adapters hebben er een aan boord of op een jumper) en de
andere bij de verste VESC.

**Route B — de CAN-controller van de Orin Nano zelf.** Die zit **niet op de
40-pins header**: op deze carrier zijn pin 29 en 31 gewoon GPIO01 en GPIO11, en
in de hele 40-pins tabel komt geen CAN voor. CAN staat op een **aparte header
J17**, 4-polig, 2,45 mm steek, waarvan de carrier-spec zegt dat het een
*footprint* is — kijk dus eerst of er op jouw bordje pinnen in zitten.

| J17 pin | Signaal | Richting |
|---|---|---|
| 1 | CAN_TX | uit, 3,3 V |
| 2 | CAN_RX | in, 3,3 V |
| 3 | GND | — |
| 4 | 3,3 V | voeding uit |

Dit is **logicaniveau, geen bus**: er hoort een transceiver tussen (ADM3053 of
ISO1050 met geïsoleerde DC-DC, geen kale SN65HVD230). Softwarematig heb je
pinmux- en device-tree-werk nodig voordat `can0` verschijnt; reken op een avond
uitzoekwerk. De winst is dat er geen USB-connector meer in het stuurpad zit.

### Bus fysiek

* **Twisted pair plus een aparte GND-referentiedraad.** Vertrouw niet op het chassis.
* **120 Ω alleen aan de twee fysieke uiteinden.** De datasheet noemt geen
  ingebouwde terminator, dus ga ervan uit dat je ze zelf plaatst. Meet met de
  accu los tussen CANH en CANL: je hoort **~60 Ω** te zien. 40 Ω betekent drie
  terminators, 120 Ω betekent er één.
* Houd de CAN-bundel weg bij de fasedraden; kruis ze haaks waar het niet anders kan.

Interface opbrengen op de Jetson:

```bash
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
```

Zonder `restart-ms` blijft de interface dood na één bus-off. Gebruik
`setup/can0.service` om dit bij elke boot te doen. Controleren of er verkeer is:

```bash
candump can0
```

Je hoort dan van beide ID's statusframes op 50 Hz binnen te zien komen, ook
zonder dat de robotsoftware draait.

---

## Motor Settings (VESC Tool)

| Parameter | Waarde | Waar het vandaan komt |
|---|---|---|
| Motor Type | FOC | Sinusvormig, vol koppel vanaf stilstand, stil bij lage snelheid |
| Sensor Port Mode | Hall | Verplicht: bij 6 km/h zit je op ~3 900 ERPM, sensorloos is daar onbetrouwbaar |
| Motor Current Max | 15 A | 44% minder warmte dan 20 A (warmte schaalt met I²). Kost 25% piekkoppel |
| Motor Current Max Brake | −10 A | Conservatief; regen belast dezelfde wikkeling |
| Battery Current Max | 20 A | Motorspec: max output 20 A. De Quinder-controller limiteerde op 18 ±1 A |
| Battery Current Max Regen | 0 A | Voorlopig — tot je gemeten hebt wat de EGO-accu aanneemt |
| Absolute Maximum Current | 30 A | Vangnet ruim boven bedrijf, ruim onder wat 2,5 mm² aankan |
| Battery Voltage Cutoff Start | 42,0 V | Motorspec: undervoltage 41 ±1 V |
| Battery Voltage Cutoff End | 40,0 V | Volledig uit, onder de undervoltage-grens |
| Max ERPM | 3 900 | = 6 km/h. Absoluut plafond is 4 570 ERPM (7 km/h) — DaviLot: nooit sneller |
| Motor Temp Sensor | Disabled | De Quinder-sensor is geen NTC; zie *Temperatuursignaal* |

**Boost in plaats van een vaste 20 A.** Houd de limiet op 15 A en til hem
bewust naar 20 A als je uit een kuil vermogen nodig hebt, met een teller die hem
na maximaal 10 s terugzet. Piekkoppel als je erom vraagt, onder toezicht,
begrensd in tijd.

### Over het configbestand in deze map

`vesc_mcconf_openagbot_bruut_500_watt_hubmotor.xml` is het **oude profiel van een
ander board** en bevat motorparameters (R, L, flux linkage, halltabel) die niet
van deze Quinder-motor zijn. Schrijf dat bestand dus niet blind naar een VESC.

De werkwijze is andersom: sluit aan, doe **Read Motor Configuration**, voer de
limieten hierboven in, draai de **FOC-detectie**, en exporteer daarna het
resultaat naar deze map. Dat geëxporteerde bestand is het echte configbestand.
Een firmware-flash kan de configuratie resetten — controleer je limieten na
élke flash.

---

## Bedrading motor → VESC

Kabel: 3 × 2,5 mm² + 8 × 0,14 mm², 200 mm.

> **Blauw, groen en geel komen twee keer voor.** De fasedraden én de
> hall-signaaldraden zijn blauw, groen en geel. Onderscheid ze op dikte:
> **2,5 mm² is fase, 0,14 mm² is hall.** Verwissel je die, dan blaas je de
> hall-sensoren op.

| Draad | Ø mm² | Functie | Naar VESC |
|---|---|---|---|
| Blauw | 2,5 | Motorfase A | Fase-uitgang |
| Groen | 2,5 | Motorfase B | Fase-uitgang |
| Geel | 2,5 | Motorfase C | Fase-uitgang — draait hij verkeerd om, wissel er twee |
| Rood | 0,14 | Hall Sensor + | Sensorconnector · +5V |
| Zwart | 0,14 | Hall Sensor − | Sensorconnector · GND |
| Blauw | 0,14 | Hall signaal A | Sensorconnector · H1 |
| Groen | 0,14 | Hall signaal B | Sensorconnector · H2 |
| Geel | 0,14 | Hall signaal C | Sensorconnector · H3 |
| Wit | 0,14 | Toerentalpuls (6/omw) | Niet aansluiten — de VESC telt zelf via de halls, tienmaal fijner |
| Paars | 0,14 | Temperatuursignaal | Via deler → IO-connector · AD2 |

De hall-volgorde is niet kritisch bij het aansluiten: de FOC-detectie meet de
tabel zelf uit. Klopt de draairichting niet, wissel dan **twee fasedraden**,
niet de halls. De datasheet noemt 8 dunne draden en hierboven staan er 7 — kijk
wat de achtste is (reserve of afscherming) voordat je de boom afknipt. De
motorkabel is maar 200 mm; je hebt een verlengboom nodig.

### Temperatuursignaal op AD2

De motor heeft een temperatuuruitgang, maar het is **geen NTC**: hij geeft
actief spanning af. Daarom kan hij niet op de TEMP-pin van de sensorconnector
(10k pull-up naar 3,3 V, die zou tegen de sensoruitgang in vechten). Gebruik AD2
met een deler ÷2.

```
IO-CONNECTOR                        SENSORCONNECTOR
paars (temp) ──[10k]──┬── AD2       rood  (Hall +) ── +5V
                      │             zwart (Hall −) ── GND
                    [10k]           blauw (A) ─────── H1
                      │             groen (B) ─────── H2
                      ├──[100nF]    geel  (C) ─────── H3
                      │
                      └── GND
```

| Toestand | Aan de sensor | Na deler ÷2 | Actie |
|---|---|---|---|
| Normaal | 4,8 – 5,0 V | 2,4 – 2,5 V | Volle limiet |
| Waarschuwing · 105 °C | 1,09 V | 0,55 V | Terug naar 5 A, foutvlag |
| Afslag · 110 °C | 0,68 V | 0,34 V | Limiet naar 1 A |
| Draad los of gebroken | — | 0 V | Valt onder de afslagdrempel — faalt veilig |

Het Lisp-script hiervoor staat onderaan dit document.

---

## Wat de software doet

| Bestand | Rol |
|---|---|
| `app/hardware/vesc_can.py` | Protocol: frames bouwen en uitpakken, telemetrie per controller bijhouden |
| `app/hardware/motor_logic.py` | De twee achterwielen als geheel: m/s ↔ eRPM, zendlus op 50 Hz, beveiligingslagen 2 en 3 |
| `app/services/vehicle_controller.py` | Ackermann, elektronisch differentieel, acceleratiebegrenzing |
| `app/hardware/stepper_logic.py` | De twee voorwielen (stappenmotoren via Arduino) — ongewijzigd |
| `data/config.example.json` → `vesc` | Alle waarden hierboven die de software nodig heeft |

### Frames

Extended frame, 29-bits ID = `(commando << 8) | vesc_id`, payload big-endian.

| Cmd | Betekenis | Payload | Schaal |
|---|---|---|---|
| 1 | SET_CURRENT | i32 | × 1000 (mA) |
| 2 | SET_CURRENT_BRAKE | i32 | × 1000 |
| 3 | SET_RPM | i32 | eRPM, geen schaal — begrens op 3 900 |
| 12 | SET_CURRENT_HANDBRAKE | i32 | × 1000 |
| 9 | STATUS ↓ | i32 eRPM, i16 stroom, i16 duty | ÷ 10 · ÷ 1000 |
| 16 | STATUS_4 ↓ | temp FET, temp motor, stroom in, pid pos | ÷ 10 · ÷ 10 · ÷ 10 · ÷ 50 |
| 27 | STATUS_5 ↓ | i32 tacho, i16 `v_in` | tacho: 300 = één wielomwenteling · ÷ 10 |

### Twee stromen, twee betekenissen

De telemetrie geeft per wiel **motorstroom** (STATUS) én **accustroom**
(STATUS_4). Dat zijn niet twee namen voor hetzelfde getal: de VESC is een
omvormer, geen weerstand. Bij lage duty ligt de motorstroom fors hoger dan wat
er uit de accu komt — bij een vastgelopen wiel op 20 A motorstroom ziet een
accuzijdige zekering maar ~1,7 A, en die merkt er dus niets van.

* **Motorstroom** bepaalt de warmte in de wikkeling. Hierop draaien de
  stall-detectie en het thermisch model, en hierop staat Motor Current Max.
* **Accustroom** bepaalt wat er door de zekering en de accukabel loopt, en is
  negatief tijdens teruglevering. Beide opgeteld is wat het pak levert — precies
  het getal dat de vraag "hoeveel regenstroom neemt de accu aan?" beantwoordt.

Je ziet ze naast elkaar in het aandrijfpaneel van de webinterface, op
`/api/motors` (`motor_current_a` en `input_current_a` per wiel, plus `accu_a` en
`accu_w` totaal) en in elke ritlog in `data/logs/`.

> **Handbrake is een greep, geen parkeerrem.** Bij nul toeren gaat alle
> handbrake-stroom als warmte de wikkeling in — precies het stall-scenario. De
> software gebruikt hem daarom niet: bij stilstand gaat de stroom naar 0 en
> rollen de wielen vrij.

### Beveiligingslagen, op volgorde van waarde per uur werk

| # | Laag | Waar | Reactietijd |
|---|---|---|---|
| 1 | Motor Current Max op 15 A | VESC-config | µs |
| 2 | Stall-detectie | `motor_logic.py` | 3 s |
| 3 | Thermisch model op de motorstroom | `motor_logic.py` | continu |
| 4 | VESC Timeout op 500 ms | VESC-config | 0,5 s |
| 5 | Zekering 30 A, ≥58 V DC | hardware | seconden |
| 6 | Temperatuursensor op AD2 + Lisp | op de controller zelf | 105 °C |

Laag 1 en 2 doen samen bijna al het werk. Laag 3 en 6 zijn elkaars aanvulling:
het model draait op de Jetson en is dood zodra die dood is; het Lisp-script
draait op de controller en blijft werken als de CAN-kabel eruit trilt.

**Een stroomlimiet is geen garantie.** Er bestaat geen stroomwaarde waarbij een
vastgelopen wiel veilig is. De motor is 9 A rated loading, en die 9 A geldt voor
een *draaiend* wiel met luchtstroming. 15 A is nog altijd ~1,7× overbelasting —
een pieklimiet, geen vrijbrief.

### Het thermisch model ijken

`motor_logic.py` schat de wikkelingtemperatuur uit de motorstroom die toch al op
50 Hz binnenkomt:

```
T += (i_motor**2 * k_warmte - T / tau) * dt
```

De startwaarden in `config.example.json` (`k_warmte` 0,00123 en `tau_s` 600) zijn
berekend, niet gemeten: ze komen uit op ~60 °C boven omgeving bij 9 A continu.
IJk ze één keer tegen de drietrapssensor: draai op een bekende stroom tot de
sensor bij 105 °C omslaat en noteer hoe lang dat duurde. Reken conservatief bij
stilstand — zonder luchtstroom is `tau` langer. Log `T` mee in het veld; daarmee
kies je uiteindelijk je definitieve 15 A op meetwaarden in plaats van op een
vuistregel.

---

## Remmen, hellingen en de accu

**Er zit nergens een mechanische rem.** Het wiel draait met de hand vrij naar
beide kanten; de 5 : 1 kast blokkeert niet tegendraads. Wat de robot tegenhoudt
is uitsluitend wat de VESC elektrisch doet — en dat werkt alleen als de accu de
energie aanneemt. Staat alles uit, dan rolt hij.

Dit is geen instelling die je goed of fout kunt zetten; het is een
vermogensbalans. Zwaartekracht levert een vermogen dat lineair met je snelheid
meegroeit, je rem kan een vast maximum wegzetten. Zodra de helling er net
overheen gaat is er géén snelheid meer waarbij het in evenwicht komt: je
versnelt, de zwaartekracht levert méér, je versnelt harder.

| Regen per VESC | Totaal | Houdt bij 6 km/h | Houdt bij 3 km/h |
|---|---|---|---|
| −3 A | 6 A · 312 W | ~4 % | ~8 % |
| −5 A | 10 A · 520 W | ~6 % | ~13 % |
| −10 A | 20 A · 1 040 W | ~13 % | ~25 %* |

Vuistregel bij 6 km/h: elke ampère teruglevering koopt ~0,6 % helling. Afgeleid
uit `m·g·sin(θ)·v` bij 500 kg en 52 V. \* De lage-snelheidskolom loopt eerder
tegen de 15 A motorlimiet aan dan tegen het vermogen — bovengrens, geen belofte.

### Voeding van deze machine

| Verbruiker | Bron |
|---|---|
| Twee VESC's | 56 V EGO-accu (14S, vol 58,8 V) |
| Jetson | EGO-omvormer 230 V AC, met de eigen netvoeding van de dev kit |

Twee dingen volgen daaruit.

**De taper op `v_in` in `config.json` is op dit pak gesneden.** 56,0 V als begin
en 58,0 V als eind horen bij een 14S EGO; wissel je van accutype, dan moeten die
twee mee.

**Hangt de omvormer aan hetzelfde pak als de VESC's?** Zo ja, dan zakt je
Jetson-voeding mee op het moment dat de aandrijving het hardst trekt — een
20 A-piek uit een kuil is precies wanneer je hem niet wilt verliezen — en valt
alles tegelijk uit als de BMS afschakelt. Een eigen accu voor de omvormer haalt
dat koppel uit elkaar: de aandrijving mag dan leegraken zonder je brein mee te
nemen. Reken bij één gedeeld pak in elk geval na of de omvormer zijn eigen
laagspanningsgrens niet eerder haalt dan de 42 V waarop de VESC's terugregelen.

De EGO-accu néémt regen aan, maar **bij een vol pak valt de rem weg**. Dat is
bekend EGO-gedrag en geldt voor élke volle accu. De overspanningsbeveiliging van
de VESC helpt niet: dit is een 100 V board en je pack gaat tot 58,8 V, dus hij
regelt uit zichzelf niets terug. Die fade moet je zelf maken — en dat doet
`_update_regen_marge()` in `motor_logic.py`:

| Gemeten `v_in` | Regen | Snelheidsplafond |
|---|---|---|
| < 56,0 V | vol | Normaal |
| 56,0 – 58,0 V | lineair naar nul | Evenredig terug |
| > 58,0 V | geen | Stapvoets |

Kalibreer die grenzen (`vesc.safety.regen` in de config) op wat je werkelijk
terugleest bij een volle accu. Omdat `P = F · v` houdt dezelfde rem bij de halve
snelheid de dubbele helling: **volle accu betekent weinig ruimte betekent
langzaam naar beneden.** Dat is de enige mitigatie die de natuurkunde aan jouw
kant zet.

Wat het werkelijk oplost: een **remweerstand op de bus** (MOSFET met
vermogensweerstand boven ~57 V, ~4 Ω ≈ 850 W ongeacht laadtoestand), of een
**veerbelaste elektromagnetische rem op de as** — het enige dat ook werkt als de
VESC uit staat. Tot die er zijn geldt de bedrijfsregel: geen hellingen op die je
niet uitrollend kunt verlaten, en nooit vol beginnen aan een perceel met helling.

---

## Lisp-script voor de temperatuurbeveiliging

VESC Tool → Scripting. Draait op de controller zelf en blijft dus werken als de
Jetson vastloopt.

```lisp
(def i-max (conf-get 'l-current-max))   ; bewaar de geconfigureerde 15 A
(def v-warn 1.50)   ; boven deze waarde: normaal
(def v-trip 0.45)   ; onder deze waarde: afslag (of draad los)

(loopwhile t
  (progn
    (def v (get-adc 1))                 ; kanaal 1 = AD2
    (if (< v v-trip)
        (conf-set 'l-current-max 1.0)
        (if (< v v-warn)
            (conf-set 'l-current-max 5.0)
            (conf-set 'l-current-max i-max)))
    (sleep 0.2)))
```

`conf-set` schrijft niet naar flash: na een reboot sta je automatisch weer op je
veilige 15 A. Kalibreer `v-warn` en `v-trip` op wat je werkelijk terugleest, en
controleer de syntax tegen jouw firmwareversie — LispBM is nog in beweging.

---

## Bankprocedure

In deze volgorde, vóór het eerste veldgebruik:

1. **Precharge eerst.** XT90-S of een voorlaadweerstand; dit board heeft flinke
   condensatoren.
2. **Wiel vrij van de grond.** Bok of klem, vóórdat er spanning op staat.
3. **Limieten invoeren en opslaan** vóór je de motor aankoppelt. Doe eerst
   *Read Motor Configuration* — wat VESC Tool offline toont zijn defaults van
   een ander hardwareprofiel.
4. **Stock-controller volledig van de fasedraden af.** Blijft hij eraan hangen,
   dan laadt de VESC via zijn body-diodes diens buscondensatoren op.
5. **FOC-detectie draaien** met de halls aangesloten. Noteer de gemeten R en L.
6. **Draairichting controleren.** Verkeerd om? Twee fasedraden wisselen.
7. **ERPM-limiet verifiëren:** vol commando moet uitkomen op 3 900 ERPM.
8. **Odometrie controleren:** één wielomwenteling met de hand = 300 tellen.
9. **CAN-bus opbouwen:** unieke ID per board, 500 kbit/s, statusframes 1–5 op
   50 Hz. Meet ~60 Ω tussen CANH en CANL met de accu los.
10. **Timeout aantoonbaar maken:** laat een wiel draaien en trek de CAN-kabel
    eruit. Hij hoort binnen een halve seconde uit te vallen. Test dit één keer
    bewust — het is je belangrijkste failsafe.
11. **Meetronde in het veld** met telemetrie aan (`/api/motors` of de CSV-logs
    in `data/logs/`). Dáárop kies je je definitieve 15 A en ijk je het model.
12. **Configbestand exporteren en in deze map zetten.**

### Onthouden

* **Houd de Quinder-controller heel.** Niet de kabelboom doorknippen: hij is je
  terugvaloptie én je meetreferentie. Wel volledig loskoppelen van de fasedraden.
* **Zekering: 30 A, niet 25 A**, en controleer de **DC**-spanningswaarde —
  auto-steekzekeringen zijn vaak op 32 V DC gespecificeerd, jij zit tot ~58 V.
* **Nooit sneller dan 7 km/h.** Bij slepen met de wielen aan de grond: 5 km/h.
* **Sleep nooit met de hoofdschakelaar uit.** Rollende wielen maken de motor tot
  generator, en die spanning komt via de body-diodes altijd op de bus. Met de
  accu erop wordt hij geklemd; zonder accu laadt hij de buscondensatoren op tot
  niets hem meer tegenhoudt. De accu is hier de bescherming, niet het slachtoffer.
* **Precharge ook na een sleepbeurt** met de schakelaar uit.
* **Verwissel nooit + en −.** Dat sloopt de hall-sensoren, en die zitten in een
  IP66-behuizing.

---

## Rekenwaarden

Herbereken deze als je van band, tandwielkast, massa of accuspanning wisselt.

| Grootheid | Waarde | Afleiding |
|---|---|---|
| Bandomtrek | 1,277 m | Buitenmaat 16" = 406,4 mm × π |
| Poolparen | 10 | 2P = 20 polen |
| Overbrenging | 5 : 1 | Zelfsmerende binnentandwielkast |
| ERPM per wiel-RPM | × 50 | 5 (kast) × 10 (poolparen) |
| 6 km/h | 3 917 ERPM | 78,3 wiel-RPM × 50 |
| 7 km/h — nooit hoger | 4 569 ERPM | 91,4 wiel-RPM × 50 |
| Tellen per wielomwenteling | 300 | 6 stappen/elek.omw × 10 poolparen × 5 |
| Odometrieresolutie | 4,26 mm | 1 277 mm ÷ 300 |
| Continu belastbaar | 9,0 A · 75 RPM | Rated loading ≈ 5,7 km/h |
| Maximaal | 20 A · 55 RPM | Max output ≈ 4,2 km/h, ≈ 1 kW ingangsvermogen |
| Massa (aslast) | 500 kg | Motorspec max axle load |
| Hellingvermogen bij 6 km/h | 8,2 kW per eenheid sin θ | 500 × 9,81 × 1,667 |
| Helling per ampère regen | ~0,6 % | 52 V ÷ 8 177 W, bij 6 km/h |
| Accu vol | 58,8 V | EGO 14S × 4,2 V — hier is de regenruimte nul |
| Overspanningsgrens board | 100 V | Tientallen volts boven de accu |

---

## Openstaande vragen

Af te vinken op de werkbank; de software draait ondertussen op veilige
startwaarden.

* Wie voedt de temperatuursensor? Sluit alleen +5 V en GND van de VESC aan en
  meet de paarse draad koud. ~4,8 V = klaar. 0 V = de voeding zat in de
  Quinder-controller.
* Werkt `get-adc` met App op UART/CAN, en geeft hij pinspanning of de gedeelde
  waarde? Eén meting met een multimeter ernaast beantwoordt beide.
* Is het temperatuursignaal drietraps of proportioneel? Meet tijdens een zware klim.
* Hoeveel regenstroom gebruikt de stock-controller? Stroomtang om de plusdraad
  tijdens remmen op een helling die hij nog wél houdt.
* Wat doet de firmware bij hoge busspanning tijdens regen — taperen of een
  `OVER_VOLTAGE`-fout? Een fout betekent dat de motor er in één klap uit gaat.
* Koppelt de BMS af bij een vol pak, of trekt de controller zich terug?
