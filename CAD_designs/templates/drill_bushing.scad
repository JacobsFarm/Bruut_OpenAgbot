// ==========================================
// DRILL BUSHING - GEDEELDE BASIS (parametrisch)
// ==========================================
// Vervangbare opoffer-ring (boorbus) voor boormallen.
// Het lijf valt in de uitsparing van de mal, de kraag blijft erbovenop liggen
// zodat de ring bij het boren niet doorzakt. Is een ring uitgeboord, dan
// vervang je alleen die ring en niet de hele mal.
//
// Origin = de BOVENKANT van de mal:
//   lijf loopt van z = -plate_thick tot z = 0
//   kraag loopt van z = 0 tot z = collar_h
//
// Deze basis niet direct importeren in een mal, gebruik de maatvoerende versies:
//   use <drill_bushing_m8.scad>;   ->  bushing_m8(...)  / bushing_m8_pocket_d()
//   use <drill_bushing_m10.scad>;  ->  bushing_m10(...) / bushing_m10_pocket_d()

bush_wall_default     = 5;     // Wanddikte van de ring rond het boorgat
bush_fit_default      = 0.2;   // Speling tussen ring en uitsparing in de mal (persfit)
bush_collar_h_default = 2;     // Dikte van de kraag die bovenop de mal rust
bush_collar_w_default = 2;     // Extra breedte van de kraag per kant (om hem eruit te wippen)

// ==========================================
// MAATFUNCTIES
// ==========================================

function bushing_od(hole_d, wall = bush_wall_default) =
    hole_d + (2 * wall);

function bushing_pocket_d(hole_d, wall = bush_wall_default, fit = bush_fit_default) =
    bushing_od(hole_d, wall) + fit;

function bushing_collar_d(hole_d, wall = bush_wall_default, collar_w = bush_collar_w_default) =
    bushing_od(hole_d, wall) + (2 * collar_w);

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module drill_bushing(hole_d,
                     plate_thick,
                     wall     = bush_wall_default,
                     collar_h = bush_collar_h_default,
                     collar_w = bush_collar_w_default) {
    difference() {
        union() {
            translate([0, 0, -plate_thick])
                cylinder(d = bushing_od(hole_d, wall), h = plate_thick, $fn = 64);

            cylinder(d = bushing_collar_d(hole_d, wall, collar_w), h = collar_h, $fn = 64);
        }

        translate([0, 0, -plate_thick - 1])
            cylinder(d = hole_d, h = plate_thick + collar_h + 2, $fn = 64);
    }
}

module drill_bushing_flat(hole_d,
                          plate_thick,
                          wall     = bush_wall_default,
                          collar_h = bush_collar_h_default,
                          collar_w = bush_collar_w_default) {
    translate([0, 0, collar_h])
        rotate([180, 0, 0])
            drill_bushing(hole_d, plate_thick, wall, collar_h, collar_w);
}
