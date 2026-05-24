include <../config/parameters.scad>

module chassis_beam_2() {
    // Genereert automatisch de lijst met gewenste lengtes
    gewenste_lengtes = [chassis_length_min : chassis_length_step : chassis_length_max];
    
    difference() {
        // Basis kokerbalk voor de lengterichting
        cube([beam_length_2, beam_profile, beam_profile], center=true);
        
        // Holle binnenkant
        cube([beam_length_2 + 1, beam_profile - (2*beam_thickness), beam_profile - (2*beam_thickness)], center=true);

        // Loop over de automatisch gegenereerde lengtes
        for(optie_length = gewenste_lengtes) { 
            for(y_dir = [-1, 1]) {
                module_center_y = y_dir * (optie_length / 2);
                
                // Plaats de 2 gaten per kant (uitgelijnd op de topplaat Y-as)
                for(by = [-1, 1]) {
                    hole_y = module_center_y + (by * (bracket_top_hole_dist_y / 2));
                    
                    translate([hole_y, 0, 0])
                        cylinder(d=bolt_dia, h=beam_profile + 10, center=true);
                }
            }
        }
    }
}

// Preview van de lengtebalk
chassis_beam_2();