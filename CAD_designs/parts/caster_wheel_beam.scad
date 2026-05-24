include <../config/parameters.scad>

module caster_wheel_beam() {
    color("#225522") {
        difference() {
            // Buitenmaat koker
            cube([tube_length, tube_width, tube_width], center=true);
            
            // Binnenmaat (uitsnede voor de wanddikte)
            inner_size = tube_width - (2 * tube_thickness);
            cube([tube_length + 2, inner_size, inner_size], center=true);

            // Gatenpatroon over de X-as
            for (x = [-tube_length/2 + grid_step : grid_step : tube_length/2 - grid_step]) {
                
                // DE LOGICA: Plaats de gaten alleen aan de ANDERE kant (rechterkant).
                // We plaatsen gaten vanaf (rechterkant - de minimum lengte) tot aan de rand.
                if (x >= tube_length/2 - tube_length_min) {
                    
                    // Gaten verticaal door de koker
                    translate([x, 0, 0])
                        cylinder(d=bracket_bolt_diameter, h=tube_width + 10, center=true);
                }
            }
        }
    }
}

// Test render (verwijder of comment uit bij gebruik in assembly)
caster_wheel_beam();