include <../config/parameters.scad>

module main_base_plate() {
    // Haalt automatisch je min, max en step(80) op
    gewenste_lengtes = [base_length_min : base_length_step : base_length_max];

    difference() {
        // De solide basisplaat
        cube([bracket_total_width, base_plate_length, connect_plate_thick], center=true);

        // Loop over de ingestelde lengtes
        for(optie_len = gewenste_lengtes) {
            
            // Voor- en achterkant van het chassis bepalen
            for(y_dir = [-1, 1]) {
                module_center_y = y_dir * (optie_len / 2);
                
                // Plaats de 4 gaten per hoek, perfect uitgelijnd op de topplaat
                for(bx = [-1, 1], by = [-1, 1]) {
                    hole_x = bx * (bracket_top_hole_dist_x / 2);
                    hole_y = module_center_y + (by * (bracket_top_hole_dist_y / 2));
                    
                    translate([hole_x, hole_y, 0])
                        cylinder(d=bolt_dia, h=connect_plate_thick + 10, center=true);
                }
            }
        }
    }
}

// Preview van de base plate
main_base_plate();