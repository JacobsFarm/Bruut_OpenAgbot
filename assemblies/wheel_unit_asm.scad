include <../config/parameters.scad>
include <../parts/bracket_side_plate.scad>
include <../parts/bracket_top_plate.scad>

module wheel_unit_asm() {
    // Hub Motor (Visualization only)
    color("#555555") { 
        rotate([0, 90, 0]) cylinder(d=tire_dia, h=tire_width, center=true);
        rotate([0, 90, 0]) cylinder(d=hub_dia, h=hub_width, center=true);
    }
    color("Silver") rotate([0, 90, 0]) cylinder(d=axle_dia, h=217, center=true);

    // Assembly of bracket parts
    translate([0, 0, exploded_view ? explosion_dist * 0.5 : 0]) {
        // Top Plate
        translate([0, 0, arm_height + bracket_thick/2])
            bracket_top_plate();
        
        // Side Plates
        for(i = [-1, 1]) {
            translate([i * (inner_width/2 + bracket_thick/2), 0, 0])
                bracket_side_plate();
        }
    }
}

// Preview
wheel_unit_asm();