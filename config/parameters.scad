// Global Chassis Dimensions
chassis_width = 750;   
chassis_length = 1000;
drill_pattern_widths = [750, 650, 550];
drill_pattern_lengths = [750, 850, 1000];
base_plate_length = 1300;
connect_plate_thick = 10; 

// Beam Profile (Purchased Part)
beam_profile = 40;
beam_thickness = 3;    
beam_length = 1000;

// Upright & Cover
upright_height = 500;
top_side_width = 60;
cover_thick = 5;
cover_clearance = 10;  
cover_overlap = 10;
cover_total_height = 530; 

// Resolution & Preview
$fn = 60; 
exploded_view = false; 
explosion_dist = 150; 

// Motor & Wheel Data
tire_dia = 430;
tire_width = 100;
hub_dia = 160;
hub_width = 140; //specs from Quinder are: Fork width for mounting: 138mm
axle_dia = 10.2; //specs from Quinder are: Mounting hole: max 10.2mm
bolt_dia = 14.2;

// Bracket Geometry
bracket_thick = 6;
side_plate_top_width = 200;
side_plate_width = 200;
axle_bottom_dist = 35;
extra_space_bracket = 30;

arm_height = (tire_dia / 2) + 30;
inner_width = hub_width;
bracket_total_width = inner_width + (extra_space_bracket*2) + (2 * bracket_thick);
bracket_top_z = arm_height + bracket_thick;

// Axle bracket
axle_hex_width = 80;          
axle_hex_height = 40;
axle_hex_straight_part = 25;   
axle_bracket_thickness = 8;    

axle_hole_diameter = 8.2;
axle_hole_distance = 30;

axle_flat_width = axle_dia; // Gebruikt 10.2 uit parameters 
axle_round_dia = bolt_dia;  // Gebruikt 14.2 uit parameters
