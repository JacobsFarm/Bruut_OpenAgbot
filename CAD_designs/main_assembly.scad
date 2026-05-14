include <config/parameters.scad>
include <assemblies/wheel_unit_asm.scad>
include <assemblies/chassis_frame_asm.scad>
include <parts/chassis_beam.scad>

module bruut_agbot_full() {
    for(x_pos = [-chassis_width/2, chassis_width/2]) {
        for(y_pos = [-chassis_length/2, chassis_length/2]) {
            translate([x_pos, y_pos, 0])
                wheel_unit_asm();
        }
    }
    z_pos = bracket_top_z + (beam_profile/2);
    bolt_offset_y = side_plate_top_width/3;
    translate([0, 0, exploded_view ? explosion_dist : 0]) {
        for(y_as = [-chassis_length/2, chassis_length/2]) {
            for(koker_y_offset = [-bolt_offset_y, bolt_offset_y]) {
                translate([0, y_as + koker_y_offset, z_pos])
                    chassis_beam();
            }
        }
    }
    chassis_frame_asm();
}

bruut_agbot_full();