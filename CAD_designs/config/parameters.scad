// Global Chassis Dimensions
chassis_width = 720; //kies een veelvoud van 80  
chassis_length = 1040; //kies een veelvoud van 80

// --- Modulair Gatenpatroon (Grid) ---
grid_step = 40; // Universele stapgrootte voor alle gaten

// --- Bereiken (Ranges) voor de Robot Afmetingen ---
// Bereik voor de BREEDTE 
chassis_width_min = 560;
chassis_width_max = 800;
chassis_width_step = 80; // Stapgrootte voor instelbare breedte

// Bereik voor de LENGTE 
chassis_length_min = 720;
chassis_length_max = 1040;
chassis_length_step = 80; // Stapgrootte voor instelbare lengte

// Bereik voor de BASE PLATE 
base_length_min = 800;
base_length_max = 1280;
base_length_step = 80;

// Beam Profile (Purchased Part)
beam_profile = 40;
beam_thickness = 3;    
beam_length_1 = 1000;
beam_length_2 = 1280;

// Upright & Cover
base_plate_length = 1300;
connect_plate_thick = 5; 
upright_height = 500;
top_side_width = 60;
cover_thick = 5;
cover_clearance = 10;  
cover_overlap = 10;
cover_total_height = 530; 
hole_distance_cover = 30;

// Resolution & Preview
$fn = 60; 
exploded_view = false; 
explosion_dist = 800; 

// Motor & Wheel Data
tire_dia = 430;
tire_width = 100;
hub_dia = 160;
hub_width = 140; //specs from Quinder are: Fork width for mounting: 138mm
axle_dia = 10.2; //specs from Quinder are: Mounting hole: max 10.2mm
bolt_dia = 14.2;

// Bracket Geometry universal
bracket_thick = 5;
bracket_bolt_diameter = 10.4; //dikte van de gaten van gaten van de wiel_bracket     
tire_clearance = 130;      
side_plate_top_width = 240;
side_plate_width = 240;

//Side plate
axle_bottom_dist = 35;
extra_space_bracket = 40;
side_hole_start_from_bottom = 20; 
side_hole_pitch = 100; 

tab_length = 40;         // Lengte van de nok/sleuf
tab_offset_y = 40;       // Positie vanaf het midden over de Y-as (uit elkaar)
laser_tolerance = 0.5;   // Extra snijspeling zodat het makkelijk in elkaar schuift

//top plate
bracket_top_hole_dist_x = 80; // De totale gewenste afstand over de X-as
bracket_top_hole_dist_y = 120; // De totale gewenste afstand over de Y-as


arm_height = (tire_dia / 2) + tire_clearance;
inner_width = hub_width;
bracket_total_width = inner_width + (extra_space_bracket*2) + (2 * bracket_thick);
bracket_top_z = arm_height + bracket_thick;

// Axle bracket
axle_hex_width = 85;          
axle_hex_height = 40;
axle_hex_straight_part = 30;   
axle_bracket_thickness = 5;    

axle_hole_diameter = 10.3; //Dikte van het gaten in de axle_bracket
axle_hole_distance = 30; //hoogte vanaf de onderkant tot de wiel ophanging

axle_flat_width = axle_dia; // Gebruikt 10.2 uit parameters 
axle_round_dia = bolt_dia;  // Gebruikt 14.2 uit parameters

// --- Caster Wheel Parameters ---  
bracket_width            = 80;  
bracket_thickness        = 5;
caster_wheel_axle_width  = 130;   
caster_wheel_axle_diameter = 20;
bracket_axle_hole_diameter = 10.4;

pivot_cylinder_dia       = 30;  
pivot_cylinder_height    = 100;  

outer_cylinder_thickness = 5;   
outer_cylinder_height    = 60;  
outer_cylinder_z_offset  = 33;   
kap_speling              = 1;   

tube_width               = 35;  
tube_thickness           = 2;   
tube_length              = 400;
tube_length_min          = 240;

