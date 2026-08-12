// ==========================================
// LOCAL TEMPLATE CONFIG (Hardcoded)
// ==========================================
// Lasmal die op de plaats van de wielas valt en de zijplaten onderin
// exact op de binnenmaat (inner_width) uit elkaar houdt, zodat ze tijdens
// het lassen niet naar binnen trekken.
// De tong heeft een ronde kop en valt in het asgat, net als de echte as.

tpl_span_adjust  = 0;      // 0 = exact 140 mm. -0.2 voor speling, +0.2 voor lichte voorspanning
tpl_clearance    = 0.3;    // Speling zodat de ronde kop in het asgat (10.2) valt
tpl_tongue_extra = 8;      // Extra uitsteek voorbij de buitenkant van de zijplaat (0 = vlak)

tpl_web_height   = 15;     // Hoogte van de rug, gemeten vanaf het hart van de as naar beneden
tpl_web_width    = 20;     // Y-breedte van de rug tussen de platen => vormt de aanslag

tpl_wing_width   = 80;     // Y-breedte van de vierkante vleugels
tpl_wing_thick   = 6;      // Z-dikte van de vleugels
tpl_wing_inset   = 0;      // Vleugels korter dan de binnenmaat (0 = volle lengte, beste steun)

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_reference = true;

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>;
use <../parts/bracket_side_plate.scad>;

// ==========================================
// GEDEELDE AFMETINGEN
// ==========================================
tpl_span       = inner_width + tpl_span_adjust;
tpl_tongue_len = bracket_thick + tpl_tongue_extra;
tpl_total_len  = tpl_span + (2 * tpl_tongue_len);

tpl_tongue_w   = axle_dia - tpl_clearance;
tpl_seat_z     = axle_hole_distance - axle_bottom_dist;

tpl_bottom_z   = tpl_seat_z - tpl_web_height;
tpl_body_cz    = tpl_seat_z - (tpl_web_height / 2);
tpl_wing_cz    = tpl_bottom_z + (tpl_wing_thick / 2);

tpl_plate_face = inner_width / 2;

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module distance_template() {
    union() {
        translate([0, 0, tpl_seat_z])
            rotate([0, 90, 0])
                cylinder(d = tpl_tongue_w, h = tpl_total_len, center = true, $fn = 64);

        translate([0, 0, tpl_body_cz])
            cube([tpl_total_len, tpl_tongue_w, tpl_web_height], center=true);

        translate([0, 0, tpl_body_cz])
            cube([tpl_span, tpl_web_width, tpl_web_height], center=true);

        translate([0, 0, tpl_wing_cz])
            cube([tpl_span - (2 * tpl_wing_inset), tpl_wing_width, tpl_wing_thick], center=true);
    }
}

// ==========================================
// RENDER
// ==========================================

color("DodgerBlue") {
    distance_template();
}

if (show_reference) {
    for (i = [-1, 1]) {
        translate([i * (tpl_plate_face + (bracket_thick / 2)), 0, 0])
            rotate([0, 0, (i == 1) ? 180 : 0])
                %bracket_side_plate(show_bend = true);
    }
}
