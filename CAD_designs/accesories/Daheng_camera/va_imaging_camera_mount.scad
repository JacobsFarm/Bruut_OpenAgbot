// STL Import
show_center_import = false;

center_pos = [329, 44, -269.5];
center_rot = [0, 0, 0];

if (show_center_import) {
    translate(center_pos)
        rotate(center_rot)
            import("VEN-161-61U3C-M01.stl");
}

// Hole Settings
hole_spacing = 20;
hole1_pos = [40, 2, 5];

// Wall Module
module wall(thickness = 4, height = 46, width = 70) {
    difference() {
        cube([width, thickness, height]);
        
        // Base hinge hole
        translate(hole1_pos)
            rotate([-90, 0, 0])
                cylinder(h = thickness + 2, d = 3.5, center = true, $fn = 50);
        
        // Arc holes (0, 15, 30, 45 deg)
        for (angle = [0, 15, 30, 45]) {
            hole_pos = [
                hole1_pos[0] + (hole_spacing * cos(angle)),
                hole1_pos[1],
                hole1_pos[2] + (hole_spacing * sin(angle))
            ];
            
            translate(hole_pos)
                rotate([-90, 0, 0])
                    cylinder(h = thickness + 2, d = 3.5, center = true, $fn = 50);
        }
    }
}

wall_pos = [-35, 17.3, -25];
wall2_pos = [-35, -18.3, -25];

translate(wall_pos)
    wall();

translate(wall2_pos)
    mirror([0, 1, 0])
        wall();

// Plate Module (Aangepast met 9 gaten: 3 in de breedte x 3 in de lengte)
module plate(width = 70, length = 80, thickness = 4, hole_dia = 5.4, edge_margin = 10) {
    difference() {
        cube([width, length, thickness]);
        
        // 3 gaten in de X-richting, 3 gaten in de Y-richting (totaal 9)
        for (x = [edge_margin, width / 2, width - edge_margin]) {
            for (y = [edge_margin, length / 2, length - edge_margin]) {
                translate([x, y, -1])
                    cylinder(h = thickness + 2, d = hole_dia, $fn = 50);
            }
        }
    }
}

plate_pos = [-35, -40, 20];
translate(plate_pos)
    plate();

// Backplate Module
module back_plate(thickness = 4, height = 49, width = 80, hole_dia = 5.4, edge_margin = 10) {
    difference() {
        cube([thickness, width, height]);
        
        for (y = [edge_margin, width / 2, width - edge_margin]) {
            for (z = [edge_margin, (height / 2), height - edge_margin]) {
                translate([-1, y, z])
                    rotate([0, 90, 0])
                        cylinder(h = thickness + 2, d = hole_dia, $fn = 50);
            }
        }
    }
}

backplate_pos = [-35, -40, -25];
translate(backplate_pos)
    back_plate();
