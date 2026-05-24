include <config/parameters.scad>

use <assemblies/wheel_unit_asm.scad>
use <assemblies/chassis_frame_asm.scad>
use <parts/chassis_beam_1.scad>

module bruut_agbot_full() {
    
    // --- NIEUW: Auto-Grid Uitlijning ---
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
    
    z_pos = bracket_top_z + (beam_profile/2);
    
    // --- GECORRIGEERD: Balk-Offset ---
    // In plaats van delen door 3, gebruiken we nu de vaste gatenafstand over de Y-as
    bolt_offset_y = bracket_top_hole_dist_y / 2;

    // 2. Plaats de onderste dwarsbalken over de X-as
    translate([0, 0, exploded_view ? explosion_dist : 0]) {
        for(y_as = [-align_length/2, align_length/2]) {
            for(koker_y_offset = [-bolt_offset_y, bolt_offset_y]) {
                translate([0, y_as + koker_y_offset, z_pos])
                    chassis_beam_1(); // <-- Gecorrigeerd naar _1
            }
        }
    }
    
    // 3. Plaats de rest van het frame
    chassis_frame_asm();
}

bruut_agbot_full();