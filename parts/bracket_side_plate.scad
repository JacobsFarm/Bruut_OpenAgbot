include <../config/parameters.scad>

bracket_side_plate(show_bend = false, bend_angle = 90);

module bracket_side_plate(show_bend = true, bend_angle = 90) {
    h_total = arm_height + axle_bottom_dist;
    z_center = (arm_height - axle_bottom_dist) / 2;
    
    y_center_width = side_plate_width - (2 * extra_space_bracket);

    color("#A0A0A0") {
        difference() {
            if (show_bend) {
                union() {
                    translate([0, 0, z_center])
                        cube([bracket_thick, y_center_width, h_total], center=true);

                    translate([0, y_center_width / 2, z_center])
                        rotate([0, 0, bend_angle])
                            translate([0, extra_space_bracket / 2, 0])
                                cube([bracket_thick, extra_space_bracket, h_total], center=true);

                    translate([0, -y_center_width / 2, z_center])
                        rotate([0, 0, -bend_angle])
                            translate([0, -extra_space_bracket / 2, 0])
                                cube([bracket_thick, extra_space_bracket, h_total], center=true);

                    for (y = [-1, 1]) {
                        translate([0, y * tab_offset_y, arm_height + (bracket_thick / 2)])
                            cube([bracket_thick, tab_length, bracket_thick], center=true);
                    }
                }
            } else {
                union() {
                    hull() { 
                        translate([0, 0, arm_height]) 
                            cube([bracket_thick, side_plate_width, 0.1], center=true);
                        translate([0, 0, -axle_bottom_dist])
                            cube([bracket_thick, side_plate_width, 0.1], center=true);
                    }
                    
                    for (y = [-1, 1]) {
                        translate([0, y * tab_offset_y, arm_height + (bracket_thick / 2)])
                            cube([bracket_thick, tab_length, bracket_thick], center=true);
                    }
                }
            }

            rotate([0, 90, 0]) {
                translate([-5, 0, 0]) 
                    cylinder(d = axle_dia, h = bracket_thick + 10, center = true);
                translate([axle_bottom_dist / 2, 0, 0])
                    cube([axle_bottom_dist + 8, axle_dia, bracket_thick + 10], center = true);
            }

            rotate([0, 90, 0]) {
                translate([0, axle_hole_distance, 0])
                    cylinder(d = axle_hole_diameter, h = bracket_thick + 10, center = true);
                translate([0, -axle_hole_distance, 0])
                    cylinder(d = axle_hole_diameter, h = bracket_thick + 10, center = true);
            }

            for (z_pos = [-axle_bottom_dist + side_hole_start_from_bottom : side_hole_pitch : arm_height - side_hole_start_from_bottom]) {
                
                if (show_bend) {
                    translate([0, y_center_width / 2, 0])
                        rotate([0, 0, bend_angle])
                            translate([0, extra_space_bracket / 2, z_pos])
                                rotate([0, 90, 0])
                                    cylinder(d = bracket_bolt_diameter, h = bracket_thick + 20, center = true);
                    
                    translate([0, -y_center_width / 2, 0])
                        rotate([0, 0, -bend_angle])
                            translate([0, -extra_space_bracket / 2, z_pos])
                                rotate([0, 90, 0])
                                    cylinder(d = bracket_bolt_diameter, h = bracket_thick + 20, center = true);
                } else {
                    translate([0, y_center_width / 2 + extra_space_bracket / 2, z_pos])
                        rotate([0, 90, 0])
                            cylinder(d = bracket_bolt_diameter, h = bracket_thick + 20, center = true);
                    
                    translate([0, -(y_center_width / 2 + extra_space_bracket / 2), z_pos])
                        rotate([0, 90, 0])
                            cylinder(d = bracket_bolt_diameter, h = bracket_thick + 20, center = true);
                }
            }
        }
    }
}
