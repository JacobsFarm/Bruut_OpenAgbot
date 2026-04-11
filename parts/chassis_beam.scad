include <../config/parameters.scad>

module chassis_beam() {
    difference() {
        cube([beam_length, beam_profile, beam_profile], center=true);
        // Hollow interior
        cube([beam_length + 1, beam_profile - (2*beam_thickness), beam_profile - (2*beam_thickness)], center=true);
        
        // Drill patterns based on configuration
        for(optie_width = drill_pattern_widths) { 
            for(x_dir = [-1, 1]) {
                module_center_x = x_dir * (optie_width / 2);
                for(bx = [-1, 1]) {
                    hole_x = module_center_x + (bx * (bracket_total_width/3)); 
                    translate([hole_x, 0, 0])
                        cylinder(d=bolt_dia, h=beam_profile + 10, center=true);
                }
            }
        }
    }
}

// Preview
chassis_beam();