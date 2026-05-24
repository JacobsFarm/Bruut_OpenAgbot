include <../config/parameters.scad>

module caster_wheel_axle() {
    color("silver") {
        rotate([90, 0, 0]) {
            cylinder(
                h = caster_wheel_axle_width, 
                d = caster_wheel_axle_diameter, 
                center = true, 
                $fn = 64 // Zorgt voor een mooie, gladde ronde cilinder
            );
        }
    }
}

caster_wheel_axle();