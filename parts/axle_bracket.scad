include <../config/parameters.scad>

axle_bracket_part();

module axle_bracket_part() {
    $fn = 100;
    rotate([90, 0, 90]) 
    difference() {
        linear_extrude(height = axle_bracket_thickness, center = true) {
            polygon(points=[
                [axle_hex_width/2,  axle_hex_straight_part/2],  
                [axle_hex_width/2, -axle_hex_straight_part/2],  
                [0,             -axle_hex_height/2],      
                [-axle_hex_width/2, -axle_hex_straight_part/2], 
                [-axle_hex_width/2,  axle_hex_straight_part/2], 
                [0,              axle_hex_height/2]
            ]);
        }

        linear_extrude(height = axle_bracket_thickness + 2, center = true) {
            intersection() {
                circle(d = bolt_dia);
                square([axle_dia, bolt_dia + 2], center = true);
            }
        }

        translate([axle_hole_distance, 0, 0])
            cylinder(d = axle_hole_diameter, h = axle_bracket_thickness + 2, center = true);

        translate([-axle_hole_distance, 0, 0])
            cylinder(d = axle_hole_diameter, h = axle_bracket_thickness + 2, center = true);
    }
}