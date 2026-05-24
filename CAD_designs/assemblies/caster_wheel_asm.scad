// --- Show/Hide Toggles ---
show_wheel           = true;
show_bracket         = true;
show_pivot           = true; 
show_outer_cylinder  = true; 
show_horizontal_tube = true;
show_axle            = true; // Nieuwe toggle voor de as

use <../parts/caster_wheel_bracket.scad>
use <../parts/caster_wheel_pivot_cilinder.scad>
use <../parts/caster_wheel_outer_cilinder.scad>
use <../parts/caster_wheel_beam.scad>
use <../parts/caster_wheel_axle.scad>

include <../config/parameters.scad>

module caster_wheel_asm() {
    if (show_wheel) {
        color("#333333") {
            import("../imports/wheelbarrow_wheel_4.8_4.00-8.stl", convexity=3);
        }
    }

    // --- Toevoeging: De As ---
    if (show_axle) {
        rotate([0, 0, 90])
        caster_wheel_axle(); 
    }

    if (show_bracket) {
        caster_wheel_bracket();
    }

    top_surface_z = (tire_dia / 2) + tire_clearance + bracket_thickness;
    
    if (show_pivot) {
        pivot_z_center = top_surface_z + (pivot_cylinder_height / 2);
        translate([0, 0, pivot_z_center])
            caster_wheel_pivot_cilinder();
    }
    
    outer_z_center = top_surface_z + outer_cylinder_z_offset + (outer_cylinder_height / 2);
    
    if (show_outer_cylinder) {
        translate([0, 0, outer_z_center])
            caster_wheel_outer_cilinder();
    }
    
    if (show_horizontal_tube) {
        translate([0, tube_length / 2, outer_z_center])
            rotate([0, 0, 90])
                caster_wheel_beam();
    }
}

caster_wheel_asm();