import os

import FreeCAD as App
import Part
from FreeCAD import Vector as V

import agbot_params as P
import agbot_parts as G

DOC_NAME = "Bruut_OpenAgbot"
FOLDER = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(FOLDER, "Bruut_OpenAgbot.FCStd")

COLOR = {
    "tire": (0.07, 0.07, 0.07),
    "rim": (0.14, 0.14, 0.15),
    "hub": (0.32, 0.33, 0.35),
    "axle": (0.78, 0.79, 0.81),
    "fork": (0.46, 0.47, 0.50),
    "top_plate": (0.50, 0.38, 0.30),
    "zinc": (0.82, 0.84, 0.87),
    "beam_lower": (0.47, 0.31, 0.22),
    "beam_upper": (0.11, 0.11, 0.12),
    "bearing": (0.10, 0.27, 0.62),
    "stepper": (0.06, 0.06, 0.07),
    "wood": (0.74, 0.54, 0.31),
    "white": (0.96, 0.96, 0.95),
    "base_plate": (0.62, 0.63, 0.66),
    "wall": (0.95, 0.55, 0.10),
    "cover": (0.15, 0.62, 0.25),
}

UNITS = {
    "RL": (-1, -1, False),
    "RR": (1, -1, False),
    "FL": (-1, 1, True),
    "FR": (1, 1, True),
}


def new_part(doc, parent, name, label, pos=(0.0, 0.0, 0.0), rot_z=0.0):
    part = doc.addObject("App::Part", name)
    part.Label = label
    part.Placement = App.Placement(V(*pos), App.Rotation(V(0, 0, 1), rot_z))
    if parent is not None:
        parent.addObject(part)
    return part


SMOOTH = ("tire", "rim", "hub", "white")


def add_shape(doc, parent, name, label, shape, color, pos=None, visible=True, smooth=False):
    if isinstance(shape, (list, tuple)):
        shape = Part.makeCompound(list(shape))
    obj = doc.addObject("Part::Feature", name)
    obj.Label = label
    obj.Shape = shape
    if pos is not None:
        obj.Placement = App.Placement(V(*pos), App.Rotation()).multiply(obj.Placement)
    parent.addObject(obj)
    view = obj.ViewObject
    if view is not None:
        view.ShapeColor = color
        view.Visibility = visible
        if smooth:
            view.DisplayMode = "Shaded"
    return obj


def make_shapes():
    housing, ring = G.flange_bearing_parts()
    lower_housing = G.moved(G.rotated(housing, 180.0, G.X), z=P.z_lower_plate_bot)
    lower_ring = G.moved(G.rotated(ring, 180.0, G.X), z=P.z_lower_plate_bot)
    plate = G.bearing_plate()
    return {
        "tire": G.tire(),
        "rim": G.rim(),
        "hub_motor": G.hub_motor(),
        "axle": G.axle(),
        "wheel_hardware": G.wheel_hardware(),
        "top_plate": G.top_plate(),
        "side_plate": {-1: G.side_plate(-1), 1: G.side_plate(1)},
        "axle_bracket": {-1: G.axle_bracket(-1), 1: G.axle_bracket(1)},
        "spacer_block": G.spacer_block(),
        "frame_bolts": G.frame_bolts_rear(),
        "hub_flange": G.hub_flange(),
        "hub_flange_hardware": G.hub_flange_hardware(),
        "pivot_shaft": G.pivot_shaft(),
        "coupling": G.coupling(),
        "lower_plate": G.moved(plate, z=P.z_lower_plate_bot),
        "upper_plate": G.moved(plate, z=P.z_upper_plate_bot),
        "lower_bearing": lower_housing,
        "lower_bearing_ring": lower_ring,
        "upper_bearing": G.moved(housing, z=P.z_upper_plate_top),
        "upper_bearing_ring": G.moved(ring, z=P.z_upper_plate_top),
        "stepper_plate": G.stepper_plate(),
        "stepper_gearbox": G.stepper_gearbox(),
        "stepper_motor": G.stepper_motor(),
        "steering_hardware": G.steering_hardware(),
    }


def build_wheel_unit(doc, parent, tag, shapes, steer_deg):
    sx, sy, front = UNITS[tag]
    x = sx * P.align_width / 2.0
    y = sy * P.align_length / 2.0
    side = "left" if sx < 0 else "right"
    where = "front" if front else "rear"
    unit = new_part(doc, parent, tag + "_unit", "wheel_unit_%s_%s" % (where, side), pos=(x, y, P.ground_to_axle))
    moving = unit
    if front:
        moving = new_part(doc, unit, tag + "_steered", "steered_part_%s_%s" % (where, side), rot_z=steer_deg)

    def add(target, key, label, shape, color):
        return add_shape(doc, target, "%s_%s" % (tag, key), "%s_%s" % (label, tag), shape, COLOR[color],
                         smooth=color in SMOOTH)

    add(moving, "tire", "tire", shapes["tire"], "tire")
    add(moving, "rim", "rim", shapes["rim"], "rim")
    add(moving, "hub", "hub_motor", shapes["hub_motor"], "hub")
    add(moving, "axle", "axle", shapes["axle"], "axle")
    add(moving, "top_plate", "bracket_top_plate", shapes["top_plate"], "top_plate")
    add(moving, "side_l", "bracket_side_plate_left", shapes["side_plate"][-1], "fork")
    add(moving, "side_r", "bracket_side_plate_right", shapes["side_plate"][1], "fork")
    add(moving, "axle_br_l", "axle_bracket_left", shapes["axle_bracket"][-1], "fork")
    add(moving, "axle_br_r", "axle_bracket_right", shapes["axle_bracket"][1], "fork")
    hardware = list(shapes["wheel_hardware"])
    if front:
        hardware += shapes["hub_flange_hardware"]
    add(moving, "wheel_hw", "wheel_hardware", hardware, "zinc")

    if front:
        add(moving, "hub_flange", "steering_hub_flange", shapes["hub_flange"], "fork")
        add(moving, "shaft", "steering_shaft", shapes["pivot_shaft"], "axle")
        add(moving, "coupling", "shaft_coupling", shapes["coupling"], "axle")
        add(unit, "lower_plate", "bearing_plate_lower", shapes["lower_plate"], "top_plate")
        add(unit, "upper_plate", "bearing_plate_upper", shapes["upper_plate"], "top_plate")
        add(unit, "lower_bearing", "flange_bearing_lower", shapes["lower_bearing"], "bearing")
        add(unit, "lower_ring", "flange_bearing_lower_ring", shapes["lower_bearing_ring"], "axle")
        add(unit, "upper_bearing", "flange_bearing_upper", shapes["upper_bearing"], "bearing")
        add(unit, "upper_ring", "flange_bearing_upper_ring", shapes["upper_bearing_ring"], "axle")
        add(unit, "stepper_plate", "stepper_plate", shapes["stepper_plate"], "zinc")
        add(unit, "gearbox", "stepper_gearbox_5to1", shapes["stepper_gearbox"], "stepper")
        add(unit, "motor", "stepper_motor_nema34", shapes["stepper_motor"], "stepper")
        add(unit, "steer_hw", "steering_hardware", shapes["steering_hardware"], "zinc")
    else:
        add(unit, "spacer", "wooden_spacer_block", shapes["spacer_block"], "wood")
        add(unit, "frame_bolts", "frame_bolts", shapes["frame_bolts"], "zinc")
    return unit


def build_chassis(doc, parent):
    chassis = new_part(doc, parent, "Chassis", "chassis_frame")
    z_lower = P.ground_to_axle + P.z_lower_beam_bot + P.beam_profile / 2.0
    z_upper = P.ground_to_axle + P.z_upper_beam_bot + P.beam_profile / 2.0

    beam_1 = G.chassis_beam_1()
    beam_1_gnss = G.chassis_beam_1([(0.0, P.m8_bolt_diameter)])
    beam_2 = G.chassis_beam_2()

    names_y = [("front_outer", 1, 1), ("front_inner", 1, -1), ("rear_inner", -1, 1), ("rear_outer", -1, -1)]
    for label, s_c, s_o in names_y:
        y = s_c * P.align_length / 2.0 + s_o * P.bracket_top_hole_dist_y / 2.0
        shape = beam_1_gnss if label == "front_outer" else beam_1
        add_shape(doc, chassis, "lower_beam_" + label, "chassis_beam_1_" + label, shape, COLOR["beam_lower"],
                  pos=(0.0, y, z_lower))
    names_x = [("left_outer", -1, -1), ("left_inner", -1, 1), ("right_inner", 1, -1), ("right_outer", 1, 1)]
    for label, s_c, s_o in names_x:
        x = s_c * P.align_width / 2.0 + s_o * P.bracket_top_hole_dist_x / 2.0
        add_shape(doc, chassis, "upper_beam_" + label, "chassis_beam_2_" + label, beam_2, COLOR["beam_upper"],
                  pos=(x, 0.0, z_upper))

    y_gnss = P.align_length / 2.0 + P.bracket_top_hole_dist_y / 2.0
    z_gnss = P.ground_to_axle + P.z_lower_beam_top
    add_shape(doc, chassis, "gnss_dome", "gnss_antenna_dome", G.gnss_dome(), COLOR["white"], pos=(0.0, y_gnss, z_gnss),
              smooth=True)
    add_shape(doc, chassis, "gnss_mount", "gnss_antenna_mount", G.gnss_mount(), COLOR["zinc"], pos=(0.0, y_gnss, z_gnss))
    return chassis


def build_optional_frame(doc, parent):
    group = new_part(doc, parent, "Optional_frame_cover", "optional_frame_cover_NOT_ON_PHOTOS")
    x = P.align_width / 2.0
    z_plate = P.ground_to_axle + P.z_upper_beam_top + P.connect_plate_thick / 2.0
    wall_x = x - (P.bracket_total_width / 2.0 - P.connect_plate_thick / 2.0) - P.connect_plate_thick / 2.0
    add_shape(doc, group, "main_base_plate", "main_base_plate", G.main_base_plate(), COLOR["base_plate"],
              pos=(x, 0.0, z_plate), visible=False)
    add_shape(doc, group, "upright_wall", "upright_wall", G.upright_wall(), COLOR["wall"],
              pos=(wall_x, 0.0, z_plate), visible=False)
    add_shape(doc, group, "protection_cover", "protection_cover", G.protection_cover(), COLOR["cover"],
              pos=(x, 0.0, z_plate), visible=False)
    return group


def set_steering(left_deg, right_deg, doc=None):
    doc = doc or App.getDocument(DOC_NAME)
    for name, angle in (("FL_steered", left_deg), ("FR_steered", right_deg)):
        doc.getObject(name).Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), angle))
    doc.recompute()


def build(save_path=SAVE_PATH, steer_left=None, steer_right=None, with_optional_frame=True):
    steer = {
        "FL": P.steer_left_deg if steer_left is None else steer_left,
        "FR": P.steer_right_deg if steer_right is None else steer_right,
    }
    if DOC_NAME in App.listDocuments():
        App.closeDocument(DOC_NAME)
    doc = App.newDocument(DOC_NAME)
    doc.Label = "Bruut OpenAgbot"
    doc.Comment = ("Gegenereerd met freecad/build_agbot.py uit freecad/agbot_params.py. "
                   "x = rechts, y = rijrichting (voor = +y), z = omhoog, grond = z 0. "
                   "Stuurhoek: Placement-rotatie van steered_part_front_left/right.")
    robot = new_part(doc, None, "Robot", "Bruut_OpenAgbot_robot")

    shapes = make_shapes()
    build_chassis(doc, robot)
    for tag in ("RL", "RR", "FL", "FR"):
        build_wheel_unit(doc, robot, tag, shapes, steer.get(tag, 0.0))
    if with_optional_frame:
        build_optional_frame(doc, robot)

    doc.recompute()
    if save_path:
        doc.saveAs(save_path)
    return doc
