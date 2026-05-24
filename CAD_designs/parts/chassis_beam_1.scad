include <../config/parameters.scad>

module chassis_beam_1() {
    // Genereert automatisch de lijst met gewenste breedtes
    gewenste_breedtes = [chassis_width_min : chassis_width_step : chassis_width_max];
    
    difference() {
        // Basis kokerbalk
        cube([beam_length_1, beam_profile, beam_profile], center=true);
        
        // Holle binnenkant
        cube([beam_length_1 + 1, beam_profile - (2*beam_thickness), beam_profile - (2*beam_thickness)], center=true);

        // Loop over de automatisch gegenereerde breedtes
        for(optie_width = gewenste_breedtes) { 
            for(x_dir = [-1, 1]) {
                module_center_x = x_dir * (optie_width / 2);
                
                // Plaats de 2 gaten per kant (uitgelijnd op de topplaat X-as)
                for(bx = [-1, 1]) {
                    hole_x = module_center_x + (bx * (bracket_top_hole_dist_x / 2));
                    
                    translate([hole_x, 0, 0])
                        cylinder(d=bolt_dia, h=beam_profile + 10, center=true);
                }
            }
        }
    }
}

// Preview
chassis_beam_1();