include <../config/parameters.scad>

module protection_cover(kant = 1) {
    eff_b = bracket_total_width + (2 * cover_clearance);
    eff_l = base_plate_length + (2 * cover_clearance);
    z_start = (connect_plate_thick / 2) - cover_overlap;
    h_wand = cover_total_height - z_start;
    color("Gray", 0.8) translate([0, 0, z_start]) {
        translate([0, 0, h_wand + cover_thick/2])
            cube([eff_b + cover_thick, eff_l + (2 * cover_thick), cover_thick], center=true);
        translate([kant * (bracket_total_width/2 + cover_clearance + cover_thick/2), 0, h_wand/2])
            cube([cover_thick, eff_l + (2 * cover_thick), h_wand], center=true);
        for(y_pos = [-1, 1]) {
            translate([0, y_pos * (eff_l/2 + cover_thick/2), 0])
            rotate([270, 0, 0]) 
            linear_extrude(height = cover_thick, center = true)
                polygon([
                    [kant * (bracket_total_width/2 + cover_clearance + cover_thick/2), 0],
                    [kant * (bracket_total_width/2 + cover_clearance + cover_thick/2), -h_wand],
                    [-kant * (bracket_total_width/2 + cover_clearance + 3), -h_wand],
                    [-kant * (top_side_width/2 + cover_clearance), 0]
                ]);
        }
    }
}