// ==========================================
// DRILL BUSHING M8 (importeerbaar onderdeel)
// ==========================================
// Opoffer-ring voor een M8 boorgat. Open dit bestand los om de ring te
// printen (staat al in de juiste printstand, kraag op de bodemplaat).
//
// Importeren in een mal:
//   use <drill_bushing_m8.scad>;
//
//   difference() { ... cylinder(d = bushing_m8_pocket_d(), h = 50, center = true); }
//   translate([x, y, top_of_jig]) bushing_m8(plate_thick = 5);
//   translate([x, y, 0])          bushing_m8_flat(plate_thick = 5);

include <../config/parameters.scad>;
include <drill_bushing.scad>;

bush_m8_drill_clearance = 0.1;   // Speling op het boorgat in de ring (geleiding van de boor)
bush_m8_plate_thick     = 5;     // Standaard maldikte als je de ring los print

bush_m8_hole_d = m8_bolt_diameter + bush_m8_drill_clearance;

// DEBUG MODE - alleen van toepassing als je DIT bestand los opent
show_standalone = true;

// ==========================================
// MAATFUNCTIES
// ==========================================

function bushing_m8_hole_d() = bush_m8_hole_d;

function bushing_m8_od(wall = bush_wall_default) =
    bushing_od(bush_m8_hole_d, wall);

function bushing_m8_pocket_d(wall = bush_wall_default, fit = bush_fit_default) =
    bushing_pocket_d(bush_m8_hole_d, wall, fit);

function bushing_m8_collar_d(wall = bush_wall_default, collar_w = bush_collar_w_default) =
    bushing_collar_d(bush_m8_hole_d, wall, collar_w);

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module bushing_m8(plate_thick = bush_m8_plate_thick,
                  wall        = bush_wall_default,
                  collar_h    = bush_collar_h_default,
                  collar_w    = bush_collar_w_default) {
    drill_bushing(bush_m8_hole_d, plate_thick, wall, collar_h, collar_w);
}

module bushing_m8_flat(plate_thick = bush_m8_plate_thick,
                       wall        = bush_wall_default,
                       collar_h    = bush_collar_h_default,
                       collar_w    = bush_collar_w_default) {
    drill_bushing_flat(bush_m8_hole_d, plate_thick, wall, collar_h, collar_w);
}

// ==========================================
// RENDER (alleen standalone, wordt genegeerd bij 'use <...>')
// ==========================================

if (show_standalone) {
    color("Tomato")
        bushing_m8_flat();
}
