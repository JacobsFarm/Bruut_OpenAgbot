// ==========================================
// LOCAL TEMPLATE CONFIG (Hardcoded)
// ==========================================
// Platte boormal die exact bovenop de bracket_top_plate valt.
// Leg de mal op de top plate om te controleren of alle gaten overeen komen,
// leg hem daarna op een nieuwe plaat en boor de gaten er netjes doorheen.
//
// Twee views, om te wisselen met show_center_only:
//   false = brede view: de 4 buitenste gaten (100 x 150) EN de 4 centrumgaten (50 x 50)
//   true  = smalle view: alleen de 4 centrumgaten (50 x 50)

tpl_clearance = 0.1;        // Speling op elke gatdiameter, zodat de boor niet klemt

tpl_thickness = 5;          // Z-dikte van de geprinte mal

tpl_wide_width  = 140;      // X-maat brede view (gatafstand 100 + 2x 20 rand)
tpl_wide_height = 190;      // Y-maat brede view (gatafstand 150 + 2x 20 rand)

tpl_center_width  = 90;     // X-maat smalle view (gatafstand 50 + 2x 20 rand)
tpl_center_height = 90;     // Y-maat smalle view (gatafstand 50 + 2x 20 rand)

tpl_center_mark_dia = 5;    // Klein hartgat om de mal uit te lijnen (0 = geen hartgat)

// VIEW SELECT
show_center_only = true;

// --- OPOFFER-RINGEN (vervangbare boorbussen) ---
// false = vaste print, boorgaten zitten direct in de mal
// true  = de mal krijgt ruime uitsparingen en de boorgaten zitten in losse ringen
//         die je kunt vervangen als ze uitgeboord zijn.
// De buitenste gaten krijgen een M10-ring, de centrumgaten een M8-ring.
use_bushings  = true;
show_bushings = false;      // Ringen meerenderen (alleen als use_bushings = true)
bushings_flat = false;      // false = ringen op hun plek in de mal, true = los op de bodemplaat om te printen

tpl_bush_wall     = 5;      // Wanddikte (breedte) van de opoffer-ring
tpl_bush_fit      = 0.2;    // Speling tussen ring en uitsparing in de mal (persfit)
tpl_bush_collar_h = 2;      // Dikte van de kraag die bovenop de mal rust
tpl_bush_collar_w = 2;      // Extra breedte van de kraag per kant (om hem eruit te wippen)
tpl_bush_pitch    = 5;      // Ruimte tussen de ringen in de vlakke printopstelling
tpl_bush_flat_y   = 140;    // Y-positie van de rij losse ringen

show_single_bushing_m8  = false;  // Alleen 1 losse M8 vervangingsring renderen
show_single_bushing_m10 = false;  // Alleen 1 losse M10 vervangingsring renderen

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_reference = true;

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>;
use <../parts/bracket_top_plate.scad>;
use <drill_bushing_m8.scad>;
use <drill_bushing_m10.scad>;

// ==========================================
// GEDEELDE AFMETINGEN
// ==========================================
tpl_flush_z = (bracket_thick / 2) + (tpl_thickness / 2);

tpl_outer_pocket_d  = bushing_m10_pocket_d(tpl_bush_wall, tpl_bush_fit);
tpl_center_pocket_d = bushing_m8_pocket_d(tpl_bush_wall, tpl_bush_fit);

tpl_outer_cut_d  = use_bushings ? tpl_outer_pocket_d  : bracket_bolt_diameter + tpl_clearance;
tpl_center_cut_d = use_bushings ? tpl_center_pocket_d : bracket_m8_bolt_diameter + tpl_clearance;

tpl_flat_step  = bushing_m10_collar_d(tpl_bush_wall, tpl_bush_collar_w) + tpl_bush_pitch;
tpl_flat_count = show_center_only ? 4 : 8;
tpl_flat_x0    = -((tpl_flat_count - 1) * tpl_flat_step) / 2;

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module tpl_hole_pattern(cut_dia, dist_x, dist_y) {
    for (x = [-1, 1], y = [-1, 1]) {
        translate([x * (dist_x / 2), y * (dist_y / 2), 0])
            cylinder(d = cut_dia, h = 50, center = true, $fn = 64);
    }
}

module tpl_center_mark() {
    if (tpl_center_mark_dia > 0) {
        cylinder(d = tpl_center_mark_dia, h = 50, center = true, $fn = 64);
    }
}

module top_plate_holes_template_wide() {
    difference() {
        cube([tpl_wide_width, tpl_wide_height, tpl_thickness], center = true);

        tpl_hole_pattern(tpl_outer_cut_d, bracket_top_hole_dist_x, bracket_top_hole_dist_y);

        tpl_hole_pattern(tpl_center_cut_d,
                         bracket_top_hole_distance_centrum_holes,
                         bracket_top_hole_distance_centrum_holes);

        tpl_center_mark();
    }
}

module top_plate_holes_template_center() {
    difference() {
        cube([tpl_center_width, tpl_center_height, tpl_thickness], center = true);

        tpl_hole_pattern(tpl_center_cut_d,
                         bracket_top_hole_distance_centrum_holes,
                         bracket_top_hole_distance_centrum_holes);

        tpl_center_mark();
    }
}

// ==========================================
// OPOFFER-RINGEN (geleend uit drill_bushing_m8 / _m10)
// ==========================================
// Origin van een ring ligt op de BOVENKANT van de mal.

module tpl_bushings_in_place() {
    if (!show_center_only) {
        for (x = [-1, 1], y = [-1, 1]) {
            translate([x * (bracket_top_hole_dist_x / 2),
                       y * (bracket_top_hole_dist_y / 2),
                       tpl_thickness / 2])
                bushing_m10(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
        }
    }

    for (x = [-1, 1], y = [-1, 1]) {
        translate([x * (bracket_top_hole_distance_centrum_holes / 2),
                   y * (bracket_top_hole_distance_centrum_holes / 2),
                   tpl_thickness / 2])
            bushing_m8(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
    }
}

module tpl_bushings_flat() {
    if (!show_center_only) {
        for (i = [0 : 3]) {
            translate([tpl_flat_x0 + (i * tpl_flat_step), tpl_bush_flat_y, 0])
                bushing_m10_flat(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
        }
    }

    for (i = [0 : 3]) {
        translate([tpl_flat_x0 + ((show_center_only ? i : i + 4) * tpl_flat_step), tpl_bush_flat_y, 0])
            bushing_m8_flat(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
    }
}

// ==========================================
// RENDER
// ==========================================

if (show_single_bushing_m8) {
    color("Tomato")
        bushing_m8_flat(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);

} else if (show_single_bushing_m10) {
    color("Tomato")
        bushing_m10_flat(tpl_thickness, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);

} else {
    color("DodgerBlue") {
        translate([0, 0, tpl_flush_z]) {
            if (show_center_only) {
                top_plate_holes_template_center();
            } else {
                top_plate_holes_template_wide();
            }
        }
    }

    if (use_bushings && show_bushings) {
        color("Tomato") {
            if (bushings_flat) {
                tpl_bushings_flat();
            } else {
                translate([0, 0, tpl_flush_z])
                    tpl_bushings_in_place();
            }
        }
    }

    if (show_reference) {
        %bracket_top_plate();
    }
}
