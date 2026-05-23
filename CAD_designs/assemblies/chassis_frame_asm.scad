// === WEERGAVE OPTIES ===
toon_base_plate       = true;  // Zet op false om de main base plate te verbergen
toon_upright_wall     = true;  // Zet op false om de upright wall te verbergen
toon_protection_cover = true;  // Zet op false om de protection cover te verbergen

stapel_weergave       = false;  // Zet op true om alle onderdelen op de Z-as uit elkaar te trekken
stapel_afstand        = 450;   // De afstand op de Z-as tussen de gestapelde onderdelen
// =======================

include <../config/parameters.scad>

use <../parts/main_base_plate.scad>
use <../parts/upright_wall.scad>
use <../parts/protection_cover.scad>

module chassis_frame_asm(show_bend = true, kant = 1) {
    plate_z = bracket_top_z + beam_profile + (connect_plate_thick/2);
    
    // De hoofdgroep behoudt altijd zijn originele X- en Z-positie
    translate([kant * (chassis_width/2), 0, plate_z]) {
        
        if (toon_base_plate) {
            main_base_plate();
        }
        
        if (toon_upright_wall) {
            // X behoudt altijd de originele offset, Z schuift alleen omhoog bij stapelweergave
            wall_x = -kant * (bracket_total_width/2 - connect_plate_thick/2);
            wall_z = stapel_weergave ? stapel_afstand : 0;
            
            translate([wall_x, 0, wall_z])
                upright_wall(show_bend = show_bend, kant = kant);
        }
        
        if (toon_protection_cover) {
            // Z schuift nog verder omhoog bij stapelweergave, anders originele logica
            cover_z = stapel_weergave ? (stapel_afstand * 2) : (exploded_view ? explosion_dist * 0.8 : 0);
            
            translate([0, 0, cover_z])
                protection_cover(kant = kant);
        }
    }
}

// Render de complete assembly (verander kant naar -1 voor de linkerkant)
chassis_frame_asm(show_bend = true, kant = 1);