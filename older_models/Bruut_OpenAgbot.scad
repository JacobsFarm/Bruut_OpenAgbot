// --- SELECTIE MENU VOOR EXPORT ---
// Kies hier welk onderdeel je wilt zien en exporteren als STL
onderdeel = "Alles"; // [Alles, Beugel_Alleen, Wiel_Set_Compleet, Kap_Links, Kap_Rechts, Bovenmodule_Links, Bovenmodule_Rechts, Dwars_Koker]

// --- ORIGINELE VARIABELEN ---
chassis_width = 750;   
chassis_length = 1000; 
boor_opties_breedtes = [750, 650, 550];
boor_opties_lengtes = [750, 850, 1000];
vaste_plaat_lengte = 1300;
connect_plate_thick = 10; 

koker_profiel = 40; 
koker_dikte = 3;    
koker_lengte = 1000;

hoogte_opstand     = 500;
top_breedte_zijde  = 60;  
kap_dikte          = 5;
kap_speling        = 10;  
kap_overlap        = 10;
kap_hoogte_abs     = 530; 

$fn = 50;
exploded_view = false; 
explosion_dist = 150; 

tire_dia = 400;
tire_width = 100;
hub_dia = 160;
hub_width = 155;
axle_dia = 16;
bracket_thick = 10;
bolt_dia = 12;
side_plate_top_width = tire_width * 2.6;
arm_height = (tire_dia/2) + 30;
inner_width = hub_width + 10;
bracket_total_width = inner_width + (2 * bracket_thick);
bracket_top_z = arm_height + bracket_thick;

// --- LOGICA VOOR WEERGAVE ---

if (onderdeel == "Alles") {
    // Dit is de originele assemblage lus
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

// --- LOSSE ONDERDELEN (Voor STL Export) ---

else if (onderdeel == "Beugel_Alleen") {
    // Alleen de beugel, rechtop gezet voor makkelijke slice-orientatie
    bracket();
}

else if (onderdeel == "Wiel_Set_Compleet") {
    // Motor + Beugel samen
    wiel_set();
}

else if (onderdeel == "Kap_Links") {
    // Plaatst de kap op Z=0
    z_start = (connect_plate_thick / 2) - kap_overlap;
    translate([0,0, -z_start])
        kap(kant = -1);
}

else if (onderdeel == "Kap_Rechts") {
    // Plaatst de kap op Z=0
    z_start = (connect_plate_thick / 2) - kap_overlap;
    translate([0,0, -z_start])
        kap(kant = 1);
}

else if (onderdeel == "Bovenmodule_Links") {
    // De oranje module, verplaatst naar het nulpunt
    // We compenseren de Z-hoogte zodat hij op de plaat ligt
    plate_z = bracket_top_z + koker_profiel + (connect_plate_thick/2);
    translate([0, 0, -plate_z]) 
        translate([-(chassis_width/2), 0, plate_z]) // Neutraliseer de positie uit de assemblage
            bovenmodule(kant = -1);
}

else if (onderdeel == "Bovenmodule_Rechts") {
    plate_z = bracket_top_z + koker_profiel + (connect_plate_thick/2);
    translate([0, 0, -plate_z]) 
        translate([(chassis_width/2), 0, plate_z]) 
            bovenmodule(kant = 1);
}

else if (onderdeel == "Dwars_Koker") {
    // Eén dwarsbalk, gecentreerd
    cube([koker_lengte, koker_profiel, koker_profiel], center=true);
    // Let op: in de assemblage worden gaten geboord in de koker, 
    // als je die gaten hier ook wilt, moet de 'difference' logica hierheen gekopieerd worden.
    // Voor nu toont dit de basis koker.
}



// --- MODULES --- 

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
                            cylinder(d=bolt_dia, h=connect_plate_thick + 10, center=true);
            }
        }
        
        edge_x = -kant * (bracket_total_width/2 - connect_plate_thick/2);
        translate([edge_x, 0, hoogte_opstand/2 + connect_plate_thick/2])
            cube([connect_plate_thick, vaste_plaat_lengte, hoogte_opstand], center=true);
        for(y_end = [-1, 1]) {
            difference() {
                hull() {
                    translate([edge_x + (kant * (top_breedte_zijde - connect_plate_thick) / 2), y_end * (vaste_plaat_lengte/2 - connect_plate_thick/2), hoogte_opstand + connect_plate_thick/2])
                        cube([top_breedte_zijde, connect_plate_thick, 0.1], center=true);
                    translate([0, y_end * (vaste_plaat_lengte/2 - connect_plate_thick/2), connect_plate_thick/2])
                        cube([bracket_total_width, connect_plate_thick, 0.1], center=true);
                }
                translate([edge_x + (kant * 20), y_end * (vaste_plaat_lengte/2), (hoogte_opstand + connect_plate_thick/2) - 30])
                    rotate([90, 0, 0]) cylinder(d=20, h=top_breedte_zijde + 50, center=true);
            }
        }
    }
}

module kap(kant = 1) {
    eff_b = bracket_total_width + (2 * kap_speling);
    eff_l = vaste_plaat_lengte + (2 * kap_speling);
    z_start = (connect_plate_thick / 2) - kap_overlap;
    h_wand = kap_hoogte_abs - z_start;
    translate([0, 0, z_start]) {
        translate([0, 0, h_wand + kap_dikte/2])
            cube([eff_b + kap_dikte, eff_l + (2 * kap_dikte), kap_dikte], center=true);
        translate([kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), 0, h_wand/2])
            cube([kap_dikte, eff_l + (2 * kap_dikte), h_wand], center=true);
        for(y_pos = [-1, 1]) {
            translate([0, y_pos * (eff_l/2 + kap_dikte/2), 0])
            rotate([270, 0, 0]) 
            linear_extrude(height = kap_dikte, center = true)
                polygon([
                    [kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), 0],
                    [kant * (bracket_total_width/2 + kap_speling + kap_dikte/2), -h_wand],
                    [-kant * (bracket_total_width/2 + kap_speling + 3), -h_wand],
                    [-kant * (top_breedte_zijde/2 + kap_speling), 0]
                ]);
        }
        gat_x = -kant * (bracket_total_width/2 - connect_plate_thick/2) + (kant * 20);
        gat_z = (hoogte_opstand + connect_plate_thick/2) - 30 - z_start;
        for(y_dir = [-1, 1]) {
            pen_L = (kap_speling + kap_dikte) + ((y_dir == -1) ? 30 : 20);
            translate([gat_x, y_dir * (vaste_plaat_lengte/2) - (y_dir * ((y_dir == -1) ? 30 : 20)), gat_z])
                rotate([-90 * y_dir, 0, 0]) cylinder(d=19, h=pen_L);
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
                        cube([koker_lengte + 1, koker_profiel - (2*koker_dikte), koker_profiel - (2*koker_dikte)], center=true);
                        for(optie_width = boor_opties_breedtes) {
                            for(x_dir = [-1, 1]) {
                                module_center_x = x_dir * (optie_width / 2);
                                for(bx = [-1, 1]) {
                                    hole_x = module_center_x + (bx * (bracket_total_width/3));
                                    translate([hole_x, 0, 0])
                                        cylinder(d=bolt_dia, h=koker_profiel + 10, center=true);
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
    color("Silver") rotate([0, 90, 0]) cylinder(d=axle_dia, h=217, center=true);
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
                        translate([0, 0, arm_height]) cube([bracket_thick, side_plate_top_width, 0.1], center=true);
                        rotate([0, 90, 0]) cylinder(r=tip_radius, h=bracket_thick, center=true);
                    }
                    
                    rotate([0, 90, 0]) {
                        // Het asgat
                        cylinder(d=axle_dia + 1, h=bracket_thick + 2, center=true);
                        // De inkeping
                        translate([tip_radius/2, 0, 0])
                            cube([tip_radius, axle_dia + 1, bracket_thick + 2], center=true);
                    }
                }
            }
        }
    }
}
