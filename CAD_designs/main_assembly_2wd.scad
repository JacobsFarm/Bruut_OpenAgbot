include <config/parameters.scad>

use <assemblies/wheel_unit_asm.scad>
use <assemblies/caster_wheel_asm.scad>
use <assemblies/chassis_beam_construct_asm.scad>
use <assemblies/chassis_frame_asm.scad>

module bruut_agbot_full() {
    
    // ==========================================
    // --- ONAFHANKELIJKE ZWENKWIELEN (VOOROP) ---
    // Pas de X, Y en Z in de translate aan 
    // om de voorste wielen vrij te verplaatsen.
    // ==========================================
    
    // 1. Zwenkwiel Linksvoor (Nu verplaatst in veelvouden van 50mm)
    translate([-chassis_width/2 - 50, chassis_length/2 + 275, 0]) {
        rotate([0, 0, 180]) 
            caster_wheel_asm();
    }

    // 2. Zwenkwiel Rechtsvoor (Nu verplaatst in veelvouden van 50mm)
    translate([chassis_width/2 + 50, chassis_length/2 + 200, 0]) {
        rotate([0, 0, 180]) 
            caster_wheel_asm();
    }
    
    // 3. Aandrijfwielen (hubmotors) Links & Rechts achter
    for(x_pos = [-chassis_width/2, chassis_width/2]) {
        translate([x_pos, -chassis_length/2, 0])
            wheel_unit_asm();
    }
    
    // ==========================================
    
    // 4. Plaats de volledige chassis balken-constructie
    translate([0, 0, bracket_top_z]) {
        chassis_beam_construct_asm();
    }
    
    // 5. Plaats het chassis frame (dynamisch verhoogd zodat het exact óp de kokers ligt)
    translate([0, 0, beam_profile + (bracket_thick / 2)]) {
        chassis_frame_asm();
    }
}

bruut_agbot_full();