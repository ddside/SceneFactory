"""Run with Blender --background --factory-startup --python-exit-code 1 --python.

Small integration probe only; outputs are isolated from production scenes.
"""
import json
import os
from pathlib import Path
import sys

import bpy

out = Path(os.environ.get("SF_PROBE_OUTPUT", str(
    Path(__file__).resolve().parents[1] / "artifacts" / "environment")))
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string, "python": sys.version,
          "usd_build": bpy.app.build_options.usd, "tests": {}}


def test(name, action):
    try:
        action()
        report["tests"][name] = {"status": "passed"}
    except Exception as exc:
        report["tests"][name] = {"status": "failed", "error": repr(exc)}


scene = bpy.context.scene
report["engines"] = [item.identifier for item in
    scene.render.bl_rna.properties["engine"].enum_items]
cube = bpy.data.objects.get("Cube")
assert cube is not None and len(cube.data.vertices) == 8
cube["sf_id"] = "probe.cube"
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.render.resolution_x = 64
scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"


def export_usd():
    path = out / "probe.usda"
    assert bpy.ops.wm.usd_export(filepath=str(path)) == {"FINISHED"}
    assert path.stat().st_size > 0
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.Open(str(path))
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
    assert len(meshes) == 1
    report["usd"] = {"mesh_paths": [str(p.GetPath()) for p in meshes],
                     "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
                     "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage)}


def render(engine, device="CPU"):
    scene.render.engine = engine
    if engine == "CYCLES":
        scene.cycles.samples = 4
        scene.cycles.device = device
    path = out / (engine.lower() + "_" + device.lower() + ".png")
    scene.render.filepath = str(path)
    assert bpy.ops.render.render(write_still=True) == {"FINISHED"}
    assert path.stat().st_size > 0


test("usd_export_and_stage_read", export_usd)
test("cycles_cpu", lambda: render("CYCLES"))
test("eevee", lambda: render("BLENDER_EEVEE_NEXT"))


def metal():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    report["cycles_devices"] = [{"name": d.name, "type": d.type} for d in prefs.devices]
    assert any(d.type == "METAL" for d in prefs.devices)
    for d in prefs.devices:
        d.use = d.type == "METAL"
    render("CYCLES", "GPU")


test("cycles_metal", metal)
(out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print("SCENE_FACTORY_PROBE", json.dumps(report))
if any(t["status"] != "passed" for t in report["tests"].values()):
    raise RuntimeError("Probe failed; see report.json")
