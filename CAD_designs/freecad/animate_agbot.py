import json
import math
import os

import FreeCAD as App
import Part
from FreeCAD import Vector as V

import agbot_params as P
import build_agbot

SPEED = 1000.0   # mm/s
STEER_RATE = 35.0   # graden/s, snelheid van de stappenmotoren
STEER_MAX = 25.0   # stuurhoek van het denkbeeldige middenwiel (graden)
TURN_DEG = 90.0   # totale bocht naar links
STRAIGHT_IN = 1200.0   # mm rechtuit voor de bocht
STRAIGHT_OUT = 600.0   # mm rechtuit na de bocht
ACCEL_TIME = 0.8
DECEL_TIME = 0.8
HOLD_TIME = 0.4

TAGS = ("RL", "RR", "FL", "FR")
SIDE = {"RL": -1, "RR": 1, "FL": -1, "FR": 1}
FRONT = {"RL": False, "RR": False, "FL": True, "FR": True}
ROLLING_PARTS = ("tire", "rim", "hub")
GROUND_PREFIX = "anim_ground"

_timer = None
_play = {}


def wheel_angles(delta_c):
    """Ackermann: stuurhoek links en rechts uit de hoek van het middenwiel."""
    length = float(P.align_length)
    half = float(P.align_width) / 2.0
    t = math.tan(delta_c)
    left = math.atan2(length * t, length - half * t)
    right = math.atan2(length * t, length + half * t)
    return left, right


def simulate(fps=20):
    length = float(P.align_length)
    track = float(P.align_width)
    radius = P.tire_dia / 2.0
    n_sub = 10
    dt = 1.0 / (fps * n_sub)
    d_max = math.radians(STEER_MAX)
    rate = math.radians(STEER_RATE)
    gain_down = (SPEED * (d_max / rate) / (length * d_max)) * (-math.log(math.cos(d_max)))
    turn_switch = math.radians(TURN_DEG) - gain_down

    x, y, psi = 0.0, -length / 2.0, 0.0
    delta = v = dist = dist_out = hold = t_now = 0.0
    rolls = dict.fromkeys(TAGS, 0.0)
    phase = "in"
    frames = []
    step = 0
    max_slip = 0.0
    while True:
        dl, dr = wheel_angles(delta)
        if step % n_sub == 0:
            frames.append({"t": t_now, "x": x, "y": y, "psi": psi, "v": v, "dc": delta, "dl": dl, "dr": dr,
                           "rolls": dict(rolls)})
        if phase == "in":
            v = min(SPEED, v + SPEED / ACCEL_TIME * dt)
            if dist >= STRAIGHT_IN:
                phase = "turn"
        elif phase == "turn":
            delta = min(d_max, delta + rate * dt)
            if psi >= turn_switch:
                phase = "out"
        elif phase == "out":
            delta = max(0.0, delta - rate * dt)
            if delta <= 0.0:
                phase = "straight"
                dist_out = dist
        elif phase == "straight":
            if dist - dist_out >= STRAIGHT_OUT - SPEED * DECEL_TIME / 2.0:
                phase = "stop"
        else:
            v = max(0.0, v - SPEED / DECEL_TIME * dt)
            if v <= 0.0:
                hold += dt
                if hold >= HOLD_TIME:
                    break
        dl, dr = wheel_angles(delta)
        omega = v * math.tan(delta) / length
        for tag in TAGS:
            px = SIDE[tag] * track / 2.0
            py = length if FRONT[tag] else 0.0
            vx = -omega * py
            vy = v + omega * px
            steer = (dl if SIDE[tag] < 0 else dr) if FRONT[tag] else 0.0
            fx, fy = -math.sin(steer), math.cos(steer)
            rolls[tag] += (vx * fx + vy * fy) * dt / radius
            max_slip = max(max_slip, abs(vx * math.cos(steer) + vy * math.sin(steer)))
        psi += omega * dt
        x += -v * math.sin(psi) * dt
        y += v * math.cos(psi) * dt
        dist += v * dt
        t_now += dt
        step += 1
    frames[0]["max_slip"] = max_slip
    return frames


def base_xy(frame):
    half = P.align_length / 2.0
    psi = frame["psi"]
    return frame["x"] - half * math.sin(psi), frame["y"] + half * math.cos(psi)


def apply_frame(doc, frame):
    bx, by = base_xy(frame)
    z_axis = V(0, 0, 1)
    doc.getObject("Robot").Placement = App.Placement(V(bx, by, 0), App.Rotation(z_axis, math.degrees(frame["psi"])))
    doc.getObject("FL_steered").Placement = App.Placement(V(0, 0, 0), App.Rotation(z_axis, math.degrees(frame["dl"])))
    doc.getObject("FR_steered").Placement = App.Placement(V(0, 0, 0), App.Rotation(z_axis, math.degrees(frame["dr"])))
    for tag in TAGS:
        rot = App.Rotation(V(1, 0, 0), -math.degrees(frame["rolls"][tag]))
        for part in ROLLING_PARTS:
            doc.getObject("%s_%s" % (tag, part)).Placement = App.Placement(V(0, 0, 0), rot)


def reset(doc=None):
    doc = doc or App.getDocument(build_agbot.DOC_NAME)
    identity = App.Placement()
    names = ["Robot", "FL_steered", "FR_steered"]
    names += ["%s_%s" % (tag, part) for tag in TAGS for part in ROLLING_PARTS]
    for name in names:
        doc.getObject(name).Placement = identity


def add_ground(doc, half=16000.0, step=500.0):
    remove_ground(doc)
    slab = Part.makeBox(8 * half, 8 * half, 20.0, V(-4 * half, -4 * half, -24.0))
    minor, major = [], []
    for i in range(-int(half / step), int(half / step) + 1):
        is_major = i % 4 == 0
        w = 40.0 if is_major else 16.0
        target = major if is_major else minor
        target.append(Part.makeBox(2 * half, w, 2.0, V(-half, i * step - w / 2.0, -4.0)))
        target.append(Part.makeBox(w, 2 * half, 2.0, V(i * step - w / 2.0, -half, -4.0)))
    for name, shape, color in (("slab", slab, (0.93, 0.94, 0.95)),
                               ("minor", Part.makeCompound(minor), (0.78, 0.80, 0.83)),
                               ("major", Part.makeCompound(major), (0.58, 0.61, 0.66))):
        obj = doc.addObject("Part::Feature", "%s_%s" % (GROUND_PREFIX, name))
        obj.Shape = shape
        obj.ViewObject.ShapeColor = color
        obj.ViewObject.DisplayMode = "Shaded"


def remove_ground(doc):
    for obj in list(doc.Objects):
        if obj.Name.startswith(GROUND_PREFIX):
            doc.removeObject(obj.Name)


def track_camera(frame, eye_offset=(1500.0, 1900.0, 1300.0), height=450.0, fov=40.0):
    import FreeCADGui as Gui
    from pivy import coin
    bx, by = base_xy(frame)
    cam = Gui.ActiveDocument.ActiveView.getCameraNode()
    cam.position.setValue(coin.SbVec3f(bx + eye_offset[0], by + eye_offset[1], height + eye_offset[2]))
    cam.pointAt(coin.SbVec3f(bx, by, height), coin.SbVec3f(0, 0, 1))
    cam.heightAngle.setValue(math.radians(fov))
    cam.nearDistance.setValue(20.0)
    cam.farDistance.setValue(60000.0)


def dump_frames(path, frames):
    keep = ("t", "v", "psi", "dc", "dl", "dr")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([{k: f[k] for k in keep} for f in frames], handle)


def render_frames(folder, frames, first=0, count=None, size=(720, 480), eye_offset=(1500.0, 1900.0, 1300.0), fov=40.0):
    import FreeCADGui as Gui
    doc = App.getDocument(build_agbot.DOC_NAME)
    os.makedirs(folder, exist_ok=True)
    view = Gui.ActiveDocument.ActiveView
    view.setCameraType("Perspective")
    last = len(frames) if count is None else min(len(frames), first + count)
    for i in range(first, last):
        apply_frame(doc, frames[i])
        track_camera(frames[i], eye_offset, fov=fov)
        view.saveImage(os.path.join(folder, "frame_%04d.png" % i), size[0], size[1], "White")
    return last


def render_all(folder, fps=15, size=(720, 480)):
    doc = App.getDocument(build_agbot.DOC_NAME)
    frames = simulate(fps)
    os.makedirs(folder, exist_ok=True)
    dump_frames(os.path.join(folder, "frames.json"), frames)
    add_ground(doc)
    try:
        render_frames(folder, frames, size=size)
    finally:
        stop()
    return len(frames)


def stop(restore=True):
    import FreeCADGui as Gui
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
    doc = App.getDocument(build_agbot.DOC_NAME)
    remove_ground(doc)
    if restore:
        reset(doc)
    view = Gui.ActiveDocument.ActiveView
    view.setCameraType("Orthographic")
    from pivy import coin
    cam = view.getCameraNode()
    cam.position.setValue(coin.SbVec3f(3500, -3500, 3300))
    cam.pointAt(coin.SbVec3f(0, 0, 450), coin.SbVec3f(0, 0, 1))
    Gui.SendMsgToActiveView("ViewFit")


def play(fps=25, loop=False, follow=True):
    import FreeCADGui as Gui
    from PySide import QtCore
    global _timer
    if _timer is not None:
        stop()
    doc = App.getDocument(build_agbot.DOC_NAME)
    frames = simulate(fps)
    add_ground(doc)
    Gui.ActiveDocument.ActiveView.setCameraType("Perspective")
    _play.update({"index": 0})

    def step():
        try:
            if _play["index"] >= len(frames):
                if loop:
                    _play["index"] = 0
                else:
                    stop()
                    return
            frame = frames[_play["index"]]
            _play["index"] += 1
            apply_frame(doc, frame)
            if follow:
                track_camera(frame)
        except Exception:
            stop()
            raise

    _timer = QtCore.QTimer()
    _timer.timeout.connect(step)
    _timer.start(int(1000 / fps))
