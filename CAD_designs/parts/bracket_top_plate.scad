include <../config/parameters.scad>

module bracket_top_plate() {
    difference() {
        // Basisplaat
        cube([bracket_total_width, side_plate_top_width, bracket_thick], center=true);

        // Bestaande Bevestigingsgaten (voor montage aan frame)
        for(x = [-1, 1], y = [-1, 1]) {
            translate([x * (bracket_top_hole_dist_x / 2), y * (bracket_top_hole_dist_y / 2), 0])
                cylinder(d=bracket_bolt_diameter, h=bracket_thick + 10, center=true);
        }

        // NIEUW: 4 Sleuven voor de zijplaten
        // GECORRIGEERD: X-positie is nu gebaseerd op inner_width (exact waar de side_plates zitten)
        for (x = [-1, 1], y = [-1, 1]) {
            translate([x * (inner_width / 2 + bracket_thick / 2), y * tab_offset_y, 0])
                cube([bracket_thick + laser_tolerance, tab_length + laser_tolerance, bracket_thick + 10], center=true);
        }
    }
}

// Preview
bracket_top_plate();