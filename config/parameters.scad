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
tire_dia = 400;
tire_width = 100;
hub_dia = 160;
hub_width = 155;
axle_dia = 16;
bolt_dia = 12;

// Bracket Geometry
bracket_thick = 10;
side_plate_top_width = tire_width * 2.6;
arm_height = (tire_dia/2) + 30;
inner_width = hub_width + 10;
bracket_total_width = inner_width + (2 * bracket_thick);
bracket_top_z = arm_height + bracket_thick;