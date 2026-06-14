// ==========================================
// LOCAL TEMPLATE CONFIG
// ==========================================
tpl_length = 280;        // Lengte van de mal (280mm dekt alle gaten aan 1 kant)
tpl_thickness = 5;       // Dikte van de 3D-geprinte wanden
tpl_clearance = 0.5;     // Extra tolerantie zodat de mal over de koker glijdt
tpl_side_height = 25;    // Hoogte van de zijmuren en achterkant (zoals gevraagd)

// DEBUG MODE - Zet op 'false' voordat je de STL exporteert
show_reference = true; 

// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>; 
use <../parts/chassis_beam_1.scad>;

// ==========================================
// GEOMETRY LOGIC
// ==========================================
module drill_template_sleeve() {
    inner_w = beam_profile + tpl_clearance; 
    outer_w = inner_w + (2 * tpl_thickness);
    
    // Posities berekenen over de X-as (de koker loopt van -500 tot +500)
    end_x = (beam_length_1 / 2) + (tpl_clearance / 2);
    center_x = end_x - (tpl_length / 2);
    
    // Z-hoogtes uitlijnen zodat de muur vanaf de bovenkant 25mm naar beneden valt
    z_top_bottom = (beam_profile / 2) + (tpl_clearance / 2); // Onderkant van de bovenplaat
    z_top_center = z_top_bottom + (tpl_thickness / 2);       // Midden van de bovenplaat
    z_top_surface = z_top_bottom + tpl_thickness;            // Bovenkant van de mal
    z_side_center = z_top_surface - (tpl_side_height / 2);   // Midden van de zijmuren
    
    difference() {
        // --- 1. BASIS U-VORM MET TEGENHOUDER ---
        union() {
            // Bovenplaat
            translate([center_x, 0, z_top_center])
                cube([tpl_length, outer_w, tpl_thickness], center=true);
            
            // Zijwanden (links en rechts)
            for(y_dir = [-1, 1]) {
                translate([center_x, y_dir * ((inner_w/2) + (tpl_thickness/2)), z_side_center])
                    cube([tpl_length, tpl_thickness, tpl_side_height], center=true);
            }
            
            // Tegenhouder (Eindstop aan de kopse kant)
            translate([end_x + (tpl_thickness/2), 0, z_side_center])
                cube([tpl_thickness, outer_w, tpl_side_height], center=true);
        }
        
        // --- 2. GATEN VAN DE CHASSIS_BEAM UITKNIPPEN ---
        // Genereert automatisch de gaten op de correcte positie uit de loop
        gewenste_breedtes = [chassis_width_min : chassis_width_step : chassis_width_max];
        for(optie_width = gewenste_breedtes) { 
            for(x_dir = [-1, 1]) {
                module_center_x = x_dir * (optie_width / 2);
                for(bx = [-1, 1]) {
                    hole_x = module_center_x + (bx * (bracket_top_hole_dist_x / 2));
                    
                    // Knip gat uit de bovenplaat
                    translate([hole_x, 0, z_top_center])
                        cylinder(d=bolt_dia, h=tpl_thickness + 10, center=true, $fn=64);
                }
            }
        }
    }
}

// ==========================================
// RENDER
// ==========================================

color("DodgerBlue") {
    drill_template_sleeve();
}

if (show_reference) {
    // Rendert je kokerbalk transparant als referentie
    %chassis_beam_1(); 
}