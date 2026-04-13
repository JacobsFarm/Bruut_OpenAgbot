// ==========================================
// LOCAL TEMPLATE CONFIG (Hardcoded)
// ==========================================
tpl_width = 80;        // Wider than the hole spacing (axle_hole_distance is 30)
tpl_height = 55;       // Tall enough to cover the axle slot and holes
tpl_thickness = 5;     // Thickness of the 3D-printed template
tpl_clearance = 0.3;   // Extra tolerance so drill/bolt does not bind in plastic
bottom_slot = 10;      // 10 for an open bottom or 8 or lower for an closed bottom

// DEBUG MODE - Set to 'false' before exporting STL
show_reference = true; 

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>; 
use <../parts/bracket_side_plate.scad>;

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module drill_template() {
    difference() {
        union() {
            translate([(bracket_thick / 2) + (tpl_thickness / 2), 0, -10])
                cube([tpl_thickness, tpl_width, tpl_height], center=true);
            
            translate([tpl_thickness / 2, 0, -axle_bottom_dist - (tpl_thickness / 2)])
                cube([bracket_thick + tpl_thickness, tpl_width, tpl_thickness], center=true);
        }

        rotate([0, 90, 0]) {
            
            translate([-5, 0, 0]) 
                cylinder(d = axle_dia + tpl_clearance, h = 50, center = true, $fn = 64);
            
            translate([axle_bottom_dist / 2, 0, 0])
                cube([axle_bottom_dist + bottom_slot, axle_dia + tpl_clearance, 50], center = true);

            translate([0, axle_hole_distance, 0])
                cylinder(d = axle_hole_diameter + tpl_clearance, h = 50, center = true, $fn = 64);

            translate([0, -axle_hole_distance, 0])
                cylinder(d = axle_hole_diameter + tpl_clearance, h = 50, center = true, $fn = 64);
        }
    }
}

// ==========================================
// RENDER
// ==========================================

color("DodgerBlue") {
    drill_template();
}

if (show_reference) {
    %bracket_side_plate(); 
}
