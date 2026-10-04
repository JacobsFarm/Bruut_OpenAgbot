import math

import FreeCAD as App
import Part
from FreeCAD import Vector as V

import agbot_params as P

X = V(1, 0, 0)
Y = V(0, 1, 0)
Z = V(0, 0, 1)


# ---------------------------------------------------------------------
# Basisfuncties
# ---------------------------------------------------------------------
def box(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0):
    return Part.makeBox(sx, sy, sz, V(cx - sx / 2.0, cy - sy / 2.0, cz - sz / 2.0))


def cyl(d, h, axis="z", cx=0.0, cy=0.0, cz=0.0):
    r = d / 2.0
    if axis == "x":
        return Part.makeCylinder(r, h, V(cx - h / 2.0, cy, cz), X)
    if axis == "y":
        return Part.makeCylinder(r, h, V(cx, cy - h / 2.0, cz), Y)
    return Part.makeCylinder(r, h, V(cx, cy, cz - h / 2.0), Z)


def moved(shape, x=0.0, y=0.0, z=0.0):
    s = shape.copy()
    s.translate(V(x, y, z))
    return s


def rotated(shape, angle, axis=Z, base=V(0, 0, 0)):
    s = shape.copy()
    s.rotate(base, axis, angle)
    return s


def fuse_all(shapes):
    shapes = list(shapes)
    result = shapes[0]
    if len(shapes) > 1:
        result = result.fuse(shapes[1:])
    try:
        result = result.removeSplitter()
    except Exception:
        pass
    return result


def vertical_edges(shape):
    edges = []
    for e in shape.Edges:
        a = e.Vertexes[0].Point
        b = e.Vertexes[-1].Point
        if abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6 and abs(a.z - b.z) > 1e-6:
            edges.append(e)
    return edges


def profile_face(start, segments, plane="xy"):
    def pt(u, v):
        return V(u, v, 0) if plane == "xy" else V(u, 0, v)

    edges = []
    cur = pt(*start)
    for seg in segments:
        if seg[0] == "L":
            end = pt(*seg[1])
            edges.append(Part.LineSegment(cur, end).toShape())
        else:
            mid = pt(*seg[1])
            end = pt(*seg[2])
            edges.append(Part.Arc(cur, mid, end).toShape())
        cur = end
    return Part.Face(Part.Wire(edges))


def revolve_x(face):
    return face.revolve(V(0, 0, 0), X, 360)


def revolve_z(face):
    return face.revolve(V(0, 0, 0), Z, 360)


def hex_prism(af, h, z0=0.0, cx=0.0, cy=0.0):
    r = af / math.sqrt(3.0)
    pts = [V(cx + r * math.cos(math.radians(60 * i)), cy + r * math.sin(math.radians(60 * i)), z0) for i in range(6)]
    pts.append(pts[0])
    return Part.Face(Part.makePolygon(pts)).extrude(V(0, 0, h))


def nut(af, m, d):
    return hex_prism(af, m).cut(cyl(d, m + 2.0, "z", cz=m / 2.0))


def washer(od, t, d):
    return Part.makeCylinder(od / 2.0, t).cut(cyl(d, t + 2.0, "z", cz=t / 2.0))


def bolt(d, af, k, length):
    # kop z -k..0, schacht z 0..length
    return hex_prism(af, k, z0=-k).fuse(Part.makeCylinder(d / 2.0, length))


def bolt_up(d, af, k, length):
    # kop z 0..k, schacht z -length..0
    return hex_prism(af, k).fuse(Part.makeCylinder(d / 2.0, length, V(0, 0, -length)))


def along_x(shape, x0, side, y=0.0, z=0.0):
    s = rotated(shape, 90.0 * side, Y)
    s.translate(V(side * x0, y, z))
    return s


def hole_positions(min_value, max_value):
    out = []
    v = min_value
    while v <= max_value + 1e-6:
        out.extend([v, -v])
        v += P.grid_step
    return out


# ---------------------------------------------------------------------
# Wiel en hubmotor (lokaal: oorsprong = hart as, x = aslijn, z omhoog)
# ---------------------------------------------------------------------
def tire():
    w = P.tire_width / 2.0
    lug_h = P.tire_lug_height
    ro = P.tire_dia / 2.0 - lug_h
    rr = P.rim_dia / 2.0
    wb = P.tire_bead_width / 2.0
    sr = 15.0
    c = math.cos(math.radians(45.0))
    r_wall = rr + 48.0
    seg = [
        ("L", (w - sr, ro)),
        ("A", ((w - sr) + sr * c, (ro - sr) + sr * c), (w, ro - sr)),
        ("L", (w, r_wall)),
        ("A", (w - 2.0, rr + 20.0), (wb, rr)),
        ("L", (-wb, rr)),
        ("A", (-(w - 2.0), rr + 20.0), (-w, r_wall)),
        ("L", (-w, ro - sr)),
        ("A", (-((w - sr) + sr * c), (ro - sr) + sr * c), (-(w - sr), ro)),
    ]
    core = revolve_x(profile_face((-(w - sr), ro), seg))
    if lug_h <= 0:
        return core
    embed = 3.0
    lug = box(P.tire_lug_length, P.tire_lug_width, lug_h + embed)
    z_mid = ro - embed + (lug_h + embed) / 2.0
    lugs = []
    for side in (-1, 1):
        for i in range(P.tire_lug_count):
            theta = 360.0 * i / P.tire_lug_count + (180.0 / P.tire_lug_count if side < 0 else 0.0)
            s = rotated(lug, side * P.tire_lug_angle, Z)
            s.translate(V(side * P.tire_lug_center, 0, z_mid))
            s.rotate(V(0, 0, 0), X, theta)
            lugs.append(s)
    return core.fuse(lugs)


def rim():
    w = P.tire_width / 2.0
    rr = P.rim_dia / 2.0
    rh = P.hub_dia / 2.0
    seg = [("L", (-w, rr)), ("L", (w, rr)), ("L", (w, rh)), ("L", (-w, rh))]
    return revolve_x(profile_face((-w, rh), seg))


def hub_motor():
    a0 = P.hub_width / 2.0
    a1 = a0 - P.hub_shoulder_len
    a2 = P.tire_width / 2.0
    rb = P.bolt_dia / 2.0
    rs = P.hub_shoulder_dia / 2.0
    rc = P.hub_cover_dia / 2.0
    rd = P.hub_dia / 2.0
    seg = [
        ("L", (-a0, rs)), ("L", (-a1, rs)), ("L", (-a1, rc)), ("L", (-a2, rc)),
        ("L", (-a2, rd)), ("L", (a2, rd)), ("L", (a2, rc)), ("L", (a1, rc)),
        ("L", (a1, rs)), ("L", (a0, rs)), ("L", (a0, rb)), ("L", (-a0, rb)),
    ]
    return revolve_x(profile_face((-a0, rb), seg))


def axle():
    length = P.axle_length
    return cyl(P.axle_round_dia, length, "x").common(box(length + 2.0, P.axle_flat_width, P.axle_round_dia + 2.0))


def wheel_hardware():
    items = []
    x_out = P.inner_width / 2.0 + P.bracket_thick + P.axle_bracket_thickness
    nut14 = nut(P.axle_nut_af, P.axle_nut_thick, P.bolt_dia)
    washer14 = washer(P.axle_washer_dia, P.axle_washer_thick, P.bolt_dia)
    nut10 = nut(P.m10_head_af, P.m10_nut_m, P.rod_dia)
    bolt10 = bolt(P.rod_dia, P.m10_head_af, P.m10_head_k, 19.0)
    for side in (-1, 1):
        items.append(along_x(washer14, x_out, side))
        items.append(along_x(nut14, x_out + P.axle_washer_thick, side))
        for sy in (-1, 1):
            y = sy * P.axle_hole_distance
            items.append(along_x(bolt10, P.inner_width / 2.0, side, y))
            items.append(along_x(nut10, x_out, side, y))
    return items


# ---------------------------------------------------------------------
# Wielbeugel (zelfde geometrie als bracket_top_plate / bracket_side_plate / axle_bracket)
# ---------------------------------------------------------------------
def top_plate():
    t = P.bracket_thick
    zc = P.arm_height + t / 2.0
    plate = box(P.bracket_total_width, P.side_plate_top_width, t, 0, 0, zc)
    tools = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            tools.append(cyl(P.bracket_bolt_diameter, t + 10, "z",
                             sx * P.bracket_top_hole_dist_x / 2.0, sy * P.bracket_top_hole_dist_y / 2.0, zc))
            tools.append(cyl(P.bracket_m8_bolt_diameter, t + 10, "z",
                             sx * P.bracket_top_hole_distance_centrum_holes / 2.0,
                             sy * P.bracket_top_hole_distance_centrum_holes / 2.0, zc))
            tools.append(box(t + P.laser_tolerance, P.tab_length + P.laser_tolerance, t + 10,
                             sx * (P.inner_width / 2.0 + t / 2.0), sy * P.tab_offset_y, zc))
    return plate.cut(tools)


def side_plate(side):
    t = P.bracket_thick
    h_total = P.arm_height + P.axle_bottom_dist
    zc = (P.arm_height - P.axle_bottom_dist) / 2.0
    yw = P.side_plate_width - 2 * P.extra_space_bracket
    xc = -(P.inner_width / 2.0 + t / 2.0)
    parts = [box(t, yw, h_total, xc, 0, zc)]
    for sy in (-1, 1):
        parts.append(box(P.extra_space_bracket, t, h_total, xc - P.extra_space_bracket / 2.0, sy * yw / 2.0, zc))
        parts.append(box(t, P.tab_length, t, xc, sy * P.tab_offset_y, P.arm_height + t / 2.0))
    plate = fuse_all(parts)
    tools = [
        box(t + 10, P.axle_dia, P.axle_bottom_dist + 8, xc, 0, -P.axle_bottom_dist / 2.0),
        cyl(P.axle_dia, t + 10, "x", xc, 0, 5.0),
        cyl(P.axle_hole_diameter, t + 10, "x", xc, P.axle_hole_distance, 0),
        cyl(P.axle_hole_diameter, t + 10, "x", xc, -P.axle_hole_distance, 0),
    ]
    z = -P.axle_bottom_dist + P.side_hole_start_from_bottom
    z_end = P.arm_height - P.side_hole_start_from_bottom
    while z <= z_end + 1e-6:
        for sy in (-1, 1):
            tools.append(cyl(P.bracket_bolt_diameter, t + 20, "y", xc - P.extra_space_bracket / 2.0, sy * yw / 2.0, z))
        z += P.side_hole_pitch
    plate = plate.cut(tools)
    if side > 0:
        plate = rotated(plate, 180.0)
    return plate


def axle_bracket(side):
    t = P.axle_bracket_thickness
    x0 = P.inner_width / 2.0 + P.bracket_thick
    hw = P.axle_hex_width / 2.0
    hs = P.axle_hex_straight_part / 2.0
    hh = P.axle_hex_height / 2.0
    pts = [(hw, hs), (hw, -hs), (0, -hh), (-hw, -hs), (-hw, hs), (0, hh)]
    wire = Part.makePolygon([V(x0, y, z) for (y, z) in pts] + [V(x0, pts[0][0], pts[0][1])])
    solid = Part.Face(wire).extrude(V(t, 0, 0))
    xm = x0 + t / 2.0
    d_hole = cyl(P.axle_round_dia, t + 2, "x", xm).common(box(t + 2, P.axle_flat_width, P.axle_round_dia + 2, xm))
    holes = [cyl(P.axle_hole_diameter, t + 2, "x", xm, sy * P.axle_hole_distance, 0) for sy in (-1, 1)]
    solid = solid.cut([d_hole] + holes)
    if side < 0:
        solid = rotated(solid, 180.0)
    return solid


# ---------------------------------------------------------------------
# Frame: kokerbalken en achterste afstandsblok
# ---------------------------------------------------------------------
def tube_beam(length, positions, extra_holes=()):
    p = P.beam_profile
    t = P.beam_thickness
    tube = box(length, p, p).cut(box(length + 1.0, p - 2 * t, p - 2 * t))
    tools = [cyl(P.bracket_bolt_diameter, p + 10, "z", cx=x) for x in positions]
    tools += [cyl(d, p + 10, "z", cx=x) for (x, d) in extra_holes]
    return tube.cut(tools)


def chassis_beam_1(extra_holes=()):
    lo = P.chassis_width_min / 2.0 - P.bracket_top_hole_dist_x / 2.0
    hi = P.chassis_width_max / 2.0 + P.bracket_top_hole_dist_x / 2.0
    return tube_beam(P.beam_length_1, hole_positions(lo, hi), extra_holes)


def chassis_beam_2():
    lo = P.chassis_length_min / 2.0 - P.bracket_top_hole_dist_y / 2.0
    hi = P.chassis_length_max / 2.0 + P.bracket_top_hole_dist_y / 2.0
    return rotated(tube_beam(P.beam_length_2, hole_positions(lo, hi)), 90.0)


def spacer_block():
    h = P.steering_gap
    zc = P.z_top_plate_top + h / 2.0
    block = box(P.spacer_block_width, P.spacer_block_length, h, 0, 0, zc)
    tools = [cyl(P.bracket_bolt_diameter, h + 2, "z", sx * P.bracket_top_hole_dist_x / 2.0,
                 sy * P.bracket_top_hole_dist_y / 2.0, zc) for sx in (-1, 1) for sy in (-1, 1)]
    return block.cut(tools)


def frame_bolts_rear():
    items = []
    z_nut = P.z_top_plate_bot - P.m10_nut_m
    length = P.z_upper_beam_top - (z_nut - P.rear_bolt_nut_clearance)
    bolt10 = bolt_up(P.rod_dia, P.m10_head_af, P.m10_head_k, length)
    nut10 = nut(P.m10_head_af, P.m10_nut_m, P.rod_dia)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = sx * P.bracket_top_hole_dist_x / 2.0
            y = sy * P.bracket_top_hole_dist_y / 2.0
            items.append(moved(bolt10, x, y, P.z_upper_beam_top))
            items.append(moved(nut10, x, y, z_nut))
    return items


# ---------------------------------------------------------------------
# Stuurconstructie voorwielen
# ---------------------------------------------------------------------
def hub_flange():
    t = P.hub_flange_thick
    flange = Part.makeCylinder(P.hub_flange_dia / 2.0, t, V(0, 0, P.z_top_plate_top))
    tools = [cyl(P.m8_bolt_diameter, t + 2, "z", sx * P.bracket_top_hole_distance_centrum_holes / 2.0,
                 sy * P.bracket_top_hole_distance_centrum_holes / 2.0, P.z_top_plate_top + t / 2.0)
             for sx in (-1, 1) for sy in (-1, 1)]
    return flange.cut(tools)


def hub_flange_hardware():
    items = []
    pitch = P.bracket_top_hole_distance_centrum_holes / 2.0
    length = P.hub_flange_thick + P.bracket_thick + P.m8_nut_m + P.rear_bolt_nut_clearance
    bolt8 = bolt_up(8.0, P.m8_head_af, P.m8_head_k, length)
    nut8 = nut(P.m8_head_af, P.m8_nut_m, 8.0)
    for sx in (-1, 1):
        for sy in (-1, 1):
            items.append(moved(bolt8, sx * pitch, sy * pitch, P.z_hub_flange_top))
            items.append(moved(nut8, sx * pitch, sy * pitch, P.z_top_plate_bot - P.m8_nut_m))
    return items


def pivot_shaft():
    z_top = P.z_coupling_bot + P.coupling_len / 2.0 - 3.5
    return Part.makeCylinder(P.shaft_dia / 2.0, z_top - P.z_hub_flange_top, V(0, 0, P.z_hub_flange_top))


def flange_bearing_parts():
    f = P.bearing_flange_thick
    h = P.bearing_total_height
    s = P.bearing_flange
    flange = box(s, s, f, 0, 0, f / 2.0)
    flange = flange.makeFillet(12.0, vertical_edges(flange))
    boss = Part.makeCylinder(P.bearing_boss_dia / 2.0, h - f, V(0, 0, f))
    housing = flange.fuse(boss)
    tools = [cyl(P.bearing_ring_dia, h + 2, "z", cz=h / 2.0)]
    tools += [cyl(P.bearing_bolt_hole, f + 2, "z", sx * P.bearing_bolt_pitch / 2.0,
                  sy * P.bearing_bolt_pitch / 2.0, f / 2.0) for sx in (-1, 1) for sy in (-1, 1)]
    housing = housing.cut(tools)
    ring = Part.makeCylinder(P.bearing_ring_dia / 2.0, P.bearing_ring_len, V(0, 0, h / 2.0 - P.bearing_ring_len / 2.0))
    ring = ring.cut(cyl(P.shaft_dia, P.bearing_ring_len + 2.0, "z", cz=h / 2.0))
    return housing, ring


def bearing_plate():
    t = P.steer_plate_thick
    plate = box(P.steer_plate_width, P.steer_plate_length, t, 0, 0, t / 2.0)
    tools = [cyl(P.bearing_plate_center_hole, t + 2, "z", cz=t / 2.0)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            tools.append(cyl(P.bracket_bolt_diameter, t + 2, "z", sx * P.bracket_top_hole_dist_x / 2.0,
                             sy * P.bracket_top_hole_dist_y / 2.0, t / 2.0))
            tools.append(cyl(P.bearing_bolt_hole, t + 2, "z", sx * P.bearing_bolt_pitch / 2.0,
                             sy * P.bearing_bolt_pitch / 2.0, t / 2.0))
    return plate.cut(tools)


def stepper_plate():
    t = P.steer_plate_thick
    zc = t / 2.0
    w = P.steer_plate_slot_width
    r_in = P.steer_plate_slot_r_in
    r_out = P.steer_plate_slot_r_out
    plate = box(P.steer_plate_length, P.steer_plate_width, t, 0, 0, zc)
    tools = [cyl(P.steer_plate_center_hole, t + 2, "z", cz=zc)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            tools.append(cyl(P.bracket_bolt_diameter, t + 2, "z", sx * P.bracket_top_hole_dist_y / 2.0,
                             sy * P.bracket_top_hole_dist_x / 2.0, zc))
    slot = fuse_all([
        box(r_out - r_in, w, t + 2, (r_in + r_out) / 2.0, 0, zc),
        cyl(w, t + 2, "z", r_in, 0, zc),
        cyl(w, t + 2, "z", r_out, 0, zc),
    ])
    for a in (45.0, 135.0, 225.0, 315.0):
        tools.append(rotated(slot, a))
    for a in (P.steer_plate_extra_hole_angle, P.steer_plate_extra_hole_angle + 180.0):
        r = P.steer_plate_extra_hole_r
        tools.append(cyl(P.steer_plate_extra_hole_dia, t + 2, "z", r * math.cos(math.radians(a)),
                         r * math.sin(math.radians(a)), zc))
    return moved(rotated(plate.cut(tools), 90.0), z=P.z_stepper_plate_bot)


def coupling():
    z0 = P.z_coupling_bot
    hub = (P.coupling_len - 5.0) / 2.0
    d = P.coupling_dia
    lower = Part.makeCylinder(d / 2.0, hub, V(0, 0, z0)).cut(
        Part.makeCylinder(P.shaft_dia / 2.0, hub + 2.0, V(0, 0, z0 - 1.0)))
    spider = Part.makeCylinder(d / 2.0 - 4.0, 5.0, V(0, 0, z0 + hub))
    upper = Part.makeCylinder(d / 2.0, hub, V(0, 0, z0 + hub + 5.0)).cut(
        Part.makeCylinder(P.gearbox_shaft_dia / 2.0, hub + 2.0, V(0, 0, z0 + hub + 4.0)))
    z_shaft = z0 + hub + 6.0
    out_shaft = Part.makeCylinder(P.gearbox_shaft_dia / 2.0, P.z_stepper_plate_top - z_shaft, V(0, 0, z_shaft))
    return [lower, spider, upper, out_shaft]


def stepper_gearbox():
    g = P.gearbox_size
    body = box(g, g, P.gearbox_len, 0, 0, P.gearbox_len / 2.0)
    body = body.makeChamfer(P.stepper_chamfer, vertical_edges(body))
    boss = Part.makeCylinder(P.gearbox_pilot_dia / 2.0, P.steer_plate_thick, V(0, 0, -P.steer_plate_thick))
    boss = boss.cut(cyl(P.gearbox_shaft_dia, P.steer_plate_thick + 2.0, "z", cz=-P.steer_plate_thick / 2.0))
    return moved(body.fuse(boss), z=P.z_stepper_plate_top)


def stepper_motor():
    m = P.motor_size
    body = box(m, m, P.motor_len, 0, 0, P.motor_len / 2.0)
    body = body.makeChamfer(P.stepper_chamfer, vertical_edges(body))
    return moved(body, z=P.z_gearbox_top)


def steering_hardware():
    items = []
    nut10 = nut(P.m10_head_af, P.m10_nut_m, P.rod_dia)
    z_bot = P.z_lower_plate_bot - P.m10_nut_m - P.rod_below_nut
    z_top = P.z_stepper_plate_top + P.m10_nut_m + P.rod_above_nut
    rod = Part.makeCylinder(P.rod_dia / 2.0, z_top - z_bot, V(0, 0, z_bot))
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = sx * P.bracket_top_hole_dist_x / 2.0
            y = sy * P.bracket_top_hole_dist_y / 2.0
            items.append(moved(rod, x, y))
            for z in (P.z_lower_plate_bot - P.m10_nut_m, P.z_upper_plate_top, P.z_stepper_plate_bot - P.m10_nut_m,
                      P.z_stepper_plate_top):
                items.append(moved(nut10, x, y, z))
    pitch = P.bearing_bolt_pitch / 2.0
    f = P.bearing_flange_thick
    upper_bolt = bolt_up(P.rod_dia, P.m10_head_af, P.m10_head_k, f + P.steer_plate_thick)
    lower_bolt = bolt_up(P.rod_dia, P.m10_head_af, P.m10_head_k, f + P.steer_plate_thick + P.m10_nut_m + P.rear_bolt_nut_clearance)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = sx * pitch
            y = sy * pitch
            items.append(moved(upper_bolt, x, y, P.z_upper_plate_top + f))
            items.append(moved(lower_bolt, x, y, P.z_lower_plate_top))
            items.append(moved(nut10, x, y, P.z_lower_plate_bot - f - P.m10_nut_m))
    return items


# ---------------------------------------------------------------------
# GNSS antenne (oorsprong = bovenkant van de balk waarop hij staat)
# ---------------------------------------------------------------------
def gnss_dome():
    r = P.gnss_dome_dia / 2.0
    z0 = P.gnss_stem_height
    h = P.gnss_dome_height
    base = 10.0
    c = math.cos(math.radians(45.0))
    seg = [
        ("L", (r, z0)),
        ("L", (r, z0 + base)),
        ("A", (r * c, z0 + base + (h - base) * c), (0, z0 + h)),
        ("L", (0, z0)),
    ]
    return revolve_z(profile_face((0, z0), seg, plane="xz"))


def gnss_mount():
    stem = Part.makeCylinder(P.gnss_stem_dia / 2.0, P.gnss_stem_height)
    z_bot = P.gnss_stem_height - P.gnss_stud_length
    stud = Part.makeCylinder(P.gnss_stud_dia / 2.0, P.gnss_stud_length, V(0, 0, z_bot))
    n = nut(P.m8_head_af, P.m8_nut_m, P.gnss_stud_dia)
    return [stem, stud, moved(n, 0, 0, -P.beam_profile - P.m8_nut_m)]


# ---------------------------------------------------------------------
# Optioneel frame met afdekkap (chassis_frame_asm.scad), niet op de foto's
# ---------------------------------------------------------------------
def main_base_plate():
    t = P.connect_plate_thick
    plate = box(P.bracket_total_width, P.base_plate_length, t)
    lo = P.base_length_min / 2.0 - P.bracket_top_hole_dist_y / 2.0
    hi = P.base_length_max / 2.0 + P.bracket_top_hole_dist_y / 2.0
    tools = []
    y = lo
    while y <= hi + 1e-6:
        for bx in (-1, 1):
            for sy in (-1, 1):
                tools.append(cyl(P.bolt_dia, t + 10, "z", bx * P.bracket_top_hole_dist_x / 2.0, sy * y))
        y += P.grid_step
    return plate.cut(tools)


def upright_wall():
    t = P.connect_plate_thick
    length = P.base_plate_length
    height = P.upright_height
    wall = box(t, length, height, t / 2.0, 0, height / 2.0)
    pts = [(0, 0), (P.bracket_total_width, 0), (P.top_side_width, height), (0, height)]
    parts = [wall]
    for sy in (-1, 1):
        y_in = sy * length / 2.0
        wire = Part.makePolygon([V(u, y_in, v) for (u, v) in pts] + [V(pts[0][0], y_in, pts[0][1])])
        flap = Part.Face(wire).extrude(V(0, -sy * t, 0))
        hole = cyl(20.0, t + 2.0, "y", P.hole_distance_cover, y_in - sy * t / 2.0, height - 30.0)
        parts.append(flap.cut(hole))
    return fuse_all(parts)


def protection_cover():
    t = P.cover_thick
    eff_b = P.bracket_total_width + 2 * P.cover_clearance
    eff_l = P.base_plate_length + 2 * P.cover_clearance
    z_start = P.connect_plate_thick / 2.0 - P.cover_overlap
    h_wand = P.cover_total_height - z_start
    x_out = P.bracket_total_width / 2.0 + P.cover_clearance + t / 2.0
    parts = [
        box(eff_b + t, eff_l + 2 * t, t, 0, 0, h_wand + t / 2.0),
        box(t, eff_l + 2 * t, h_wand, x_out, 0, h_wand / 2.0),
    ]
    pts = [
        (x_out, 0),
        (x_out, h_wand),
        (-(P.bracket_total_width / 2.0 + P.cover_clearance + 3.0), h_wand),
        (-(P.top_side_width / 2.0 + P.cover_clearance), 0),
    ]
    for sy in (-1, 1):
        y_c = sy * (eff_l / 2.0 + t / 2.0)
        wire = Part.makePolygon([V(u, y_c - t / 2.0, v) for (u, v) in pts] + [V(pts[0][0], y_c - t / 2.0, pts[0][1])])
        parts.append(Part.Face(wire).extrude(V(0, t, 0)))
    return moved(fuse_all(parts), z=z_start)
