include <../config/parameters.scad>

module caster_wheel_pivot_cilinder() {
    color("grey") {
        cylinder(h=pivot_cylinder_height, d=pivot_cylinder_dia, center=true, $fn=50);
    }
}

// Test render (verwijder of comment uit bij gebruik in assembly)
caster_wheel_pivot_cilinder();