include <../config/parameters.scad>

module chassis_beam_2() {
    // Bereken de minimale en maximale posities van de gaten
    min_hole_y = (chassis_length_min / 2) - (bracket_top_hole_dist_y / 2);
    max_hole_y = (chassis_length_max / 2) + (bracket_top_hole_dist_y / 2);
    
    difference() {
        // Basis kokerbalk voor de lengterichting
        cube([beam_length_2, beam_profile, beam_profile], center=true);
        
        // Holle binnenkant
        cube([beam_length_2 + 1, beam_profile - (2*beam_thickness), beam_profile - (2*beam_thickness)], center=true);

        // Modulair Gatenpatroon over de Y-as (boven en onder)
        // Loopt perfect in stappen van 40mm (grid_step)
        for(y = [min_hole_y : grid_step : max_hole_y]) { 
            // Gaten aan de bovenkant
            translate([y, 0, 0])
                cylinder(d=bracket_bolt_diameter, h=beam_profile + 10, center=true);
            
            // Gaten aan de onderkant (gespiegeld)
            translate([-y, 0, 0])
                cylinder(d=bracket_bolt_diameter, h=beam_profile + 10, center=true);
        }
    }
}

// Preview van de lengtebalk
chassis_beam_2();