include <../config/parameters.scad>

module main_base_plate() {
    // Bereken de minimale en maximale posities van de gaten
    min_hole_y = (base_length_min / 2) - (bracket_top_hole_dist_y / 2);
    max_hole_y = (base_length_max / 2) + (bracket_top_hole_dist_y / 2);

    difference() {
        // De solide basisplaat
        cube([bracket_total_width, base_plate_length, connect_plate_thick], center=true);

        // Modulair Gatenpatroon over de Y-as
        // Loopt in stappen van 40mm (grid_step) net als de balken
        for(y = [min_hole_y : grid_step : max_hole_y]) { 
            // Plaats de gaten op de juiste breedte (X-as)
            for(bx = [-1, 1]) {
                hole_x = bx * (bracket_top_hole_dist_x / 2);
                
                // Gaten voorkant
                translate([hole_x, y, 0])
                    cylinder(d=bolt_dia, h=connect_plate_thick + 10, center=true);
                
                // Gaten achterkant (gespiegeld)
                translate([hole_x, -y, 0])
                    cylinder(d=bolt_dia, h=connect_plate_thick + 10, center=true);
            }
        }
    }
}

// Preview van de base plate
main_base_plate();