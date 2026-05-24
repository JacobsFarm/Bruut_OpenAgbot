include <../config/parameters.scad>

module upright_wall(show_bend = true, kant = 1) {
    // kant bepaalt de vouwrichting, gecombineerd met -90 voor de gewenste richting
    bend_angle = kant * -90; 
    
    // De 2D vorm van de zijflap (plat getekend als zijaanzicht)
    module flap_geometry() {
        difference() {
            polygon(points=[
                [0, 0],                                // Hoekpunt onderaan (scharnier/flush kant)
                [bracket_total_width, 0],              // Hoekpunt onderaan buitenkant
                [top_side_width, upright_height],      // Hoekpunt bovenaan buitenkant
                [0, upright_height]                    // Hoekpunt bovenaan (scharnier/flush kant)
            ]);
            
            // Het gat zit hier altijd exact 20mm vanaf de rechte vouwlijn
            translate([hole_distance_cover, upright_height - 30])
                circle(d=20);
        }
    }

    color("Orange") {
        union() {
            translate([connect_plate_thick/2, 0, upright_height/2])
                cube([connect_plate_thick, base_plate_length, upright_height], center=true);
            
            translate([0, base_plate_length / 2, 0])
                rotate([0, 0, show_bend ? bend_angle : 0])
                    translate([connect_plate_thick/2, 0, 0])
                        rotate([90, 0, 90])
                            linear_extrude(height=connect_plate_thick, center=true)
                                flap_geometry();
            
            translate([0, -base_plate_length / 2, 0])
                rotate([0, 0, show_bend ? -bend_angle : 0]) 
                    mirror([0, 1, 0]) 
                        translate([connect_plate_thick/2, 0, 0])
                            rotate([90, 0, 90])
                                linear_extrude(height=connect_plate_thick, center=true)
                                    flap_geometry();
        }
    }
}

upright_wall(show_bend = true, kant = 1);
