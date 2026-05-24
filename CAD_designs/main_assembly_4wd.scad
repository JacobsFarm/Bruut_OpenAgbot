include <config/parameters.scad>

use <assemblies/wheel_unit_asm.scad>
use <assemblies/chassis_beam_construct_asm.scad>
use <assemblies/chassis_frame_asm.scad>

module bruut_agbot_full() {
    
    // --- Auto-Grid Uitlijning ---
    // Forceert de breedte en lengte naar een veelvoud van 80, 
    // zodat de wielen altijd 100% uitlijnen met het 40mm gatenpatroon.
    align_width = round(chassis_width / 80) * 80;
    align_length = round(chassis_length / 80) * 80;

    // 1. Plaats de 4 wielunits op de hoeken
    for(x_pos = [-align_width/2, align_width/2]) {
        for(y_pos = [-align_length/2, align_length/2]) {
            translate([x_pos, y_pos, 0])
                wheel_unit_asm();
        }
    }
    
    // 2. Plaats de volledige chassis balken-constructie
    translate([0, 0, bracket_top_z]) {
        chassis_beam_construct_asm();
    }
    
    // 3. Plaats het chassis frame (40 mm hoger)
    translate([0, 0, 40]) {
        chassis_frame_asm();
    }
}

bruut_agbot_full();