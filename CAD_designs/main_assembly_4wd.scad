include <config/parameters.scad>

use <assemblies/wheel_unit_asm.scad>
use <assemblies/chassis_beam_construct_asm.scad>
use <assemblies/chassis_frame_asm.scad>

module bruut_agbot_full() {
    
    // --- Auto-Grid Uitlijning (Bulletproof) ---
    // Zorgt ervoor dat het chassis en de wielen perfect op het modulaire gatenpatroon klikken.
    // Omdat we vanuit het midden werken, is de stapgrootte altijd (2 * grid_step).
    // We rekenen vanaf de minimumafmetingen zodat de offset altijd 100% klopt.
    
    stappen_x = round((chassis_width - chassis_width_min) / (2 * grid_step));
    align_width = chassis_width_min + (stappen_x * (2 * grid_step));

    stappen_y = round((chassis_length - chassis_length_min) / (2 * grid_step));
    align_length = chassis_length_min + (stappen_y * (2 * grid_step));

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
    
    // 3. Plaats het chassis frame (dynamisch verhoogd op basis van balk + bracket)
    translate([0, 0, beam_profile + (bracket_thick / 2)]) {
        chassis_frame_asm();
    }
}

bruut_agbot_full();