include <../config/parameters.scad>

module chassis_beam_1() {
    // Bereken de minimale en maximale posities van de gaten
    min_hole_x = (chassis_width_min / 2) - (bracket_top_hole_dist_x / 2);
    max_hole_x = (chassis_width_max / 2) + (bracket_top_hole_dist_x / 2);
    
    difference() {
        // Basis kokerbalk
        cube([beam_length_1, beam_profile, beam_profile], center=true);
        
        // Holle binnenkant
        cube([beam_length_1 + 1, beam_profile - (2*beam_thickness), beam_profile - (2*beam_thickness)], center=true);

        // Modulair Gatenpatroon over de X-as (links en rechts)
        // Loopt perfect in stappen van 40mm (grid_step)
        for(x = [min_hole_x : grid_step : max_hole_x]) { 
            // Gaten aan de rechterkant
            translate([x, 0, 0])
                cylinder(d=bracket_bolt_diameter, h=beam_profile + 10, center=true);
            
            // Gaten aan de linkerkant (gespiegeld)
            translate([-x, 0, 0])
                cylinder(d=bracket_bolt_diameter, h=beam_profile + 10, center=true);
        }
    }
}

// Preview
chassis_beam_1();