import math

# =====================================================================
# Bruut OpenAgbot - FreeCAD parameters
# Spiegel van config/parameters.scad (zelfde namen, zelfde waarden).
# Onderaan staan de nieuwe parameters voor de stuurconstructie (voorwielen).
# Assen: x = rechts, y = rijrichting (voor = +y), z = omhoog, grond = z 0.
# =====================================================================

# Global Chassis Dimensions
chassis_width = 750   # kies een veelvoud van 50
chassis_length = 1000   # kies een veelvoud van 50

# Modulair gatenpatroon
grid_step = 50   # universele stapgrootte voor alle gaten

# bolt diameters
m12_bolt_diameter = 12.4
m10_bolt_diameter = 10.4
m8_bolt_diameter = 8.4
m6_bolt_diameter = 6.4

# Bereiken voor de robot afmetingen
chassis_width_min = 350
chassis_width_max = 850
chassis_length_min = 700
chassis_length_max = 1100
base_length_min = 800
base_length_max = 1300

# Beam profile (gekocht)
beam_profile = 40
beam_thickness = 2
beam_length_1 = 1000   # onderste balken (dwars, x-richting)
beam_length_2 = 1300   # bovenste balken (lengte, y-richting)

# Upright & cover
base_plate_length = 1300
connect_plate_thick = 5
upright_height = 500
top_side_width = 60
cover_thick = 5
cover_clearance = 10
cover_overlap = 10
cover_total_height = 530
hole_distance_cover = 30

# Motor & wheel data (Quinder hubmotor met 4.00-8 tractorband)
tire_dia = 430
tire_width = 100
hub_dia = 160
hub_width = 140   # Quinder: vorkbreedte 138 mm
axle_dia = 10.2   # sleufbreedte / platte kant van de as
bolt_dia = 14.2   # ronde deel van de as

# Bracket geometry
bracket_thick = 4
bracket_bolt_diameter = 10.4
bracket_m8_bolt_diameter = 8.4
tire_clearance = 130
side_plate_top_width = 240
side_plate_width = 240

# Side plate
axle_bottom_dist = 35
extra_space_bracket = 40
side_hole_start_from_bottom = 20
side_hole_pitch = 100
tab_length = 40
tab_offset_y = 40
laser_tolerance = 1.0

# Top plate
bracket_top_hole_dist_x = 100
bracket_top_hole_dist_y = 150
bracket_top_hole_distance_centrum_holes = 50

arm_height = (tire_dia / 2) + tire_clearance
inner_width = hub_width
bracket_total_width = inner_width + (extra_space_bracket * 2) + (2 * bracket_thick)
bracket_top_z = arm_height + bracket_thick

# Axle bracket
axle_hex_width = 110
axle_hex_height = 40
axle_hex_straight_part = 30
axle_bracket_thickness = 4
axle_hole_diameter = 10.3
axle_hole_distance = 40
axle_flat_width = axle_dia
axle_round_dia = bolt_dia


# =====================================================================
# Nieuw voor FreeCAD: wiel, hubmotor en bevestigingsmiddelen
# =====================================================================
ground_to_axle = tire_dia / 2   # as-hoogte boven de grond
rim_dia = 8 * 25.4   # 8 inch velg
tire_bead_width = 86   # breedte van de band op de velg
tire_lug_height = 14   # tractorprofiel binnen tire_dia (0 = gladde band)
tire_lug_count = 22   # noppen per helft
tire_lug_width = 14
tire_lug_length = 50
tire_lug_angle = 40   # graden t.o.v. de aslijn (chevron)
tire_lug_center = 26   # axiale positie van het hart van de noppen
hub_cover_dia = 150   # motorhuis zijdeksel
hub_shoulder_dia = 32   # asschouder tegen de vorkplaat
hub_shoulder_len = 8
axle_length = 186
axle_nut_af = 22   # M14
axle_nut_thick = 11
axle_washer_dia = 28
axle_washer_thick = 2.5

m10_head_af = 17
m10_head_k = 6.4
m10_nut_m = 8.4
m8_head_af = 13
m8_head_k = 5.3
m8_nut_m = 6.8
rod_dia = 10

rear_bolt_nut_clearance = 3   # draaduiteinde onder de moer


# =====================================================================
# Nieuw voor FreeCAD: stuurconstructie voorwielen
# Afgeleid van de foto's (niet in de OpenSCAD bestanden aanwezig)
# =====================================================================
steering_gap = 55   # bovenkant top plate -> onderkant onderste balken; achter gevuld door houten blok
steer_left_deg = 0.0   # stuurhoek linkervoorwiel (+ = naar links)
steer_right_deg = 0.0   # stuurhoek rechtervoorwiel

# stappenmotorplaat (STEP "PLOATIE 2"): 190 x 160 x 5, 150 x 100 gatenpatroon
steer_plate_length = bracket_top_hole_dist_y + beam_profile   # 190, langs y
steer_plate_width = 160   # langs x
steer_plate_thick = 5
steer_plate_center_hole = 61.0   # gat voor de planeetkast
steer_plate_slot_width = 7.0   # NEMA34 sleuven op de diagonalen
steer_plate_slot_r_in = 44.14
steer_plate_slot_r_out = 54.14
steer_plate_extra_hole_dia = 17.0   # twee extra gaten op r 65
steer_plate_extra_hole_r = 65.0
steer_plate_extra_hole_angle = 120.0

# lagerplaten: zelfde buitenmaat, middengat voor het lager, patroon UCF205
bearing_plate_center_hole = 40.0

# draaipunt-flens op de top plate (4x M8 op 50 x 50)
hub_flange_dia = 90
hub_flange_thick = 8

# stuuras en flenslagers (UCF205, blauw)
shaft_dia = 25
bearing_flange = 95
bearing_flange_thick = 13
bearing_total_height = 33
bearing_boss_dia = 60
bearing_bolt_pitch = 76.5
bearing_bolt_hole = 12.5
bearing_ring_dia = 38
bearing_ring_len = 36

# koppeling en stappenmotor (NEMA34 + 5:1 planeetkast)
coupling_dia = 40
coupling_len = 45
coupling_gap = 8   # bovenkant bovenste lager -> onderkant koppeling
stepper_plate_clearance = 55   # bovenkant bovenste lager -> onderkant stappenmotorplaat
gearbox_size = 90
gearbox_len = 85
gearbox_pilot_dia = 60
motor_size = 86
motor_len = 150
stepper_chamfer = 7
gearbox_shaft_dia = 14

# draadstangen M10 die de stuurkop op het frame klemmen
rod_below_nut = 5
rod_above_nut = 45

# houten afstandsblokken op de achterste wielunits
spacer_block_width = 140   # langs x
spacer_block_length = 190   # langs y

# GNSS antenne
gnss_dome_dia = 150
gnss_dome_height = 55
gnss_stem_dia = 30
gnss_stem_height = 25
gnss_stud_dia = 8
gnss_stud_length = 90


# =====================================================================
# Afgeleide waarden (zelfde logica als main_assembly_4wd.scad)
# =====================================================================
def _round_half_up(value):
    return math.floor(value + 0.5)


stappen_x = _round_half_up((chassis_width - chassis_width_min) / (2 * grid_step))
align_width = chassis_width_min + (stappen_x * (2 * grid_step))
stappen_y = _round_half_up((chassis_length - chassis_length_min) / (2 * grid_step))
align_length = chassis_length_min + (stappen_y * (2 * grid_step))

# lokale z (as = 0), na het stapelen van de lagen
z_top_plate_bot = arm_height
z_top_plate_top = bracket_top_z
z_lower_beam_bot = z_top_plate_top + steering_gap
z_lower_beam_top = z_lower_beam_bot + beam_profile
z_upper_beam_bot = z_lower_beam_top
z_upper_beam_top = z_upper_beam_bot + beam_profile

# stuurstapel (alleen voorwielen)
z_hub_flange_top = z_top_plate_top + hub_flange_thick
z_lower_plate_top = z_lower_beam_bot
z_lower_plate_bot = z_lower_plate_top - steer_plate_thick
z_lower_bearing_end = z_lower_plate_bot - bearing_total_height
z_upper_plate_bot = z_upper_beam_top
z_upper_plate_top = z_upper_plate_bot + steer_plate_thick
z_upper_bearing_end = z_upper_plate_top + bearing_total_height
z_coupling_bot = z_upper_bearing_end + coupling_gap
z_coupling_top = z_coupling_bot + coupling_len
z_stepper_plate_bot = z_upper_bearing_end + stepper_plate_clearance
z_stepper_plate_top = z_stepper_plate_bot + steer_plate_thick
z_gearbox_top = z_stepper_plate_top + gearbox_len
z_motor_top = z_gearbox_top + motor_len
