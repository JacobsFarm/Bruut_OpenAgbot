// ==========================================
// LOCAL TEMPLATE CONFIG
// ==========================================

// --- MODULE SELECTIE (zet aan/uit om los te printen) ---
show_module_1 = true;    // Mal 1: met eindstop tegen de kopse kant van de koker
show_module_2 = true;    // Mal 2: verlenging, sluit direct aan achter module 1

tpl_length    = 200;     // Lengte van module 1
tpl_length_2  = 200;     // Lengte van module 2 (verlenging)
tpl_gap       = 0;       // Ruimte tussen module 1 en 2 (0 = strak tegen elkaar => juiste boorafstand)

tpl_thickness   = 5;     // Dikte van de 3D-geprinte wanden
tpl_clearance   = 0.5;   // Extra tolerantie zodat de mal over de koker glijdt
tpl_side_height = 25;    // Hoogte van de zijmuren en achterkant

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
        min_hole_x = (chassis_width_min / 2) - (bracket_top_hole_dist_x / 2);
        max_hole_x = (chassis_width_max / 2) + (bracket_top_hole_dist_x / 2);

        for(x = [min_hole_x : grid_step : max_hole_x]) {
            // Knip gaten uit de rechterkant
            translate([x, 0, z_top_center])
                cylinder(d=m10_bolt_diameter, h=tpl_thickness + 10, center=true, $fn=64);

            // Knip gaten uit de linkerkant (spiegeling)
            translate([-x, 0, z_top_center])
                cylinder(d=m10_bolt_diameter, h=tpl_thickness + 10, center=true, $fn=64);
        }
    }
}

// ==========================================
// POSITIES VAN DE MODULES
// ==========================================
// Module 1 loopt van (end_x - tpl_length) tot end_x, met eindstop op end_x.
center_x_1 = end_x - (tpl_length / 2);

// Module 2 sluit direct aan achter module 1 (verder richting het midden van de koker).
// Loopt van (end_x - tpl_length - tpl_gap - tpl_length_2) tot (end_x - tpl_length - tpl_gap).
center_x_2 = end_x - tpl_length - tpl_gap - (tpl_length_2 / 2);

// ==========================================
// RENDER
// ==========================================
if (show_module_1) {
    color("DodgerBlue")
        drill_template_segment(center_x_1, tpl_length, with_endstop=true);
}

if (show_module_2) {
    color("Orange")
        drill_template_segment(center_x_2, tpl_length_2, with_endstop=false);
}

if (show_reference) {
    // Rendert je kokerbalk transparant als referentie
    %chassis_beam_1();
}
