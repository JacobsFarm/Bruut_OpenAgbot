// ==========================================
// LOCAL TEMPLATE CONFIG (Hardcoded)
// ==========================================
// Las-/centreermal voor de buis in het hart van de bracket_top_plate.
// Basis is dezelfde smalle view als bracket_top_plate_holes_template:
// de 4 M8 centrumgaten (50 x 50) om de mal op de plaat vast te zetten.
//
// In het hart zit een doorlopend gat voor de buis. Daaromheen staan 4
// opstaande cirkelsegmenten die de buis centreren en recht houden.
// Tussen de segmenten zitten 4 openingen: die lopen ook door de grondplaat
// heen, zodat je bij de voet van de buis kunt om een lastack te leggen.
//
// De openingen staan op de X/Y-as (tpl_gap_rotate = 0), dus weg van de M8
// bouten die op de diagonalen zitten. In de grondplaat is het maar een klein
// hapje: tpl_gap_reach bepaalt hoe diep, tpl_gap_plate_a hoe breed. Zet je
// tpl_gap_plate_a ruimer dan tpl_gap_angle, dan verbreedt het hapje pas
// buiten de opzetten, zodat die niet boven de uitsparing komen te zweven.
// Met tpl_gap_rotate = 45 draaien de openingen naar de diagonalen; houd dan
// tpl_gap_reach op ca. 29, anders loop je in de M8 gaten.

tpl_pipe_dia = 49;          // Buitendiameter van de buis (pas dit aan bij een andere maat)
tpl_pipe_fit = 0.4;         // Speling tussen buis en mal (totaal op de diameter)

tpl_clearance = 0.1;        // Speling op elke boorgatdiameter, zodat de boor niet klemt

tpl_thickness = 3;          // Z-dikte van de geprinte grondplaat

tpl_width  = 90;            // X-maat van de mal (gatafstand 50 + 2x 20 rand)
tpl_height = 90;            // Y-maat van de mal (gatafstand 50 + 2x 20 rand)

// --- CENTREER-OPZETTEN ---
tpl_arc_height   = 25;      // Hoogte van de opzetten boven de grondplaat
tpl_arc_wall     = 4;       // Wanddikte van de opzetten
tpl_arc_count    = 4;       // Aantal segmenten (= aantal lasopeningen)
tpl_gap_angle    = 40;      // Hoekbreedte van de opening tussen de opzetten
tpl_gap_rotate   = 0;       // 45 = openingen op de diagonalen, 0 = openingen op de X/Y-as
tpl_gap_plate_a  = 40;      // Hoekbreedte van het hapje in de grondplaat (gelijk aan tpl_gap_angle = geen verbreding buitenom)
tpl_gap_reach    = 31;      // Straal tot waar het hapje in de grondplaat loopt (boring ligt op 24,7 dus dit is een hapje van ca. 6 mm)
tpl_arc_lead_in  = 1.5;     // Afschuining bovenaan, zodat de buis makkelijk invalt
tpl_arc_skirt    = 0;       // Extra brede voet onderaan de opzetten (bij tpl_gap_rotate = 0 op 0 laten, anders raakt de voet de M8 gaten)
tpl_arc_support  = 1;       // Rand plaatmateriaal die onder de opzetten blijft staan, zodat ze niet boven de uitsparing zweven

// --- VERSTEVIGINGSDRIEHOEKEN ---
show_ribs        = true;    // Schoren aan de buitenkant van de opzetten
tpl_rib_per_arc  = 2;       // Aantal schoren per opzet (2 = links en rechts, 1 = midden)
tpl_rib_spread   = 18;      // Hoek vanaf het hart van de opzet (houd de schoor weg van de M8 gaten en de hapjes)
tpl_rib_len      = 9;       // Lengte van de schoor over de grondplaat
tpl_rib_height   = 15;      // Hoogte van de schoor tegen de opzet
tpl_rib_thick    = 3;       // Dikte van de schoor

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_pipe      = true;      // Ghost-buis meerenderen om de pasvorm te controleren
tpl_pipe_show_len = 120;    // Lengte van de ghost-buis
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

tpl_bore_d  = tpl_pipe_dia + tpl_pipe_fit;
tpl_arc_d   = tpl_bore_d + (2 * tpl_arc_wall);
tpl_skirt_d = tpl_arc_d + (2 * tpl_arc_skirt);

tpl_hole_cut_d = bracket_m8_bolt_diameter + tpl_clearance;

tpl_arc_foot_r = (max(tpl_arc_d, tpl_skirt_d) / 2) + tpl_arc_support;

tpl_rib_r0 = (tpl_arc_d / 2) - 1;
tpl_rib_h  = min(tpl_rib_height, tpl_arc_height);

// ==========================================
// GEOMETRY LOGIC
// ==========================================

module tpl_hole_pattern(cut_dia, dist_x, dist_y) {
    for (x = [-1, 1], y = [-1, 1]) {
        translate([x * (dist_x / 2), y * (dist_y / 2), 0])
            cylinder(d = cut_dia, h = 50, center = true, $fn = 64);
    }
}

module tpl_weld_gap(gap_a, r, h) {
    seg = max(2, ceil(gap_a / 5));
    linear_extrude(height = h)
        polygon(concat([[0, 0]],
                       [for (i = [0 : seg])
                            let (a = -gap_a / 2 + (gap_a * i / seg))
                                [r * cos(a), r * sin(a)]]));
}

module tpl_center_arcs() {
    difference() {
        union() {
            cylinder(d = tpl_arc_d, h = tpl_arc_height, $fn = 128);

            if (tpl_arc_skirt > 0) {
                cylinder(d1 = tpl_skirt_d, d2 = tpl_arc_d,
                         h = tpl_arc_skirt, $fn = 128);
            }
        }

        translate([0, 0, -1])
            cylinder(d = tpl_bore_d, h = tpl_arc_height + 2, $fn = 128);

        if (tpl_arc_lead_in > 0) {
            translate([0, 0, tpl_arc_height - tpl_arc_lead_in])
                cylinder(d1 = tpl_bore_d,
                         d2 = tpl_bore_d + (2 * tpl_arc_lead_in),
                         h = tpl_arc_lead_in + 0.01, $fn = 128);
        }

        for (i = [0 : tpl_arc_count - 1]) {
            rotate([0, 0, tpl_gap_rotate + (i * 360 / tpl_arc_count)])
                translate([0, 0, -1])
                    tpl_weld_gap(tpl_gap_angle,
                                 (tpl_skirt_d / 2) + 1,
                                 tpl_arc_height + 2);
        }
    }
}

module tpl_arc_ribs() {
    for (i = [0 : tpl_arc_count - 1], s = [0 : tpl_rib_per_arc - 1]) {
        rotate([0, 0, tpl_gap_rotate + (180 / tpl_arc_count)
                      + (i * 360 / tpl_arc_count)
                      + (tpl_rib_per_arc > 1
                         ? -tpl_rib_spread + (s * 2 * tpl_rib_spread / (tpl_rib_per_arc - 1))
                         : 0)])
            rotate([90, 0, 0])
                linear_extrude(height = tpl_rib_thick, center = true)
                    polygon([[tpl_rib_r0, 0],
                             [tpl_rib_r0 + tpl_rib_len, 0],
                             [tpl_rib_r0, tpl_rib_h]]);
    }
}

module top_plate_pipe_center_template() {
    union() {
        difference() {
            cube([tpl_width, tpl_height, tpl_thickness], center = true);

            tpl_hole_pattern(tpl_hole_cut_d,
                             bracket_top_hole_distance_centrum_holes,
                             bracket_top_hole_distance_centrum_holes);

            cylinder(d = tpl_bore_d, h = tpl_thickness + 2, center = true, $fn = 128);

            for (i = [0 : tpl_arc_count - 1]) {
                rotate([0, 0, tpl_gap_rotate + (i * 360 / tpl_arc_count)])
                    translate([0, 0, -(tpl_thickness / 2) - 1])
                        union() {
                            tpl_weld_gap(tpl_gap_angle, tpl_gap_reach, tpl_thickness + 2);

                            difference() {
                                tpl_weld_gap(tpl_gap_plate_a, tpl_gap_reach, tpl_thickness + 2);

                                translate([0, 0, -1])
                                    cylinder(r = tpl_arc_foot_r,
                                             h = tpl_thickness + 4, $fn = 128);
                            }
                        }
            }
        }

        translate([0, 0, tpl_thickness / 2])
            tpl_center_arcs();

        if (show_ribs) {
            translate([0, 0, tpl_thickness / 2])
                tpl_arc_ribs();
        }
    }
}

// ==========================================
// RENDER
// ==========================================

color("DodgerBlue")
    translate([0, 0, tpl_flush_z])
        top_plate_pipe_center_template();

if (show_pipe) {
    %translate([0, 0, bracket_thick / 2])
        cylinder(d = tpl_pipe_dia, h = tpl_pipe_show_len, $fn = 128);
}

if (show_reference) {
    %bracket_top_plate();
}
