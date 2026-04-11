include <../config/parameters.scad>

module bracket_top_plate() {
    difference() {
        cube([bracket_total_width, side_plate_top_width, bracket_thick], center=true);
        for(x = [-1, 1], y = [-1, 1]) {
            translate([x * (bracket_total_width/3), y * (side_plate_top_width/3), 0])
                cylinder(d=bolt_dia, h=bracket_thick + 10, center=true); 
        }
    }
}

// Preview
bracket_top_plate();