// ==========================================
// PARAMETERS & INSTELLINGEN (AANPASSEN HIER)
// ==========================================

// *** WEERGAVE TOGGLES ***
toon_vertrager = false;          // Toon de Nema34 vertrager (true/false)
toon_centrumplaat = false;      // Toon losse centrumplaat 86x86 (alleen-deze-view)
toon_grote_plaat = true;        // Toon de grote montageplaat op de balken (true/false)
toon_balken = true;             // Toon de twee balken als transparante referentie (true/false)


// *** NEMA34 VERTRAGER PARAMETERS ***
vertrager_x = 18.3;             // X-positie van vertrager
vertrager_y = 45.8;             // Y-positie van vertrager
vertrager_z = 0;                // Z-positie van vertrager
vertrager_rot_x = 270;          // Rotatie X-as
vertrager_rot_y = 0;            // Rotatie Y-as
vertrager_rot_z = 0;            // Rotatie Z-as


// *** CENTRUMPLAAT PARAMETERS (losse view) ***
plaat_lengte = 86;              // Lengte van de plaat (mm)
plaat_breedte = 86;             // Breedte van de plaat (mm)
plaat_dikte = 3;                // Dikte van de plaat (mm)
centraal_gat = 60;              // Diameter centraal gat (mm)
hoek_gat = 6.5;                 // Diameter hoekgaten (mm) - M6 boormaat
gat_afstand = 69.5;             // Afstand tussen gaten centrum-tot-centrum (mm)
plaat_x = 0;                    // X-positie van plaat
plaat_y = 0;                    // Y-positie van plaat
plaat_z = 0;                    // Z-positie van plaat


// *** GROTE MONTAGEPLAAT PARAMETERS ***
// De plaat ligt OP de twee onderste dwarsbalken (chassis_beam_1).
// X = langs de balken, Y = dwars over de balken.
grote_plaat_y = 150;            // Maat dwars over de balken (mm) - "lengte"
grote_plaat_x = 150;            // Maat langs de balken (mm) - "breedte"
grote_plaat_dikte = 5;          // Dikte van de grote plaat (mm)
grote_plaat_z = 0;              // Z-positie (midden van de plaat)

grote_plaat_auto_y = true;     // true = Y-maat automatisch = balkafstand + 2x randmarge
grote_plaat_rand = 20;          // Randmarge rond het balkgat bij auto-maat (mm)

grote_plaat_met_reducer_gaten = true;  // Centraal gat + 4 reducergaten ook in de grote plaat

// *** BALKGATEN (bevestiging op de kokerbalken) ***
// volg_grid = true : de gaten worden 1-op-1 overgenomen uit het gatenpatroon
//                    van chassis_beam_1 (vanaf 125 mm uit het hart, stappen
//                    van grid_step = 50, dus 125/175/225 ... 475).
//                    Zet plaat_positie_x op de plek waar het HART van de
//                    plaat op de balk komt; elk gridgat dat met genoeg rand
//                    binnen de plaat valt wordt automatisch uitgesneden.
// volg_grid = false: vrij patroon via balk_gaten_per_balk / balk_gat_pitch.
balk_gaten_volgen_grid = true;
plaat_positie_x = 175;          // X-positie van plaat-hart op de balk (chassis-coordinaat)
balk_gat_rand = 10;             // Minimale rand van uitsparing tot plaatrand (mm)

// centreer_op_gridgat = true: plaat_positie_x wordt naar het dichtstbijzijnde
//   gridgat geschoven, zodat er een gat EXACT in het hart van de plaat komt.
//   Met een plaatmaat van 150 langs de balk levert dat 3 gaten per balk op
//   (-50 / 0 / +50) en ligt het middelste gat in lijn met het hart van de
//   vertrager. Zet op false om de plaat vrij te positioneren.
centreer_op_gridgat = true;

balk_gat_speling = 0;           // Extra speling op de gatdiameter (mm)
balk_gaten_per_balk = 2;        // Vrij patroon: aantal gaten per balk (1 of meer)
balk_gat_pitch = 50;            // Vrij patroon: hart-op-hart afstand langs de balk (mm)
balk_gat_offset_x = 0;          // Vrij patroon: verschuiving van het patroon (mm)

// *** OPOFFER-RINGEN (vervangbare boorbussen) ***
// false = vaste plaat, de gaten zitten direct in de plaat
// true  = de plaat krijgt ruime uitsparingen en de boorgaten zitten in losse
//         ringen die je kunt vervangen als ze uitgeboord zijn.
// De balkgaten krijgen een M10-ring, de 4 reducergaten een M6-ring.
gebruik_bushings         = true;  // M10-ringen op de balkgaten
gebruik_reducer_bushings = true;  // M6-ringen op de 4 reducergaten
toon_bushings    = false;        // Ringen meerenderen
bushings_vlak    = false;       // false = ringen op hun plek, true = los ernaast om te printen

tpl_bush_wall     = 5;          // Wanddikte (breedte) van de opoffer-ring
tpl_bush_fit      = 0.2;        // Speling tussen ring en uitsparing in de plaat (persfit)
tpl_bush_collar_h = 2;          // Dikte van de kraag die bovenop de plaat rust
tpl_bush_collar_w = 2;          // Extra breedte van de kraag per kant (om hem eruit te wippen)
tpl_bush_pitch    = 5;          // Ruimte tussen de ringen in de vlakke printopstelling
tpl_bush_vlak_y   = 160;        // Y-positie van de rij losse ringen

toon_losse_bushing_m10 = false; // Alleen 1 losse M10 vervangingsring renderen
toon_losse_bushing_m6  = false; // Alleen 1 losse M6 vervangingsring renderen

// *** BALK REFERENTIE (alleen weergave) ***
balk_lengte = 300;              // Getoonde lengte van de referentiebalken (mm)


// ==========================================
// EXTERNAL DATA (Linked)
// ==========================================
include <../config/parameters.scad>;
use <drill_bushing_m10.scad>;
use <drill_bushing_m6.scad>;


// ==========================================
// AFGELEIDE MATEN
// ==========================================
balk_hart_afstand = bracket_top_hole_dist_y;
balk_gat_diameter = bracket_bolt_diameter + balk_gat_speling;

bush_pocket_d = bushing_m10_pocket_d(tpl_bush_wall, tpl_bush_fit);
bush_collar_d = bushing_m10_collar_d(tpl_bush_wall, tpl_bush_collar_w);

bush_m6_pocket_d = bushing_m6_pocket_d(tpl_bush_wall, tpl_bush_fit);
bush_m6_collar_d = bushing_m6_collar_d(tpl_bush_wall, tpl_bush_collar_w);

balk_uitsparing_d = gebruik_bushings ? bush_pocket_d : balk_gat_diameter;
hoek_uitsparing_d = gebruik_reducer_bushings ? bush_m6_pocket_d : hoek_gat;

plaat_y_maat = grote_plaat_auto_y
    ? balk_hart_afstand + (2 * grote_plaat_rand)
    : grote_plaat_y;

grid_min_x = (chassis_width_min / 2) - (bracket_top_hole_dist_x / 2);
grid_max_x = (chassis_width_max / 2) + (bracket_top_hole_dist_x / 2);

grid_xs = [for (x = [grid_min_x : grid_step : grid_max_x]) each [x, -x]];

grid_n_max = floor((grid_max_x - grid_min_x) / grid_step);

function snap_naar_gridgat(x) =
    let (teken = x < 0 ? -1 : 1,
         n = max(0, min(round((abs(x) - grid_min_x) / grid_step), grid_n_max)))
    teken * (grid_min_x + (n * grid_step));

plaat_hart_x = centreer_op_gridgat
    ? snap_naar_gridgat(plaat_positie_x)
    : plaat_positie_x;

max_lokaal_x = (grote_plaat_x / 2) - (balk_uitsparing_d / 2) - balk_gat_rand;

grid_gat_xs = [for (x = grid_xs)
                  if (abs(x - plaat_hart_x) <= max_lokaal_x) x - plaat_hart_x];

vrij_gat_xs = balk_gaten_per_balk == 1
    ? [balk_gat_offset_x]
    : [for (i = [0 : balk_gaten_per_balk - 1])
          balk_gat_offset_x + (i - (balk_gaten_per_balk - 1) / 2) * balk_gat_pitch];

balk_gat_xs = balk_gaten_volgen_grid ? grid_gat_xs : vrij_gat_xs;

rand_x = (grote_plaat_x / 2) - max([for (x = balk_gat_xs) abs(x)]) - (balk_uitsparing_d / 2);
rand_y = (plaat_y_maat / 2) - (balk_hart_afstand / 2) - (balk_uitsparing_d / 2);

echo(str("Plaat-hart op de balk (X): ", plaat_hart_x));
echo(str("Balkgaten per balk: ", len(balk_gat_xs)));
echo(str("Gatposities lokaal in de plaat (X): ", balk_gat_xs));
echo(str("Gatposities op de chassisbalk (X): ",
         [for (x = balk_gat_xs) x + plaat_hart_x]));
echo(str("Plaatmaat: ", grote_plaat_x, " x ", plaat_y_maat, " x ", grote_plaat_dikte));
echo(str("Uitsparing balkgat (diameter): ", balk_uitsparing_d));
echo(str("Materiaalrand bij balkgat - X: ", rand_x, "  Y: ", rand_y));
echo(str("Uitsparing reducergat (diameter): ", hoek_uitsparing_d,
         "  boormaat: ", gebruik_reducer_bushings ? bushing_m6_hole_d() : hoek_gat));


// ==========================================
// 1. NEMA34 VERTRAGER
// ==========================================
if (toon_vertrager) {
    translate([vertrager_x, vertrager_y, vertrager_z]) {
        rotate([vertrager_rot_x, vertrager_rot_y, vertrager_rot_z]) { 
            import("../imports/Nema34 5_1 Reducer.stl", convexity = 5);
        }
    }
}


// ==========================================
// 2. REDUCER GATENPATROON (gedeeld)
// ==========================================
module reducerGaten(dikte, c_gat, h_gat, h_afstand) {
    // Centraal gat
    cylinder(h = dikte + 1, r = c_gat / 2, center = true, $fn = 100);

    // Vier hoekgaten - vierkant patroon met h_afstand van centrum
    gat_offset = h_afstand / 2;

    for (sx = [-1, 1], sy = [-1, 1]) {
        translate([sx * gat_offset, sy * gat_offset, 0]) {
            cylinder(h = dikte + 1, r = h_gat / 2, center = true, $fn = 64);
        }
    }
}


// ==========================================
// 3. CENTRUMPLAAT MODULE
// ==========================================
module centreringPlaat(
    lengte,
    breedte,
    dikte,
    c_gat,
    h_gat,
    h_afstand
) {
    difference() {
        // Basis plaat
        cube([lengte, breedte, dikte], center = true);

        reducerGaten(dikte, c_gat, h_gat, h_afstand);
    }
}


// ==========================================
// 4. GROTE MONTAGEPLAAT MODULE
// ==========================================
module grotePlaat(
    x_maat,
    y_maat,
    dikte,
    balk_afstand,
    gat_d,
    gat_xs,
    met_reducer_gaten,
    c_gat,
    h_gat,
    h_afstand
) {
    difference() {
        // Basis plaat
        cube([x_maat, y_maat, dikte], center = true);

        // Gaten van de twee balken
        for (sy = [-1, 1]) {
            for (gx = gat_xs) {
                translate([gx, sy * (balk_afstand / 2), 0]) {
                    cylinder(h = dikte + 2, d = gat_d, center = true, $fn = 64);
                }
            }
        }

        // Doorvoer voor de vertrager
        if (met_reducer_gaten) {
            reducerGaten(dikte + 1, c_gat, h_gat, h_afstand);
        }
    }
}


// ==========================================
// 5. OPOFFER-RINGEN (uit drill_bushing_m10.scad)
// ==========================================
// Origin van een ring ligt op de BOVENKANT van de plaat.

module bushingsOpPlek(balk_afstand, gat_xs, h_afstand, dikte, plaat_z_pos) {
    boven_z = plaat_z_pos + (dikte / 2);

    if (gebruik_bushings) {
        for (sy = [-1, 1]) {
            for (gx = gat_xs) {
                translate([gx, sy * (balk_afstand / 2), boven_z]) {
                    bushing_m10(dikte, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
                }
            }
        }
    }

    if (gebruik_reducer_bushings) {
        for (sx = [-1, 1], sy = [-1, 1]) {
            translate([sx * (h_afstand / 2), sy * (h_afstand / 2), boven_z]) {
                bushing_m6(dikte, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
            }
        }
    }
}

module bushingsVlak(aantal_m10, aantal_m6, dikte) {
    stap = bush_collar_d + tpl_bush_pitch;
    totaal = aantal_m10 + aantal_m6;
    x0 = -((totaal - 1) * stap) / 2;

    for (i = [0 : totaal - 1]) {
        translate([x0 + (i * stap), tpl_bush_vlak_y, 0]) {
            if (i < aantal_m10) {
                bushing_m10_flat(dikte, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
            } else {
                bushing_m6_flat(dikte, tpl_bush_wall, tpl_bush_collar_h, tpl_bush_collar_w);
            }
        }
    }
}


// ==========================================
// 6. BALK REFERENTIE MODULE
// ==========================================
module balkReferentie(lengte, balk_afstand, plaat_dik, plaat_z_pos, positie_x) {
    z_pos = plaat_z_pos - (plaat_dik / 2) - (beam_profile / 2);

    for (sy = [-1, 1]) {
        translate([0, sy * (balk_afstand / 2), z_pos]) {
            difference() {
                // Kokerprofiel
                cube([lengte, beam_profile, beam_profile], center = true);

                // Holle binnenkant
                cube([lengte + 1,
                      beam_profile - (2 * beam_thickness),
                      beam_profile - (2 * beam_thickness)], center = true);

                // Het echte gatenpatroon van chassis_beam_1
                for (x = grid_xs) {
                    if (abs(x - positie_x) <= lengte / 2) {
                        translate([x - positie_x, 0, 0]) {
                            cylinder(d = bracket_bolt_diameter,
                                     h = beam_profile + 10, center = true, $fn = 32);
                        }
                    }
                }
            }
        }
    }
}


// ==========================================
// 7. RENDER
// ==========================================
if (toon_losse_bushing_m10) {
    color("Tomato")
        bushing_m10_flat(grote_plaat_dikte, tpl_bush_wall,
                         tpl_bush_collar_h, tpl_bush_collar_w);

} else if (toon_losse_bushing_m6) {
    color("Tomato")
        bushing_m6_flat(grote_plaat_dikte, tpl_bush_wall,
                        tpl_bush_collar_h, tpl_bush_collar_w);

} else {
    if (toon_centrumplaat) {
        translate([plaat_x, plaat_y, plaat_z]) {
            centreringPlaat(
                plaat_lengte,
                plaat_breedte,
                plaat_dikte,
                centraal_gat,
                hoek_gat,
                gat_afstand
            );
        }
    }

    if (toon_grote_plaat) {
        color("DodgerBlue")
        translate([0, 0, grote_plaat_z]) {
            grotePlaat(
                grote_plaat_x,
                plaat_y_maat,
                grote_plaat_dikte,
                balk_hart_afstand,
                balk_uitsparing_d,
                balk_gat_xs,
                grote_plaat_met_reducer_gaten,
                centraal_gat,
                hoek_uitsparing_d,
                gat_afstand
            );
        }
    }

    if ((gebruik_bushings || gebruik_reducer_bushings) && toon_bushings) {
        color("Tomato") {
            if (bushings_vlak) {
                bushingsVlak(gebruik_bushings ? 2 * len(balk_gat_xs) : 0,
                             gebruik_reducer_bushings ? 4 : 0,
                             grote_plaat_dikte);
            } else {
                bushingsOpPlek(balk_hart_afstand, balk_gat_xs, gat_afstand,
                               grote_plaat_dikte, grote_plaat_z);
            }
        }
    }

    if (toon_balken) {
        %balkReferentie(
            balk_lengte,
            balk_hart_afstand,
            grote_plaat_dikte,
            grote_plaat_z,
            plaat_hart_x
        );
    }
}
