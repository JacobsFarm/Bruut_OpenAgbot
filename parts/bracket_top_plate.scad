include <../config/parameters.scad>

module bracket_top_plate() {
    difference() {
        cube([bracket_total_width, side_plate_top_width, bracket_thick], center=true);
        
        for(x = [-1, 1], y = [-1, 1]) {
            // Gebruik hier de waarden uit parameters.scad gedeeld door 2
            translate([x * (bracket_top_hole_dist_x / 2), y * (bracket_top_hole_dist_y / 2), 0])
                cylinder(d=bracket_bolt_diameter, h=bracket_thick + 10, center=true); 
        }
    }
}

// Preview
bracket_top_plate();