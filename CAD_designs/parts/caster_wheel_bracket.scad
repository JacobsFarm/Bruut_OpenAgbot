include <../config/parameters.scad>

// Nieuwe parameter voor het as-gat
bracket_axle_hole_diameter = 10.4;

module caster_wheel_bracket() {
    // Bovenplaat valt precies tussen de zijplaten
    top_plate_width = caster_wheel_axle_width;
    
    // Basis hoogte van de poten (gemeten vanaf as op Z=0 tot onderkant bovenplaat)
    base_leg_height = axle_hole_distance + (tire_dia / 2) + tire_clearance;
    
    // Totale hoogte van de zijplaten (inclusief overlap met de bovenplaat)
    leg_height      = base_leg_height + bracket_thickness;
    
    // Z-posities
    leg_z_center    = -axle_hole_distance + (leg_height / 2);
    top_plate_z     = (tire_dia / 2) + tire_clearance + (bracket_thickness / 2);

    color("#555555") {
        difference() {
            // Het massieve model (bovenplaat en zijplaten samen)
            union() {
                // Bovenplaat
                translate([0, 0, top_plate_z])
                    cube([top_plate_width, bracket_width, bracket_thickness], center=true);

                // Zijplaten
                for (i = [-1, 1]) {
                    translate([i * (caster_wheel_axle_width / 2 + bracket_thickness / 2), 0, leg_z_center])
                        cube([bracket_thickness, bracket_width, leg_height], center=true);
                }
            }
            
            // Enkel de gaten voor de as, precies door de zijplaten (Z=0)
            for (i = [-1, 1]) {
                translate([i * (caster_wheel_axle_width / 2 + bracket_thickness / 2), 0, 0])
                    rotate([0, 90, 0])
                        // h = bracket_thickness + 2 (voor een schone snede aan beide kanten)
                        cylinder(d = bracket_axle_hole_diameter, h = bracket_thickness + 5, center = true);
            }
        }
    }
}

// Test render (verwijder of comment uit bij gebruik in assembly)
caster_wheel_bracket();