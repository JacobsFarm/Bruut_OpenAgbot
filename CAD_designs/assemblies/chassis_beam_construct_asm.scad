include <../config/parameters.scad>
use <../parts/bracket_top_plate.scad>
use <../parts/chassis_beam_1.scad>
use <../parts/chassis_beam_2.scad>

module chassis_beam_construct_asm(
    toon_brackets = false, 
    toon_onderste_balken = true, 
    toon_bovenste_balken = true
) {
    // Z-hoogtes berekenen zodat de delen netjes op elkaar stapelen
    z_bracket_top = bracket_thick / 2;
    z_bottom_beams = z_bracket_top + (beam_profile / 2);
    z_top_beams = z_bottom_beams + beam_profile;

    // 1. Plaats de 4 bracket_top_plates direct op de hoeken
    if (toon_brackets) {
        for (x = [-chassis_width/2, chassis_width/2]) {
            for (y = [-chassis_length/2, chassis_length/2]) {
                translate([x, y, 0])
                    color("darkgray") 
                    bracket_top_plate();
            }
        }
    }

    // 2. Plaats de 4 onderste balken (Breedte / X-as)
    if (toon_onderste_balken) {
        for (y_center = [-chassis_length/2, chassis_length/2]) {
            for (y_offset = [-bracket_top_hole_dist_y/2, bracket_top_hole_dist_y/2]) {
                translate([0, y_center + y_offset, z_bottom_beams])
                    color("silver")
                    chassis_beam_1(); 
            }
        }
    }

    // 3. Plaats de 4 bovenste balken (Lengterichting / Y-as)
    if (toon_bovenste_balken) {
        for (x_center = [-chassis_width/2, chassis_width/2]) {
            for (x_offset = [-bracket_top_hole_dist_x/2, bracket_top_hole_dist_x/2]) {
                translate([x_center + x_offset, 0, z_top_beams])
                    rotate([0, 0, 90])
                    color("dimgray")
                    chassis_beam_2(); 
            }
        }
    }
}

// Previews
chassis_beam_construct_asm();