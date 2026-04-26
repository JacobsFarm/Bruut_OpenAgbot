The MCP4728 is a compact module featuring four 12-bit Digital-to-Analog Converters (DACs), ideal for precise voltage setting requirements. This module is compatible with STEMMA QT and Qwiic connectors for easy "plug-and-play" integration via I2C.

## Key Features

* **Quad 12-bit Outputs:** Four independent buffered voltage output DACs.
* **Non-Volatile Memory (EEPROM):** Ability to store DAC settings and I2C address bits in internal EEPROM. Saved settings are automatically loaded as defaults upon power-up.
* **Flexible Reference Voltage:** Choose between the input supply voltage (VCC) or an internal reference of 2.048V.
* **Adjustable Gain:** When using the internal reference, you can select 1X or 2X gain.
* **Fast Response:** Typical settling time of 6 μs.
* **I2C Interface:** Fully controllable via I2C with a default address of `0x60`.

## Technical Specifications

| Feature | Specification |
| :--- | :--- |
| **Resolution** | 12-bit  |
| **Operating Voltage** | 2.7 V to 5.5 V  |
| **Settling Time** | 6 μs (typical) |
| **Differential Non-Linearity (DNL)** | ±0.2 LSB (typical) |
| **Default I2C Address** | 0x60  |

## Voltage Output Ranges

The output voltage range depends on the selected reference voltage (Vref) and gain settings:

* **Internal VREF (2.048V):**
    * **Gain = 1:** 0.000V to 2.048V[.
    * **Gain = 2:** 0.000V to 4.096V (Ideal for ~5V applications).
* **External VREF (VDD/VCC):**
    * 0.000V to VDD (Allows matching the input voltage range, e.g., 3.3V or 5V)

## Pinout Overview

The module features several connection points for integration:
* **VCC:** Power supply (2.7V - 5.5V).
* **GND:** Ground.
* **SCL/SDA:** I2C Clock and Data lines.
* **VA, VB, VC, VD:** The four DAC output channels.
* **RDY:** Ready pin.
* **LDAC:** Latch DAC Synchronization pin.
"""
