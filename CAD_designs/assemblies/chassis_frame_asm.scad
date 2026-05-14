include <../config/parameters.scad>
include <../parts/main_base_plate.scad>
include <../parts/upright_wall.scad>
include <../parts/protection_cover.scad>

module chassis_frame_asm() {
    plate_z = bracket_top_z + beam_profile + (connect_plate_thick/2);
    for(x_side = [-1, 1]) {
        translate([x_side * (chassis_width/2), 0, plate_z]) {
            main_base_plate();
            translate([-x_side * (bracket_total_width/2 - connect_plate_thick/2), 0, 0])
                upright_wall(kant = x_side);
            translate([0, 0, exploded_view ? explosion_dist * 0.8 : 0])
                protection_cover(kant = x_side);
        }
    }
}