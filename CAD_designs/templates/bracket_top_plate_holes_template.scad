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
show_center_only = false;

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_reference = true;

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>;
use <../parts/bracket_top_plate.scad>;

// ==========================================
// GEDEELDE AFMETINGEN
// ==========================================
tpl_flush_z = (bracket_thick / 2) + (tpl_thickness / 2);

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module tpl_hole_pattern(hole_dia, dist_x, dist_y) {
    for (x = [-1, 1], y = [-1, 1]) {
        translate([x * (dist_x / 2), y * (dist_y / 2), 0])
            cylinder(d = hole_dia + tpl_clearance, h = 50, center = true, $fn = 64);
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

        tpl_hole_pattern(bracket_bolt_diameter, bracket_top_hole_dist_x, bracket_top_hole_dist_y);

        tpl_hole_pattern(bracket_m8_bolt_diameter,
                         bracket_top_hole_distance_centrum_holes,
                         bracket_top_hole_distance_centrum_holes);

        tpl_center_mark();
    }
}

module top_plate_holes_template_center() {
    difference() {
        cube([tpl_center_width, tpl_center_height, tpl_thickness], center = true);

        tpl_hole_pattern(bracket_m8_bolt_diameter,
                         bracket_top_hole_distance_centrum_holes,
                         bracket_top_hole_distance_centrum_holes);

        tpl_center_mark();
    }
}

// ==========================================
// RENDER
// ==========================================

color("DodgerBlue") {
    translate([0, 0, tpl_flush_z]) {
        if (show_center_only) {
            top_plate_holes_template_center();
        } else {
            top_plate_holes_template_wide();
        }
    }
}

if (show_reference) {
    %bracket_top_plate();
}
