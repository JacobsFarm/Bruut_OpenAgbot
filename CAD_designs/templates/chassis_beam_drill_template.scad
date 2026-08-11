// ==========================================
// LOCAL TEMPLATE CONFIG
// ==========================================

// --- MODULE SELECTIE (zet aan/uit om los te printen) ---
show_module_1 = true;    // Mal 1: met eindstop tegen de kopse kant van de koker
show_module_2 = true;    // Mal 2: verlenging, sluit direct aan achter module 1
show_single_bushing = false; // Mal 3: 1 losse opoffer-ring om een versleten ring te vervangen
                             // (true => alleen die ene ring, de rest wordt niet gerenderd)

tpl_length    = 200;     // Lengte van module 1
tpl_length_2  = 200;     // Lengte van module 2 (verlenging)
tpl_gap       = 0;       // Ruimte tussen module 1 en 2 (0 = strak tegen elkaar => juiste boorafstand)

tpl_thickness   = 5;     // Dikte van de 3D-geprinte wanden
tpl_clearance   = 0.5;   // Extra tolerantie zodat de mal over de koker glijdt
tpl_side_height = 25;    // Hoogte van de zijmuren en achterkant

// --- OPOFFER-RINGEN (vervangbare boorbussen) ---
// false = vaste print, boorgaten zitten direct in de mal (originele versie)
// true  = de mal krijgt ruime uitsparingen en de boorgaten zitten in losse ringen
//         die je kunt vervangen als ze uitgeboord zijn
use_bushings      = false;
show_bushings     = false;  // Ringen meerenderen (alleen als use_bushings = true)
bushings_flat     = false; // false = ringen op hun plek in de mal, true = los op de bodemplaat om te printen

tpl_bush_wall     = 5;     // Wanddikte (breedte) van de opoffer-ring
tpl_bush_fit      = 0.2;   // Speling tussen ring en uitsparing in de mal (persfit)
tpl_bush_collar_h = 2;     // Dikte van de kraag die bovenop de mal rust (stop tegen doordrukken)
tpl_bush_collar_w = 2;     // Extra breedte van de kraag per kant (om hem eruit te wippen)
tpl_bush_pitch    = 5;     // Ruimte tussen de ringen in de vlakke printopstelling
tpl_bush_flat_y   = 80;    // Y-positie van de rij losse ringen

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_reference = true;

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>;
use <../parts/chassis_beam_1.scad>;

// ==========================================
// GEDEELDE AFMETINGEN
// ==========================================
inner_w = beam_profile + tpl_clearance;
outer_w = inner_w + (2 * tpl_thickness);

// Kopse kant (eind) van de koker
end_x = (beam_length_1 / 2) + (tpl_clearance / 2);

// Z-hoogtes uitlijnen zodat de muur vanaf de bovenkant naar beneden valt
z_top_bottom  = (beam_profile / 2) + (tpl_clearance / 2); // Onderkant van de bovenplaat
z_top_center  = z_top_bottom + (tpl_thickness / 2);       // Midden van de bovenplaat
z_top_surface = z_top_bottom + tpl_thickness;             // Bovenkant van de mal
z_side_center = z_top_surface - (tpl_side_height / 2);    // Midden van de zijmuren

// Boorgat en ring afmetingen
drill_hole_d  = m10_bolt_diameter + 0.1;                  // Het eigenlijke boorgat (geleiding)
bush_od       = drill_hole_d + (2 * tpl_bush_wall);       // Buitenmaat van de ring
bush_pocket_d = bush_od + tpl_bush_fit;                   // Uitsparing in de mal
bush_collar_d = bush_od + (2 * tpl_bush_collar_w);        // Kraag bovenop de mal

// Gatenpatroon volgens het modulaire grid
hole_min_x = (chassis_width_min / 2) - (bracket_top_hole_dist_x / 2);
hole_max_x = (chassis_width_max / 2) + (bracket_top_hole_dist_x / 2);

// ==========================================
// POSITIES VAN DE MODULES
// ==========================================
// Module 1 loopt van (end_x - tpl_length) tot end_x, met eindstop op end_x.
center_x_1 = end_x - (tpl_length / 2);

// Module 2 sluit direct aan achter module 1 (verder richting het midden van de koker).
// Loopt van (end_x - tpl_length - tpl_gap - tpl_length_2) tot (end_x - tpl_length - tpl_gap).
center_x_2 = end_x - tpl_length - tpl_gap - (tpl_length_2 / 2);

// Een ring past alleen als de hele uitsparing binnen het segment valt
function fits_in_segment(x, seg_center_x, seg_length) =
    abs(x - seg_center_x) <= (seg_length / 2) - (bush_pocket_d / 2);

function hole_has_bushing(x) =
    fits_in_segment(x, center_x_1, tpl_length) || fits_in_segment(x, center_x_2, tpl_length_2);

function hole_is_shown(x) =
    (show_module_1 && fits_in_segment(x, center_x_1, tpl_length)) ||
    (show_module_2 && fits_in_segment(x, center_x_2, tpl_length_2));

// Lijst met alle gatposities (rechts en gespiegeld links)
all_hole_xs = [for (x = [hole_min_x : grid_step : hole_max_x]) each [x, -x]];

// In de vlakke printopstelling worden altijd alle ringen van module 1 + 2 gemaakt,
// zodat je de mal kunt uitzetten en alleen de ringen kunt printen.
bush_xs = bushings_flat
    ? [for (x = all_hole_xs) if (hole_has_bushing(x)) x]
    : [for (x = all_hole_xs) if (hole_is_shown(x)) x];

// ==========================================
// GEOMETRY LOGIC (parametrisch segment)
// ==========================================
// seg_center_x : X-positie van het midden van dit segment
// seg_length   : lengte van dit segment langs de koker
// with_endstop : true => tegenhouder aan de kopse kant (alleen module 1)
module drill_template_segment(seg_center_x, seg_length, with_endstop=false) {
    difference() {
        // --- 1. BASIS U-VORM ---
        union() {
            // Bovenplaat
            translate([seg_center_x, 0, z_top_center])
                cube([seg_length, outer_w, tpl_thickness], center=true);

            // Zijwanden (links en rechts)
            for(y_dir = [-1, 1]) {
                translate([seg_center_x, y_dir * ((inner_w/2) + (tpl_thickness/2)), z_side_center])
                    cube([seg_length, tpl_thickness, tpl_side_height], center=true);
            }

            // Tegenhouder (eindstop aan de kopse kant) - alleen module 1
            if (with_endstop) {
                translate([end_x + (tpl_thickness/2), 0, z_side_center])
                    cube([tpl_thickness, outer_w, tpl_side_height], center=true);
            }
        }

        // --- 2. GATEN VAN DE CHASSIS_BEAM UITKNIPPEN ---
        // Genereert gaten volgens het modulaire grid patroon (grid_step)
        // Met use_bushings wordt een ruime uitsparing gefreesd waar de opoffer-ring in valt;
        // past de uitsparing niet volledig binnen dit segment, dan blijft het een gewoon boorgat.
        for(x = all_hole_xs) {
            cut_d = (use_bushings && fits_in_segment(x, seg_center_x, seg_length))
                ? bush_pocket_d
                : drill_hole_d;

            translate([x, 0, z_top_center])
                cylinder(d=cut_d, h=tpl_thickness + 10, center=true, $fn=64);
        }
    }
}

// ==========================================
// OPOFFER-RING (losse boorbus)
// ==========================================
// Origin ligt op de bovenkant van de mal: het lijf valt in de uitsparing,
// de kraag blijft erbovenop liggen zodat de ring er bij het boren niet doorheen zakt.
module sacrificial_bushing() {
    difference() {
        union() {
            translate([0, 0, -tpl_thickness])
                cylinder(d=bush_od, h=tpl_thickness, $fn=64);

            cylinder(d=bush_collar_d, h=tpl_bush_collar_h, $fn=64);
        }

        translate([0, 0, -tpl_thickness - 1])
            cylinder(d=drill_hole_d, h=tpl_thickness + tpl_bush_collar_h + 2, center=false, $fn=64);
    }
}

// Printstand: op de kop, kraag op de bodemplaat, dus zonder support
module bushing_flat() {
    translate([0, 0, tpl_bush_collar_h])
        rotate([180, 0, 0])
            sacrificial_bushing();
}

// ==========================================
// RENDER
// ==========================================
if (show_single_bushing) {
    // Losse vervangingsring op de oorsprong, klaar om te slicen
    color("Tomato")
        bushing_flat();

} else {
    if (show_module_1) {
        color("DodgerBlue")
            drill_template_segment(center_x_1, tpl_length, with_endstop=true);
    }

    if (show_module_2) {
        color("Orange")
            drill_template_segment(center_x_2, tpl_length_2, with_endstop=false);
    }

    if (use_bushings && show_bushings) {
        color("Tomato") {
            if (bushings_flat) {
                // Hele set ringen naast de mal
                for (i = [0 : len(bush_xs) - 1]) {
                    translate([i * (bush_collar_d + tpl_bush_pitch), tpl_bush_flat_y, 0])
                        bushing_flat();
                }
            } else {
                for (x = bush_xs) {
                    translate([x, 0, z_top_surface])
                        sacrificial_bushing();
                }
            }
        }
    }

    if (show_reference) {
        // Rendert je kokerbalk transparant als referentie
        %chassis_beam_1();
    }
}
