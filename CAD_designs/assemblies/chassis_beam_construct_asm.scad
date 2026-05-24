// chassis_beam_construct_asm.scad

include <../config/parameters.scad>
use <../parts/bracket_top_plate.scad>
use <../parts/chassis_beam_1.scad>
use <../parts/chassis_beam_2.scad>

module chassis_beam_construct_asm() {
    
    // --- NIEUW: Auto-Grid Uitlijning ---
    // Zorgt ervoor dat het chassis altijd perfect op het 40mm gatenpatroon klikt.
    // Omdat we vanuit het midden (0) werken, moet de totale breedte een veelvoud van 80 zijn.
    align_width = round(chassis_width / 80) * 80;   // Bijv: 750 wordt automatisch 720
    align_length = round(chassis_length / 80) * 80; // Bijv: 1000 wordt automatisch 960

    // Z-hoogtes berekenen zodat de delen netjes op elkaar stapelen
    z_bracket_top = bracket_thick / 2;
    z_bottom_beams = z_bracket_top + (beam_profile / 2);
    z_top_beams = z_bottom_beams + beam_profile;

    // 1. Plaats de 4 bracket_top_plates op de hoeken (gebruikt nu align_width/length)
    for (x = [-align_width/2, align_width/2]) {
        for (y = [-align_length/2, align_length/2]) {
            translate([x, y, 0])
                color("darkgray") 
                bracket_top_plate();
        }
    }

    // 2. Plaats de 4 onderste balken (Zijdelings / Breedte / X-as)
    for (y_center = [-align_length/2, align_length/2]) {
        for (y_offset = [-bracket_top_hole_dist_y/2, bracket_top_hole_dist_y/2]) {
            translate([0, y_center + y_offset, z_bottom_beams])
                color("silver")
                chassis_beam_1(); 
        }
    }

    // 3. Plaats de 4 bovenste balken (Lengterichting / Y-as)
    for (x_center = [-align_width/2, align_width/2]) {
        for (x_offset = [-bracket_top_hole_dist_x/2, bracket_top_hole_dist_x/2]) {
            translate([x_center + x_offset, 0, z_top_beams])
                rotate([0, 0, 90])
                color("dimgray")
                chassis_beam_2(); 
        }
    }
}

// Preview
chassis_beam_construct_asm();