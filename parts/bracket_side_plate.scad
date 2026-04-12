include <../config/parameters.scad>

module bracket_side_plate() {
    color("#A0A0A0") {
        difference() {
            hull() { 
                translate([0, 0, arm_height]) 
                    cube([bracket_thick, side_plate_top_width, 0.1], center=true);
                translate([0, 0, -axle_bottom_dist])
                    cube([bracket_thick, side_plate_bottom_width, 0.1], center=true);
            }

            rotate([0, 90, 0]) {
                translate([-5, 0, 0]) 
                    cylinder(d = axle_dia, h = bracket_thick + 2, center = true);
                translate([axle_bottom_dist / 2, 0, 0])
                    cube([axle_bottom_dist + 8, axle_dia, bracket_thick + 2], center = true);
            }

            rotate([0, 90, 0]) {
                translate([0, axle_hole_distance, 0])
                    cylinder(d = axle_hole_diameter, h = bracket_thick + 2, center = true);
                translate([0, -axle_hole_distance, 0])
                    cylinder(d = axle_hole_diameter, h = bracket_thick + 2, center = true);
            }
        }
    }
}

bracket_side_plate();