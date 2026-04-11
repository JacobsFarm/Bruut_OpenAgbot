include <../config/parameters.scad>

module upright_wall(kant = 1) {
    color("Orange") {
        translate([0, 0, upright_height/2 + connect_plate_thick/2])
            cube([connect_plate_thick, base_plate_length, upright_height], center=true);
        for(y_end = [-1, 1]) {
            difference() {
                hull() {
                    translate([(kant * (top_side_width - connect_plate_thick) / 2), y_end * (base_plate_length/2 - connect_plate_thick/2), upright_height + connect_plate_thick/2])
                        cube([top_side_width, connect_plate_thick, 0.1], center=true);
                    translate([0, y_end * (base_plate_length/2 - connect_plate_thick/2), connect_plate_thick/2])
                        cube([bracket_total_width, connect_plate_thick, 0.1], center=true);
                }
                translate([(kant * 20), y_end * (base_plate_length/2), (upright_height + connect_plate_thick/2) - 30])
                    rotate([90, 0, 0]) cylinder(d=20, h=top_side_width + 50, center=true);
            }
        }
    }
}