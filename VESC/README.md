# VESC instellen — Bruut OpenAgbot

Twee **VESC Classic 100V** sturen elk een **Quinder 8" 48V 550W naafmotor** aan,
gevoed uit een **EGO 56 V-accu**, aangestuurd door de Jetson over **CAN**.

| | |
|---|---|
| Motor | Quinder 8" 48V 550W · art. 10101025 · 2× |
| Controller | VESC Classic 100V · 2× |
| Accu | EGO 56 V, 5 Ah = **14S2P** · ~252 Wh |
| Vervangt | Quinder DC-controller 10301059 + Arduino/MCP4728-DAC |
| Aansturing | Jetson · CAN 500 kbit/s · ID 0 (links) en 1 (rechts) |
| Topsnelheid | 6 km/h = 3 900 ERPM · **nooit boven 7 km/h** |

Dit bestand is de **werkvolgorde en de instellingen**. De volledige onderbouwing —
waarom CAN en geen UART, hoe het thermisch model werkt, de vermogensbalans bij
remmen — staat in [README_DEV.md](README_DEV.md).

> De VESC Tool is gratis. Een kleine donatie aan het VESC-project helpt hen
> verder met de software waar jij op meelift.

---

## Voordat er spanning op staat

* **Wiel vrij van de grond.** Bok eronder, vóórdat de accu erop gaat.
* **Precharge.** XT90-S of voorlaadweerstand — dit board heeft flinke condensatoren.
* **Quinder-controller volledig los van de fasedraden**, maar **niet doorknippen**:
  hij is je terugvaloptie én je referentiemeting.
* **Fase = 2,5 mm², hall = 0,14 mm².** Blauw, groen en geel komen twee keer voor
  in de motorkabel. Verwissel je ze, dan blaas je de hall-sensoren op.
* **Nooit + en − verwisselen.** Dat sloopt de halls, en die zitten in een
  IP66-behuizing die je niet openmaakt.
* **Zekering 30 A**, en controleer de **DC**-waarde — auto-steekzekeringen zijn
  vaak op 32 V DC gespecificeerd en jij zit tot ~58 V.
* Eén board tegelijk via USB. CAN komt pas in stap 12.

**Begin met `Read Motor Configuration`.** Wat de VESC Tool zonder uitlezen toont
zijn defaults van een vreemd hardwareprofiel — dan bewerk je een configuratie die
nergens bestaat. Controleer je limieten ook **na elke firmware-flash**; een flash
kan ze resetten.

---

## De instellingen

Elk scherm afsluiten met **Write Motor Configuration**. De tool schrijft niets uit
zichzelf weg — en schrijft álle velden, ook die je niet aanraakte.

### Motor Settings → General

| Veld | Waarde | |
|---|---|---|
| Motor Type | **FOC** | Vol koppel vanaf stilstand, stil bij kruipsnelheid, bruikbare stroommeting |
| Invert Motor Direction | **False** | Beslis dit in stap 11. De motoren zitten gespiegeld, dus één board krijgt `True` |

Zet de vlag hier en niet in de software: dan draaien telemetrie, tacho en het
teken van de regenstroom mee. Wissel **geen fasedraden** — dat maakt de
uitgemeten halltabel ongeldig.

### Motor Settings → Sensors

| Veld | Waarde | |
|---|---|---|
| Sensor Port Mode | **Hall Sensors** | Ons hele bereik is 0–3 900 ERPM; de sensorloze waarnemer wordt pas ergens rond 1 000–2 000 ERPM betrouwbaar. Sensorloos betekent elke start op een helling blind |

Encoder- en Sin/Cos-velden ongemoeid laten: die worden niet gelezen.

### Motor Settings → Current

| Veld | Default | Waarde | |
|---|---|---|---|
| Motor Current Max | 60 A | **15 A** | Continu belastbaar is ~9 A. 15 i.p.v. 20 A scheelt 44 % warmte (I²) en kost 25 % piekkoppel |
| Motor Current Max Brake | −60 A | **−10 A** | Remmen belast dezelfde wikkeling, vaak ná een klim |
| Absolute Maximum Current | 150 A | **30 A** | Noodrem, geen regellimiet. 2× bedrijf, ruim onder wat 2,5 mm² aankan |
| Slow ABS Current Limit | False | **False** | Houdt die trip snel; True maakt er een trage softwarelimiet van |
| Battery Current Max | 99 A | **20 A** | Motorspec max output. Wordt in de praktijk nooit bereikt: de motorlimiet bindt eerder |
| Battery Current Max Regen | −60 A | **−3 A** | Zie *Remmen* hieronder — dit getal hangt aan de accu, niet aan de motor |

Overige velden (current scales, input current map, DRV8301) laten staan.

### Motor Settings → Voltage

| Veld | Default | Waarde | |
|---|---|---|---|
| Battery Voltage Cutoff Start | 10 V | **42,0 V** | Motorspec zegt 41 ±1 V, én het is 3,00 V/cel op 14S. Twee redeneringen, één antwoord |
| Battery Voltage Cutoff End | 8 V | **40,0 V** | Dit is de **enige** onderspanningsbeveiliging die er is — zie *De accu* |
| Battery Voltage Regen Cutoff Start | 1000 V | **56,0 V** | Vanaf hier bouwt de VESC de teruglevering zelf af. Het bijpassende snelheidsplafond in de software is nog niet gebouwd — zie README_DEV |
| Battery Voltage Regen Cutoff End | 1100 V | **57,5 V** | = gemiddeld 4,11 V/cel. Bewust laag: er is geen celbewaking die ingrijpt |
| Battery Filter Constant | 45 | *laten* | Niet scherper zetten: onder belasting zakt de spanning kort in, en zonder filter gaat je cutoff af op elke stroompiek |

### Motor Settings → RPM

| Veld | Default | Waarde | |
|---|---|---|---|
| Max ERPM | 100 000 | **3 900** | 6 km/h. Absoluut plafond 4 569 (7 km/h) — daar nooit overheen |
| Max ERPM Reverse | −100 000 | **−3 900** | Open punt: halveren naar −1 950 (3 km/h) is verdedigbaar op 500 kg |
| ERPM Limit Start | 80 % | *laten* | Knijpt vanaf 3 120 geleidelijk af i.p.v. tegen een muur |

### Motor Settings → Wattage

**Beide velden laten staan** (1 500 000 W = begrenzer uit). De stroomlimieten
begrenzen het vermogen al; een wattlimiet ernaast is een tweede begrenzer voor
dezelfde grootheid, die zich anders gaat gedragen naarmate het pak leegloopt.

### Motor Settings → Temperature

| Veld | Waarde | |
|---|---|---|
| Motor Temperature Sensor Type | **Disabled** | De Quinder-sensor is **geen thermistor**: hij geeft actief spanning af (~4,8 V koud, 1,09 V bij 105 °C, 0,68 V bij 110 °C). Tegen een 10k pull-up levert dat geen meting op |
| MOSFET Temp Cutoff | 85 / 100 °C *laten* | Echte sensor op het board. De enige thermische meting zonder aanname eronder |

Het paarse draadje gaat via een deler ÷2 naar **AD2**, waar een Lisp-script de
drempels bewaakt. Zolang dat script niet draait, is het thermisch model in
`motor_logic.py` je enige motorbescherming — en dat draait op berekende, nog niet
geijkte startwaarden.

### Motor Settings → BMS

**BMS Type → `Disabled`.** Dit scherm is voor een VESC-BMS die celspanningen over
CAN doorgeeft. Een EGO-pak spreekt dat protocol niet. Laat je het op *VESC BMS*
staan, dan staat er een begrenzer scherp die wacht op gegevens die nooit komen.

### Motor Settings → Advanced

| Veld | Default | Waarde | |
|---|---|---|---|
| **Maximum Input Voltage** | **57,0 V** | **65,0 V** | Een vol 14S-pak is 58,8 V. Op 57 V krijg je een `OVER_VOLTAGE`-fout zodra de accu vol van de lader komt — en een fout zet de motor in één klap uit |
| Maximum Duty Cycle | 95 % | *laten* | Niet naar 100 %: die marge heeft de eindtrap nodig om fasestroom te meten |
| Fault Stop Time | 500 ms | *laten* | **Niet** de CAN-timeout — die staat in App Settings en is toevallig ook 500 ms |
| Additional Faults | uit | **uit laten** | Zie hieronder |

> `57,0 V` is een 12S-default. Staat dat er ná `Read Motor Configuration` nog
> steeds, dan is het uitlezen niet gelukt. Op een echt 100 V-board hoort hier al
> 90 V of meer te staan — laat het dan staan.

**Waarom `Overspeed` uit blijft:** een fout zet de motor uit, en deze machine
heeft geen mechanische rem. Rolt hij een helling af en gaat daardoor over de
limiet, dan haalt die fout precies weg wat hem nog tegenhield. Runaway-detectie
zit in de software, waar de reactie een *gestuurde* actie kan zijn.

### Motor Settings → FOC · detectie

Halls aangesloten, wiel vrij, limieten hierboven al weggeschreven. Draai de
detectie en lees de uitkomst één keer goed:

* De zes middelste getallen van de halltabel horen **zes verschillende** waarden
  te zijn. Twee dezelfde = een sensor die niet schakelt.
* **0 en 7 horen er niet in te staan** — dat is alle drie laag of alle drie hoog:
  dode sensor, gebroken draad of geen voeding.
* Noteer R, L en flux linkage in het [Meetblad](#meetblad).

Klopt de tabel niet, dan is dat bedrading — niet iets wat je met een instelling
repareert.

### Motor Settings → PID Controllers

**Speed PID min ERPM → 150.** Standaard staat dit veel hoger; daarmee regelt hij
onder ~1,4 km/h niet.

### App Settings · per board

| Parameter | Links | Rechts | |
|---|---|---|---|
| VESC ID | **0** | **1** | Onderste byte van elk CAN-adres; moet uniek zijn |
| CAN Baud Rate | 500k | 500k | |
| CAN Status Message Mode | 1 – 5 | 1 – 5 | Levert eRPM, stroom, duty, temperaturen, tacho en `v_in` zonder pollen |
| CAN Status Rate | 50 Hz | 50 Hz | |
| Multiple VESCs Over CAN | **uit** | **uit** | Die functie spiegelt één gascommando naar alle VESC's — aan betekent: niet kunnen sturen |
| Timeout | 500 ms | 500 ms | **De belangrijkste failsafe** |
| Timeout Brake Current | 0 A | 0 A | Uitrollen bij verlies van commando, niet remmen op een onbekende situatie |
| App to Use | UART / CAN | UART / CAN | Niet ADC — dat houdt AD2 vrij voor het temperatuursignaal |

**De timeout is je beste beveiliging omdat hij niet van onze software afhangt.**
Stopt de Jetson met sturen, dan zetten beide VESC's zichzelf na 500 ms uit — ook
als deze codebase niet meer draait. Daarom zendt de regellus in
`vehicle_controller.py` onafgebroken op 50 Hz, ook als er niets verandert.

**Toon dat één keer aan:** laat een wiel draaien en trek de CAN-kabel eruit. Hij
hoort binnen een halve seconde uit te vallen.

---

## Remmen

**Er zit nergens een mechanische rem.** Wat de machine tegenhoudt is uitsluitend
wat de VESC elektrisch doet, en dat kan alleen als de accu de energie aanneemt.

Een regenlimiet is **geen kraan die stroom omleidt** — het is een randvoorwaarde
voor de regelaar. Mag er niets naar het pak, dan verlaagt de VESC de fasestroom:
hij remt minder hard. De energie wordt niet omgeleid, hij wordt niet onttrokken,
en de machine rolt door. Bij stilstand kun je wél vol houden (snelheid nul, dus
geen mechanisch vermogen — alles wordt warmte).

| Regen per VESC | Totaal | Houdt bij 6 km/h | Houdt bij 3 km/h |
|---|---|---|---|
| **−3 A** | 6 A · 312 W | **~4 %** | ~8 % |
| −5 A | 10 A · 520 W | ~6 % | ~13 % |
| −10 A | 20 A · 1 040 W | ~13 % | ~25 % |

Vuistregel bij 6 km/h: elke ampère teruglevering koopt ~0,6 % helling.

**Waarom −3 A en niet meer:** laadstroom hoort afgezet tegen het aantal cellen
*parallel*. Het 10 Ah-pak is 14S4P van 2,5 Ah-cellen (Samsung INR18650-25R,
4 A snellaadstroom), dus een 5 Ah-pak is **14S2P**. Met −3 A per VESC zit je op
3 A per cel; met −5 A op 5 A per cel, boven spec.

| Pak | Opbouw | Regen per VESC |
|---|---|---|
| 2,5 Ah | 14S1P | −1,5 A |
| **5,0 Ah** | **14S2P** | **−3 A** |
| 7,5 Ah | 14S3P | −4 A |
| 10 / 12 Ah | 14S4P | −5 A |

> **Een te lage regenlimiet maakt niets kapot.** De VESC maakt die stroom
> eenvoudigweg niet. De keuze voor een mechanische rem is een veiligheids- en
> functievraag, geen vraag over het beschermen van onderdelen.

**Waar het wél misgaat:** slepen of rollen met de controller uit. Dan regelt
niemand en komt de generatorspanning via de body-diodes hoe dan ook op de bus.
Met accu erop wordt die geklemd; zonder accu laden de condensatoren op tot niets
het meer tegenhoudt. **Sleep nooit met de hoofdschakelaar uit, en precharge ook
na een sleepbeurt.**

**En stilstaand een helling houden op stroom kookt de motor** — vol koppel, geen
luchtstroom. Daarvoor is de stall-detectie.

---

## De accu

Wat de teardowns en de DIY-gemeenschap over EGO 56 V-pakken melden, en wat het
voor ons betekent:

* **De plus- en minklem gaan rechtstreeks naar de cellenstring, om de elektronica
  heen.** De hoofdstroom loopt niet door de BMS.
* **Er zit geen afschakel-MOSFET in.** De BMS beveiligt door over de `D`-pin
  tegen het *gereedschap* te zeggen dat het moet uitschakelen — en een VESC is
  geen EGO-gereedschap.

| | Gevolg |
|---|---|
| Afkoppelen tijdens remmen | **Kan niet** — er is geen schakelaar om te openen |
| Overladen via regen | **Niemand vangt het af.** Geen cutoff, geen laadstroomlimiet, geen celbewaking |
| Onderspanning per cel | Niet beschermd. Onze 42,0 V is de enige grens |

Alles wat dit pak tijdens teruglevering beschermt is dus een instelling in onze
VESC. Daarom ligt de regenband bewust laag.

**Nog te meten:** wat een vol pak werkelijk aanwijst. EGO geeft 50,4 V nominaal
op en de cellen zijn 4,2 V-types, dus 58,8 V is de theoretische bovengrens — maar
de naam "56 V" volgt de conventie waarin het merkgetal 14 × 4,0 V is. Eén
multimetermeting na het laden beslist de hele taperband.

**En meet wat de stock-controller doet.** Die heeft op déze machine met dít pak
al geremd. Stroomtang om de plusdraad op een helling die hij nog houdt: meer dan
6 A betekent dat onze −3 A conservatief is.

---

## Bedrading

### Motor → VESC

Kabel 3 × 2,5 mm² + 8 × 0,14 mm², 200 mm — je hebt een verlengboom nodig.

| Draad | Ø | Functie | Naar |
|---|---|---|---|
| Blauw / Groen / Geel | 2,5 | Motorfase A / B / C | Fase-uitgangen |
| Rood / Zwart | 0,14 | Hall + / − | Sensorconnector +5V / GND |
| Blauw / Groen / Geel | 0,14 | Hall A / B / C | H1 / H2 / H3 |
| Wit | 0,14 | Toerentalpuls (6/omw) | **Niet aansluiten** — de VESC telt via de halls, tienmaal fijner |
| Paars | 0,14 | Temperatuursignaal | Via deler ÷2 → IO-connector AD2 |

De hall-volgorde is niet kritisch: de detectie meet de tabel uit.

```
IO-CONNECTOR                        SENSORCONNECTOR
paars (temp) ──[10k]──┬── AD2       rood  ── +5V
                      │             zwart ── GND
                    [10k]           blauw ── H1
                      │             groen ── H2
                      ├──[100nF]    geel  ── H3
                      └── GND
```

### CAN

JST-GH 4-polig: `1 = 5V uit`, `2 = CANH`, `3 = CANL`, `4 = GND`.

* **Verbind pin 1 niet tussen de twee VESC's.** Dat is bij allebei een *uitgang*.
  Tussen de boards lopen alleen CANH, CANL en GND.
* **Eén CAN-connector per board**, dus drie knopen betekent een T-split of een
  verdeelprintje — doorlussen kan niet.
* **120 Ω alleen aan de twee fysieke uiteinden.** Meet met de accu los tussen
  CANH en CANL: je hoort **~60 Ω** te zien. 40 Ω = drie terminators, 120 Ω = één.
* Twisted pair plus een aparte GND-draad. Vertrouw niet op het chassis, en houd
  de bundel weg bij de fasedraden.

**Aan de Jetson-kant: een geïsoleerde socketcan-adapter.** De productpagina moet
*SocketCAN*, *gs_usb* of *candleLight* noemen en hij moet als `can0` verschijnen
— bijvoorbeeld een InnoMaker USB2CAN (ISO1050) of CANable Pro. Een goedkope
CH340-UART-brug is **niet** bruikbaar: die verschijnt als `/dev/ttyUSB0` en kan
geen willekeurige 29-bits ID's sturen. Je hebt er **één** nodig, niet twee — CAN
is een bus.

```bash
ip link | grep can        # can0 -> goed
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
candump can0              # statusframes van beide ID's op 50 Hz
```

Zonder `restart-ms` blijft de interface dood na één bus-off. `setup/can0.service`
doet dit bij elke boot.

---

## Rekenwaarden

Herbereken deze als je van band, tandwielkast, massa of accu wisselt.

| Grootheid | Waarde | Afleiding |
|---|---|---|
| Bandomtrek | 1,277 m | 16" buitenmaat × π |
| Poolparen · overbrenging | 10 · 5:1 | |
| **ERPM per wiel-RPM** | **× 50** | 5 × 10 |
| 6 km/h | 3 917 ERPM | afgerond naar 3 900 |
| 7 km/h — nooit hoger | 4 569 ERPM | grens DaviLot |
| Tellen per wielomwenteling | 300 | odometrie: 4,26 mm per tel |
| Continu belastbaar | 9,0 A · 75 RPM | ≈ 5,7 km/h |
| Massa (aslast) | 500 kg | motorspec |
| Accu vol (theoretisch) | 58,8 V | 14S × 4,2 V — **meet dit na** |

---

## Beveiligingslagen

| # | Waar | Wat |
|---|---|---|
| 1 | VESC | Motor Current Max 15 A — voorkomt de oorzaak |
| 2 | Software | Stall-detectie op stroom en toerental |
| 3 | Software | Thermisch model op gemeten stroom (ongeijkt) |
| 4 | VESC | **Timeout 500 ms** — werkt ook als onze software dood is |
| 5 | Hardware | Zekering 30 A DC |
| 6 | VESC | Lisp-script op AD2 met de echte motorsensor |

---

## Meetblad

Invullen tijdens het in bedrijf stellen. Dit is de verantwoording van wat er
werkelijk in de boards staat.

| | Links (ID 0) | Rechts (ID 1) |
|---|---|---|
| Datum · serienummer · firmware | | |
| Halltabel (8 getallen) | | |
| Motor R (mΩ) · L (µH) · flux (mWb) | | |
| Invert Motor Direction | | |
| Vol commando → gemeten ERPM | | |
| Maximum Input Voltage zoals uitgelezen | | |
| Paarse draad koud gemeten (V) | | |
| Timeout aangetoond (datum) | | |
| Geëxporteerd configbestand | | |

Eenmalig, niet per board:

| | Waarde |
|---|---|
| Pakspanning vol, direct na laden | |
| Nemen de klemmen stroom aan? (labvoeding ~0,5 A) | |
| Regenstroom stock Quinder-controller (stroomtang) | |
| Neemt het pak −3 A regen aan? | |

---

## Tot slot

**Schrijf `vesc_mcconf_openagbot_bruut_500_watt_hubmotor.xml` niet naar een
board.** Dat is het oude profiel van ánder materiaal; de motorparameters zijn
niet van deze motor. De werkwijze is andersom: uitlezen, limieten invoeren,
detectie draaien, en het resultaat **exporteren naar deze map**. Dát wordt het
echte configbestand.

Verdieping — waarom CAN en geen UART, waarom geen Arduino in het stuurpad, de
vermogensbalans bij remmen, het Lisp-script, de openstaande vragen:
[README_DEV.md](README_DEV.md).
