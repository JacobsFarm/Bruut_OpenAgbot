Virtual reality is populair, maar je zou geen honderden dollars moeten uitgeven om de technologie erachter te krijgen. Gelukkig is dit waar de VR IMU Breakout binnenkomt. De kern is CEVA's BNO086, een gecombineerd triaxiale versnellingsmeter/gyroscoop/magnetometer-pakketsysteem (SiP) in 32-bits ARM © Cortex™M0 +. De BNO086 Inertial Measurement Unit (IMU) produceert nauwkeurige rotatievectorkoppen, ideaal voor VR-en andere koerstoepassingen, met een statische rotatiefout van 2 graden of minder. De VR IMU is precies waar we op hebben gewacht; Alle sensorgegevens worden samengevoegd en gecorrigeerd tot zinvolle, nauwkeurige IMU-informatie. Het is perfect voor elk project dat richting of beweging moet voelen.

Het IMU-splitbord wordt ook geleverd met twee I2C Qwiic-connectoren om de verbinding met het miniatuur QFN-pakket iets gemakkelijker te maken. Het maakt deel uit van het Qwiic-verbindingssysteem, dus u hoeft niet te lassen om erachter te komen hoe de dingen zijn georiënteerd. Als u echter liever een breadboard gebruikt, hebben we nog steeds 0,1 "uit elkaar geplaatste pinnen.


De BNO080 is ontworpen om te worden gebruikt in Android-telefoons en kan alle berekeningen aan die nodig zijn voor een virtual reality-bril met alleen de telefoon. Voor BNO080 EOL biedt CEVA een plug-in alternatief voor BNO086 met verbeterde functies (14-bits accelerometerfusie, minder inactief vermogen en interactieve kalibratie). De sensor is zeer krachtig en wordt geleverd met een complexe interface. Dankzij de jumper op het bord kun je kiezen tussen twee verschillende I2C-adressen. Niettemin, als I2C niet uw favoriete communicatieoptie is, kunnen de sensoren communiceren via SPI en UART! We hebben ook een I2C-based bibliotheek geschreven die rotatievectoren biedt (de metingen die de meeste mensen van een IMU willen), versnelling, gyroscoop-en magnetometermetingen, staptellingen, en activiteitsclassifiers (zoals fietsen).


Het is een ecosysteem van I2C-sensoren, actuatoren, schilden en kabels die prototyping sneller en minder foutgevoelig maken. Alle QWIIC-compatibele kaarten gebruiken de gemeenschappelijke 1mm pitch, 4-pins JST-connector. Dit vermindert de vereiste PCB-ruimte, en de gepolariseerde verbinding betekent dat u het niet verkeerd kunt ophangen.





Bedrijfsspanning

2.4v tot 3.6v

Meestal 3,3 V via Qwiic-kabel

I2C (standaard): tot 400kHz

SPI: tot 3MHz

UART: 3 mbps

Rotatievector

Dynamische fout: 3,5 °

Statische fout: 2.0 °

Spelrotatie vector

Dynamische fout: 2,5 °

Statische fout: 1,5 °

Dynamische cursusdrift: 0,5 °/ min

Geomagnetische rotatie vector

Dynamische rotatiefout: 4,5 °

Statische rotatiefout: 3,0 °

Zwaartekracht Hoekfout: 1,5 °

Lineaire versnellingsnauwkeurigheid: 0,35 m/s2

Accelerometer nauwkeurigheid: 0,3 m/s2

Nauwkeurigheid gyroscoop: 3.1 °/ s

Magnetometer nauwkeurigheid: 1.4 & micro;T

2 Qwiic-verbindingspoorten

I2C adres: 0x4B (standaard), 0x4A

I2C pull-up weerstand (2.2kΩ)

Vermogen LED

Springschot

Vermogen LED

I2C pull-up weerstand

Adreselectie

Protocol selectie 0

Protocol optie 1

Bordgrootte: 1.0in. X 1.2. (25,4mm x 30,48mm)

Gewicht: 3g.