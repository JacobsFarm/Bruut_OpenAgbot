include <../config/parameters.scad>

module bracket_side_plate() {
    tip_radius = axle_dia * 2.8;
    color("#A0A0A0") { 
        difference() {
            hull() { 
                translate([0, 0, arm_height]) 
                    cube([bracket_thick, side_plate_top_width, 0.1], center=true);
                rotate([0, 90, 0]) 
                    cylinder(r=tip_radius, h=bracket_thick, center=true);
            }
            rotate([0, 90, 0]) {
                // Axle hole
                cylinder(d=axle_dia + 1, h=bracket_thick + 2, center=true); 
                // Mounting notch
                translate([tip_radius/2, 0, 0])
                    cube([tip_radius, axle_dia + 1, bracket_thick + 2], center=true);
            }
        }
    }
}

// Preview
bracket_side_plate();