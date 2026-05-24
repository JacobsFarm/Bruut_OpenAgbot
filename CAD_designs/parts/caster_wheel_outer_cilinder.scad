include <../config/parameters.scad>

module caster_wheel_outer_cilinder() {
    inner_hole_dia = pivot_cylinder_dia + (2 * kap_speling);
    outer_dia = inner_hole_dia + (2 * outer_cylinder_thickness);
    
    color("#993333") {
        difference() {
            cylinder(h=outer_cylinder_height, d=outer_dia, center=true, $fn=50);
            cylinder(h=outer_cylinder_height + 2, d=inner_hole_dia, center=true, $fn=50);
        }
    }
}

caster_wheel_outer_cilinder();