import importlib
import os
import sys

sys.dont_write_bytecode = True

try:
    FOLDER = os.path.dirname(os.path.abspath(__file__))
except NameError:
    FOLDER = r"F:\Agbot\Bruut_OpenAgbot\CAD_designs\freecad"

if FOLDER not in sys.path:
    sys.path.insert(0, FOLDER)

import agbot_params
import agbot_parts
import build_agbot

for module in (agbot_params, agbot_parts, build_agbot):
    importlib.reload(module)

doc = build_agbot.build()

try:
    import FreeCADGui as Gui
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
except Exception:
    pass
