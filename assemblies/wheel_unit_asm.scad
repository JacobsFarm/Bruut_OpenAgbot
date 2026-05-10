// --- Show/Hide Toggles ---
show_motor    = true;
show_top      = true;
show_sides    = true;
show_brackets = true;

// Use 'use' for parts to prevent them from rendering at the origin automatically
use <../parts/bracket_side_plate.scad>
use <../parts/bracket_top_plate.scad>
use <../parts/axle_bracket.scad> 

// Use 'include' for parameters so the variables are available in this script
include <../config/parameters.scad>

module wheel_unit_asm() {
    // 1. Hub Motor & Rings Import
    if (show_motor) {
        color("#555555") { 
            rotate([90, 0, 180]) {
                // Main Motor Body
                translate([-97.5, 0, 0]) 
                    import("../imports/hubmotor_quinder.stl", convexity=3);

                // Left Ring
                translate([-97.5, 0, 0]) 
                    import("../imports/hubmotor_quinder_ring_left.stl", convexity=3);

                // Right Ring
                translate([-97.5, 0, 0]) 
                    import("../imports/hubmotor_quinder_ring_right.stl", convexity=3);
            }
        }
    }

    // 2. Bracket Assembly
    translate([0, 0, exploded_view ? explosion_dist * 0.5 : 0]) {
        
        // Top Plate
        if (show_top) {
            translate([0, 0, arm_height + bracket_thick/2])
                bracket_top_plate();
        }

        // Side Plates & Axle Brackets
        for(i = [-1, 1]) {
            // 1. De standaard zijplaten van de bracket
            if (show_sides) {
                translate([i * (inner_width/2 + bracket_thick/2), 0, 0])
                rotate([0, 0, (i == 1) ? 180 : 0])
                    bracket_side_plate(show_bend = true); 
            }

            // 2. Axle Brackets (Hexagon plaatjes)
            if (show_brackets) {
                // Gebruik nu axle_bracket_thickness in de translate
                translate([i * (inner_width/2 + bracket_thick + axle_bracket_thickness/2), 0, 0])
                    axle_bracket_part();
            }
        }
    }
}

// Render the assembly
wheel_unit_asm();