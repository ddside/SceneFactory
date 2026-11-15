"""JSON worker entrypoint; execute exclusively with Blender CLI."""
import json
from pathlib import Path
import sys
import traceback

# Blender doesn't inherit application site-packages. Only import this package's
# source from its own location (also works in an installed wheel).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bpy

from scene_factory.spec import load_spec, example_spec
from scene_factory.blender.generators import generate
from scene_factory.blender.validation import validate_scene
from scene_factory.blender.rendering import inventory, render


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def execute(request, out):
    if bpy.app.version[:2] != (4, 5) or sys.version_info[:2] != (3, 11):
        raise RuntimeError("Requires Blender 4.5 LTS with built-in Python 3.11")
    action = request["action"]
    metadata = {"blender": bpy.app.version_string, "blender_hash": bpy.app.build_hash.decode(),
                "blender_python": sys.version, "action": action}
    if action == "doctor":
        generate(example_spec())
        devices = inventory()
        probes = []
        targets = [("CYCLES", d) for d in sorted({v["backend"] for v in devices["devices"]})]
        targets.append(("BLENDER_EEVEE_NEXT", "cpu"))
        for engine, device in targets:
            try:
                path = out / f"{engine}-{device}.png"
                selected = render(path, device, 32, 1, engine)
                probes.append({"engine": engine, "device": device if engine == "CYCLES" else "engine-managed",
                               "ok": path.is_file(),
                               "selection": {k: v for k, v in selected.items() if k != "inventory"}
                               if engine == "CYCLES" else {"selected": "engine-managed"}})
            except Exception as exc:
                probes.append({"engine": engine, "device": device, "ok": False, "error": str(exc)})
        return {"ok": any(p["ok"] and p["device"] == "cpu" for p in probes),
                **metadata, **devices, "render_probes": probes}
    spec = load_spec(request["spec_path"])
    if action == "build":
        generate(spec)
        validation = validate_scene(spec)
        path = out / "scene.blend"
        bpy.context.preferences.filepaths.save_version = 0
        if bpy.ops.wm.save_as_mainfile(filepath=str(path)) != {"FINISHED"}:
            raise RuntimeError("Failed to save scene.blend")
        return {**metadata, **validation, "scene_file": str(path)}
    if action in ("validate", "preview"):
        bpy.ops.wm.open_mainfile(filepath=request["blend_path"], load_ui=False, use_scripts=False)
        validation = validate_scene(spec)
        if action == "validate":
            return {**metadata, **validation, "reopened": True}
        selected = render(out / "preview.png", request["device"], request["resolution"], request["samples"])
        return {**metadata, **validation, "render": selected, "preview": "preview.png",
                "resolution": request["resolution"], "samples": request["samples"]}
    raise ValueError(f"Unknown worker action: {action}")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    request_path, result_path = map(Path, args)
    try:
        result = execute(json.loads(request_path.read_text(encoding="utf-8")), result_path.parent)
        write(result_path, result)
    except Exception as exc:
        write(result_path, {"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        raise
