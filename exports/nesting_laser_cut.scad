include <../config/parameters.scad>
include <../parts/bracket_side_plate.scad>
include <../parts/bracket_top_plate.scad>
include <../parts/main_base_plate.scad>

part_to_export = "side_plate"; 

if (part_to_export == "side_plate") {
    projection(cut = true) 
        rotate([0, -90, 0]) 
            bracket_side_plate();
} else if (part_to_export == "top_plate") {
    projection(cut = true) 
        bracket_top_plate();
} else if (part_to_export == "base_plate") {
    projection(cut = true) 
        main_base_plate();
}