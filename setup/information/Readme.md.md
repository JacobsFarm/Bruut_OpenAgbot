draden van de controller naar de gashendel

Rood = +5V
Wit = GND
Blauw = signaal (0.8–3.5V)
(moet worden gecheckt)

rood wit is verschil +-5 volt (specs gelezen)
bij test geven rood  - wit 4.36 volt

blauw wit +-0.8 volt of volgas 3.5 volt (specs gelezen)
bij test geven onderling wit - blauw voltage van 0.8 tot 3.5
Bij uit geeft de 0.8 volt en bij volgas geeft die 3.5 voltage
Er is geen verschil tussen de standen low, mid en high

Arduino dac waardes code bij (DAC waarden op basis van 12-bit resolutie: 0-4095)
analogWrite(A0, 700); = 0.77 volt
analogWrite(A0, 2500); = 2.8 volt 
analogWrite(A0, 3100); = 3.4 volt

De draden zijn zo verbonden

Rood gaat gewoon naar de controller toe, blijft heel
Blauw is het signaaldraad deze gaat naar de A0 draad van de arduino
Wit is het GND draad deze gaat naar de GND van de arduino

Draden van de handgas naar de controller
Rood = 5 volt draad uit test 4.36V = heel laten gaat niet naar de arduino
Blauw = signaaldraad (0.8–3.5V) = A0 arduino
Wit = GND = GND arduino
zwart
oranje
bruin
groen
geel

Draden van de vooruit achteruit naar de controller
rood
geel
lichtblauw
groen

De DAC module MCP4728
Met de DAC Module worden onafhankelijk voor het linker en rechterwiel via het signaal draad blauw en het witte GND nageboots.
Hier is het complete en overzichtelijke aansluitschema voor je Arduino, de MCP4728 DAC-module en de motorcontrollers van de wielen.

1. Arduino ➔ MCP4728 DAC-module (I2C Communicatie)

Dit is de verbinding om de module van stroom te voorzien en de data (de commando's vanuit Python) door te geven. Je gebruikt de pinnen aan de onderkant van het bordje (waar SDA en SCL bij staan):

    Arduino 5V ➔ VCC (of VDD) op de DAC-module
    Arduino GND ➔ GND op de DAC-module
    Arduino SCL (A5) ➔ SCL op de DAC-module (Kloksignaal)
    Arduino SDA (A4) ➔ SDA op de DAC-module (Datasignaal)

2. MCP4728 DAC-module ➔ Motorcontrollers (Het Signaal)
Dit is de verbinding die de analoge spanning (0.77V - 3.4V) naar de motoren stuurt, ter vervanging van de fysieke gashendel. Je gebruikt de uitgangen aan de bovenkant (VA, VB, etc.):

    VA (Kanaal A) ➔ Blauwe signaaldraad van het Linker wiel
    VB (Kanaal B) ➔ Blauwe signaaldraad van het Rechter wiel
    GND ➔ Witte GND-draad van BEIDE wielen

Gebruik maken van de UBX informatie ipv de NEMEA berichten 