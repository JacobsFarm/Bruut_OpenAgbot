{
  "product": {
    "name": "Venus USB3.0 Industrial Color Camera",
    "part_number": "VEN-161-61U3C-M01",
    "manufacturer": "Daheng Imaging",
    "description": "Compact industrial USB3 Vision camera with Sony IMX296 global shutter sensor."
  },
  "housing_options": [
    {
      "model": "VEN-161-61U3C-M06",
      "housing": "No housing",
      "dimensions_mm": "32.5x32.5x8.1",
      "weight_g": 7
    },
    {
      "model": "VEN-161-61U3C-M05",
      "housing": "M12",
      "dimensions_mm": "35x35x15.1",
      "weight_g": 32
    },
    {
      "model": "VEN-161-61U3C-M01",
      "housing": "CS-mount",
      "dimensions_mm": "35x35x15.8",
      "weight_g": 31
    },
    {
      "model": "VEN-161-61U3C-M01 + 5mm extension ring",
      "housing": "C-Mount",
      "dimensions_mm": "35x35x20.8",
      "weight_g": 34
    }
  ],
  "lens_mount_options": {
    "supported_mounts": ["M12", "CS-mount", "C-Mount"],
    "notes": "M12 lenses can be used directly with the M12 version or with the CS-mount version using a C-to-M12 adapter."
  },
  "specifications": {
    "interface": "USB3 Vision",
    "resolution": {
      "width": 1440,
      "height": 1080
    },
    "megapixel": 2,
    "frame_rate_fps": 61,
    "sensor": {
      "model": "IMX296",
      "size": "1/2.9\"",
      "pixel_size_um": 3.45,
      "type": "Color",
      "shutter_type": "Global Shutter"
    },
    "shutter_time": {
      "min": "52us",
      "max": "1s"
    },
    "adc_bit_depth": 10,
    "pixel_bit_depth": [8, 10],
    "digital_gain_db": {
      "min": 0,
      "max": 24
    },
    "pixel_data_format": [
      "Bayer RG8",
      "Bayer RG10"
    ],
    "synchronization": [
      "Hardware trigger",
      "Software trigger"
    ],
    "io": {
      "input": 1,
      "gpio": 1
    },
    "operating_conditions": {
      "temperature_c": {
        "min": 0,
        "max": 45
      },
      "humidity_percent": {
        "min": 10,
        "max": 80
      }
    },
    "mount": ["S", "C"],
    "dimensions_mm": {
      "cs_m12": "35x35x15.2",
      "no_housing": "32.5x32.5x8.1"
    },
    "sdk_support": [
      "Windows",
      "Linux",
      "Android"
    ],
    "power_consumption": "<2.7W@5V",
    "weight_g": 32,
    "certifications": [
      "RoHS",
      "CE",
      "FCC",
      "USB3 Vision",
      "GenICam"
    ]
  },
  "industrial_color_camera_info": {
    "technology": "Bayer pattern",
    "advantages": [
      "Excellent image quality",
      "Larger and more light-sensitive pixels than webcams and security cameras"
    ],
    "limitations": [
      "Less sharp than monochrome cameras",
      "Lower light sensitivity due to RGB filters"
    ],
    "light_sensitivity_compensation": [
      "Increase ambient light",
      "Increase gain",
      "Increase shutter speed/exposure time",
      "Use a more light-sensitive sensor",
      "Use a more light-sensitive lens"
    ]
  },
  "warranty_and_lifecycle": {
    "annual_production": 100000,
    "certification": "TÜV Rheinland",
    "warranty_years": 3,
    "minimum_product_lifecycle_years": 7
  }
}