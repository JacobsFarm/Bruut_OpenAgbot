#include <Adafruit_MCP4728.h>
#include <Wire.h>

Adafruit_MCP4728 mcp;

void setup() {
  Serial.begin(115200);
  
  // Start I2C communicatie met de MCP4728
  if (!mcp.begin()) {
    Serial.println("Fout: MCP4728 DAC module niet gevonden!");
    while (1) {
      delay(10); // Stop het programma als de module niet gevonden wordt
    }
  }

  // Zet de startwaarde op 'uit' (700 = ~0.77V) voor Kanaal A en B
  // We gebruiken VDD (5V) als referentievoltage om hetzelfde bereik te houden
  mcp.setChannelValue(MCP4728_CHANNEL_A, 700, MCP4728_VREF_VDD, MCP4728_GAIN_1X);
  mcp.setChannelValue(MCP4728_CHANNEL_B, 700, MCP4728_VREF_VDD, MCP4728_GAIN_1X);
  
  Serial.println("Systeem gestart (Dual Motor MCP4728). Wacht op commando's...");
}

void loop() {
  // Controleer of er data is ontvangen (Format: "Links,Rechts\n")
  if (Serial.available() > 0) {
    
    // Lees de twee inkomende getallen gescheiden door een komma
    int dacLinks = Serial.parseInt();
    int dacRechts = Serial.parseInt();

    // Lees de 'newline' character of overgebleven data uit de buffer
    while(Serial.available() > 0) {
      char c = Serial.read();
      if (c == '\n') break;
    }

    // Filter de werkbereiken voor het LINKER wiel
    if (dacLinks >= 700 && dacLinks <= 3100) {
      mcp.setChannelValue(MCP4728_CHANNEL_A, dacLinks, MCP4728_VREF_VDD, MCP4728_GAIN_1X);
    }
    
    // Filter de werkbereiken voor het RECHTER wiel
    if (dacRechts >= 700 && dacRechts <= 3100) {
      mcp.setChannelValue(MCP4728_CHANNEL_B, dacRechts, MCP4728_VREF_VDD, MCP4728_GAIN_1X);
    }
  }
}