// --- SELECTIE MENU VOOR EXPORT ---
onderdeel = "Alles"; // [Alles, Beugel_Alleen, Wiel_Set_Compleet, Wiel_Alleen, Kap_Links, Kap_Rechts, Bovenmodule_Links, Bovenmodule_Rechts, Dwars_Koker]

// ... (variabelen blijven gelijk) ...
chassis_width = 75;   
chassis_length = 70; 
boor_opties_breedtes = [75, 65, 55];
boor_opties_lengtes = [75, 85, 100];
vaste_plaat_lengte = 100;
connect_plate_thick = 2.5; 

koker_profiel = 10; 
koker_dikte = 10;    
koker_lengte = 100;

hoogte_opstand     = 50;
top_breedte_zijde  = 6;  
kap_dikte          = 0.5;
kap_speling        = 1.5;  
kap_overlap        = 1;
kap_hoogte_abs     = 53; 

$fn = 50;
exploded_view = false; 
explosion_dist = 15; 

tire_dia = 40;
tire_width = 10;
hub_dia = 16;
hub_width = 15.5;
axle_dia = 5;
bracket_thick = 2.5;
bolt_dia = 1.2;

side_plate_top_width = tire_width * 2.6;
arm_height = (tire_dia/2) + 3;
inner_width = hub_width + 1;
bracket_total_width = inner_width + (2 * bracket_thick);
bracket_top_z = arm_height + bracket_thick;

// --- LOGICA VOOR WEERGAVE ---

if (onderdeel == "Alles") {
    for(x_pos = [-chassis_width/2, chassis_width/2]) {
        for(y_pos = [-chassis_length/2, chassis_length/2]) {
            translate([x_pos, y_pos, 0]) {
                wiel_set();
            }
        }
    }

    translate([0, 0, exploded_view ? explosion_dist : 0]) {
        dwars_kokers();
    }

    translate([0, 0, exploded_view ? explosion_dist * 2.5 : 0]) {
        verbindings_bouw();
    }
} 

else if (onderdeel == "Beugel_Alleen") {
    bracket();
}

else if (onderdeel == "Wiel_Set_Compleet") {
    wiel_set();
}

// --- NIEUWE OPTIE HIER ---
else if (onderdeel == "Wiel_Alleen") {
    hub_motor();
}

else if (onderdeel == "Kap_Links") {
    z_start = (connect_plate_thick / 2) - kap_overlap;
    translate([0,0, -z_start])
        kap(kant = -1);
}

else if (onderdeel == "Kap_Rechts") {
    z_start = (connect_plate_thick / 2) - kap_overlap;
    translate([0,0, -z_start])
        kap(kant = 1);
}

else if (onderdeel == "Bovenmodule_Links") {
    plate_z = bracket_top_z + koker_profiel + (connect_plate_thick/2);
    translate([0, 0, -plate_z]) 
        translate([-(chassis_width/2), 0, plate_z]) 
            bovenmodule(kant = -1);
}

else if (onderdeel == "Bovenmodule_Rechts") {
    plate_z = bracket_top_z + koker_profiel + (connect_plate_thick/2);
    translate([0, 0, -plate_z]) 
        translate([(chassis_width/2), 0, plate_z]) 
            bovenmodule(kant = 1);
}

else if (onderdeel == "Dwars_Koker") {
    cube([koker_lengte, koker_profiel, koker_profiel], center=true);
}

// ... (Rest van de modules blijven gelijk) ...

module verbindings_bouw() {
    plate_z = bracket_top_z + koker_profiel + (connect_plate_thick/2);
    for(x_side = [-1, 1]) {
        translate([x_side * (chassis_width/2), 0, plate_z]) {
            bovenmodule(kant = x_side);
            translate([0, 0, exploded_view ? explosion_dist * 0.8 : 0])
                color("Gray", 0.8) kap(kant = x_side);
        }
    }
}

module bovenmodule(kant = 1) {
    color("Orange") {
        difference() {
            cube([bracket_total_width, vaste_plaat_lengte, connect_plate_thick], center=true);
            for(optie_len = boor_opties_lengtes, y_dir = [-1, 1]) {
                translate([0, y_dir * (optie_len / 2), 0])
                    for(bx = [-1, 1], by = [-1, 1])
                        translate([bx * (bracket_total_width/3), by * (side_plate_top_width/3), 0])
                            cylinder(d=bolt_dia, h=connect_plate_thick + 1, center=true);
            }
        }
        
        edge_x = -kant * (bracket_total_width/2 - connect_plate_thick/2);
        translate([edge_x, 0, hoogte_opstand/2 + connect_plate_thick/2])
            cube([connect_plate_thick, vaste_plaat_lengte, hoogte_opstand], center=true);
        for(y_end = [-1, 1]) {
            difference() {
                hull() {
                    translate([edge_x + (kant * (top_breedte_zijde - connect_plate_thick) / 2), y_end * (vaste_plaat_lengte/2 - connect_plate_thick/2), hoogte_opstand + connect_plate_thick/2])
                        cube([top_breedte_zijde, connect_plate_thick, 0.01], center=true);
                    translate([0, y_end * (vaste_plaat_lengte/2 - connect_plate_thick/2), connect_plate_thick/2])
                        cube([bracket_total_width, connect_plate_thick, 0.01], center=true);
                }
                translate([edge_x + (kant * 2), y_end * (vaste_plaat_lengte/2), (hoogte_opstand + connect_plate_thick/2) - 3])
                    rotate([90, 0, 0]) cylinder(d=2, h=top_breedte_zijde + 5, center=true);
            }
        }
    }
}

module kap(kant = 1) {
    eff_b = bracket_total_width + (2 * kap_speling);
    eff_l = vaste_plaat_lengte + (2 * kap_speling);
    z_start = (connect_plate_thick / 2) - kap_overlap;
    h_wand = kap_hoogte_abs - z_start;
    
    // De hoogte van de haak (hoe ver hij achter de plaat steekt)
    haak_diepte = 10; 

    translate([0, 0, z_start]) {
        // 1. Bovenplaat (Dak)
        translate([0, 0, h_wand + kap_dikte/2])
            cube([eff_b + kap_dikte, eff_l + (2 * kap_dikte), kap_dikte], center=true);
        
        // 2. Buitenste zijwand
        translate([kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), 0, h_wand/2])
            cube([kap_dikte, eff_l + (2 * kap_dikte), h_wand], center=true);

        // 3. NIEUW: De Haakplaat (loopt achter de bovenmodule langs)
        // Deze zit aan de tegenovergestelde kant van de buitenwand
        translate([-kant * (eff_b/2 - kap_dikte/2), 0, h_wand - (haak_diepte/2)])
            cube([kap_dikte, eff_l + (2 * kap_dikte), haak_diepte], center=true);

        // 4. Voor- en achterkant (de schuine driehoeken)
        for(y_pos = [-1, 1]) {
            translate([0, y_pos * (eff_l/2 + kap_dikte/2), 0])
            rotate([270, 0, 0]) 
                linear_extrude(height = kap_dikte, center = true)
                    polygon([
                        [kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), 0],
                        [kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), -h_wand],
                        [-kant * (bracket_total_width/2 + kap_speling + 0.3), -h_wand],
                        [-kant * (top_breedte_zijde/2 + kap_speling), 0]
                    ]);
        }
        
        // 5. De borgpennen (bestaande code)
        gat_x = -kant * (bracket_total_width/2 - connect_plate_thick/2) + (kant * 2);
        gat_z = (hoogte_opstand + connect_plate_thick/2) - 3 - z_start;
        for(y_dir = [-1, 1]) {
            pen_L = (kap_speling + kap_dikte) + ((y_dir == -1) ? 3 : 2);
            translate([gat_x, y_dir * (vaste_plaat_lengte/2) - (y_dir * ((y_dir == -1) ? 3 : 2)), gat_z])
                rotate([-90 * y_dir, 0, 0]) cylinder(d=1.9, h=pen_L);
        }
    }
}

module dwars_kokers() {
    z_pos = bracket_top_z + (koker_profiel/2);
    bolt_offset_y = side_plate_top_width/3;
    color("DimGray") {
        for(y_as = [-chassis_length/2, chassis_length/2]) {
            for(koker_y_offset = [-bolt_offset_y, bolt_offset_y]) {
                translate([0, y_as + koker_y_offset, z_pos]) {
                    difference() {
                        cube([koker_lengte, koker_profiel, koker_profiel], center=true);
                        cube([koker_lengte + 0.1, koker_profiel - (2*koker_dikte), koker_profiel - (2*koker_dikte)], center=true);
                        for(optie_width = boor_opties_breedtes) {
                            for(x_dir = [-1, 1]) {
                                module_center_x = x_dir * (optie_width / 2);
                                for(bx = [-1, 1]) {
                                    hole_x = module_center_x + (bx * (bracket_total_width/3));
                                    translate([hole_x, 0, 0])
                                        cylinder(d=bolt_dia, h=koker_profiel + 1, center=true);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

module wiel_set() {
    hub_motor();
    translate([0, 0, exploded_view ? explosion_dist * 0.5 : 0]) bracket();
}

module hub_motor() {
    color("#555555") { 
        rotate([0, 90, 0]) cylinder(d=tire_dia, h=tire_width, center=true);
        rotate([0, 90, 0]) cylinder(d=hub_dia, h=hub_width, center=true);
    }
    color("Silver") rotate([0, 90, 0]) cylinder(d=axle_dia, h=21.7, center=true);
}

module bracket() {
    tip_radius = axle_dia * 2.8;
    color("#A0A0A0") { 
        difference() {
            translate([0, 0, arm_height + bracket_thick/2])
                cube([bracket_total_width, side_plate_top_width, bracket_thick], center=true);
            for(x = [-1, 1], y = [-1, 1]) {
                translate([x * (bracket_total_width/3), y * (side_plate_top_width/3), arm_height])
                    cylinder(d=bolt_dia, h=bracket_thick * 3, center=true);
            }
        }
        for(i = [-1, 1]) {
            translate([i * (inner_width/2 + bracket_thick/2), 0, 0]) {
                difference() {
                    hull() {
                        translate([0, 0, arm_height]) cube([bracket_thick, side_plate_top_width, 0.01], center=true);
                        rotate([0, 90, 0]) cylinder(r=tip_radius, h=bracket_thick, center=true);
                    }
                    
                    rotate([0, 90, 0]) {
                        cylinder(d=axle_dia + 0.1, h=bracket_thick + 0.2, center=true);
                        translate([tip_radius/2, 0, 0])
                            cube([tip_radius, axle_dia + 0.1, bracket_thick + 0.2], center=true);
                    }
                }
            }
        }
    }
}
