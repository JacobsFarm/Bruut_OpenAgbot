include <../config/parameters.scad>

module main_base_plate() {
    difference() {
        cube([bracket_total_width, base_plate_length, connect_plate_thick], center=true);
        for(optie_len = drill_pattern_lengths, y_dir = [-1, 1]) {
            translate([0, y_dir * (optie_len / 2), 0])
                for(bx = [-1, 1], by = [-1, 1])
                    translate([bx * (bracket_total_width/3), by * (side_plate_top_width/3), 0])
                        cylinder(d=bolt_dia, h=connect_plate_thick + 10, center=true);
        }
    }
}