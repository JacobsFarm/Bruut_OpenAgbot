include <config/parameters.scad>

use <assemblies/wheel_unit_asm.scad>
use <assemblies/caster_wheel_asm.scad>
use <assemblies/chassis_beam_construct_asm.scad>
use <assemblies/chassis_frame_asm.scad>

module bruut_agbot_full() {
    
    // --- Auto-Grid Uitlijning ---
    // Forceert de breedte en lengte naar een veelvoud van 80, 
    // zodat de wielen altijd 100% uitlijnen met het 40mm gatenpatroon.
    align_width = round(chassis_width / 80) * 80;
    align_length = round(chassis_length / 80) * 80;
    
    // ==========================================
    // --- ONAFHANKELIJKE ZWENKWIELEN (VOOROP) ---
    // Pas de X, Y en Z in de translate aan 
    // om de voorste wielen vrij te verplaatsen.
    // ==========================================
    
    // 1. Zwenkwiel Linksvoor
    translate([-align_width/2 - 40, align_length/2 + 220, 0]) {
        rotate([0, 0, 180]) 
            caster_wheel_asm();
    }

    // 2. Zwenkwiel Rechtsvoor
    translate([align_width/2 + 40, align_length/2 + 220, 0]) {
        rotate([0, 0, 180]) 
            caster_wheel_asm();
    }

    
    // 3. Aandrijfwielen (hubmotors) Links & Rechts achter
    for(x_pos = [-align_width/2, align_width/2]) {
        translate([x_pos, -align_length/2, 0])
            wheel_unit_asm();
    }
    
    // ==========================================
    
    // 4. Plaats de volledige chassis balken-constructie
    translate([0, 0, bracket_top_z]) {
        chassis_beam_construct_asm();
    }
    
    // 5. Plaats het chassis frame (40 mm hoger)
    translate([0, 0, 40]) {
        chassis_frame_asm();
    }
}

bruut_agbot_full();