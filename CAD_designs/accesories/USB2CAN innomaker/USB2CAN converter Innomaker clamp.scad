// --- Positie en Rotatie voor STL Imports ---
// Vul hier de X, Y, Z waarden in om het model te verplaatsen of draaien.
center_pos = [0, 25, 2]; 
center_rot = [0, 0, 0]; 

// --- Positie en Rotatie voor de Klem ---
// Pas dit aan om de klem precies over de behuizing te schuiven
klem_pos = [0, 0, 0]; 
klem_rot = [0, 0, 0]; 

// --- STL Imports Weergave ---
show_top_import = true;
show_bottom_import = true;
show_klem = true;

// Optioneel: pas de transparantie aan (0.0 tot 1.0)
alpha_waarde = 0.8; 

// --- Klem Parameters ---
klem_breedte = 36;      // Binnenmaat breedte
klem_hoogte  = 19.5;    // Binnenmaat hoogte
klem_diepte  = 20;      // Diepte van de klem
klem_dikte   = 3;       // Dikte van het materiaal
oor_lengte   = 20;      // Lengte van de bevestigingsoren aan beide kanten
gat_diameter = 4;       // Diameter van het schroefgat in de oren
$fn = 50;               // Hoge resolutie voor mooie ronde gaten


// --- Klem Module ---
module behuizing_klem() {
    difference() {
        // Basisvorm (Oren + Buitenste kap)
        union() {
            // Hoofdgedeelte van de klem (kap)
            translate([-(klem_breedte/2 + klem_dikte), 0, 0])
                cube([klem_breedte + 2*klem_dikte, klem_diepte, klem_hoogte + klem_dikte]);
            
            // Linker oor
            translate([-(klem_breedte/2 + klem_dikte + oor_lengte), 0, 0])
                cube([oor_lengte, klem_diepte, klem_dikte]);
            
            // Rechter oor
            translate([(klem_breedte/2 + klem_dikte), 0, 0])
                cube([oor_lengte, klem_diepte, klem_dikte]);
        }
        
        // Uitsnede voor de behuizing (binnenkant hol maken)
        translate([-klem_breedte/2, -1, -1])
            cube([klem_breedte, klem_diepte + 2, klem_hoogte + 1]);
            
        // Schroefgat linker oor (precies in het midden van het oor)
        translate([-(klem_breedte/2 + klem_dikte + oor_lengte/2), klem_diepte/2, -1])
            cylinder(d=gat_diameter, h=klem_dikte + 2);
            
        // Schroefgat rechter oor (precies in het midden van het oor)
        translate([(klem_breedte/2 + klem_dikte + oor_lengte/2), klem_diepte/2, -1])
            cylinder(d=gat_diameter, h=klem_dikte + 2);
    }
}


// ==========================================
// --- RENDER GEDEELTE ---
// ==========================================

// Top behuizing
if (show_top_import) {
    translate(center_pos)
        rotate(center_rot)
            color("lightblue", alpha_waarde) 
            import("innomaker-USB2CAN-Top.stl");
}

// Bottom behuizing
if (show_bottom_import) {
    translate(center_pos)
        rotate(center_rot)
            color("darkgrey", alpha_waarde) 
            import("innomaker-USB2CAN-Bottom.stl");
}

// De Klem
if (show_klem) {
    translate(klem_pos)
        rotate(klem_rot)
            color("darkorange", 1.0)
            behuizing_klem();
}