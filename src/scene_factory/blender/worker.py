"""JSON worker entrypoint; execute exclusively with Blender CLI."""
import json
from pathlib import Path
import sys
import traceback
import time
import resource

# Blender doesn't inherit application site-packages. Only import this package's
# source from its own location (also works in an installed wheel).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bpy

from scene_factory.spec import load_spec, example_spec, read_json
from scene_factory.registry import Registry, file_hash
from scene_factory.compiler import compile_scene, verify_plan
from scene_factory.blender.generators import generate
from scene_factory.blender.legacy_validation import validate_scene as validate_legacy_scene
from scene_factory.blender.validation import validate_scene
from scene_factory.blender.interior import validate as validate_interior
from scene_factory.blender.engine import generate_plan
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
    # Legacy callers can validate a new build using its adjacent saved plan.
    if "plan_path" not in request and action in ("validate", "preview"):
        adjacent = Path(request["spec_path"]).parent / "plan.json"
        if adjacent.is_file():
            request = {**request,"plan_path":str(adjacent),"plan_digest":read_json(adjacent)["plan_digest"]}
    plan, registry = None, None
    if "plan_path" in request:
        plan = verify_plan(read_json(request["plan_path"]))
        if request.get("plan_digest") != plan["plan_digest"]:
            raise ValueError("worker request / BuildPlan digest mismatch")
        if plan["validation_candidates"] and request.get("skill_validation") is not True:
            raise ValueError("candidate execution only allowed in explicit skill validation runs")
        registry = Registry()
        compiled = compile_scene(read_json(request["spec_path"]), registry, file_hash(request["spec_path"]),
                                 plan["runtime_profile"], plan["validation_candidates"],resources=plan.get("resources"))
        if compiled["build_plan"] != plan:
            raise ValueError("BuildPlan differs from current specification/skill pins/runtime contracts")
        metadata["plan_digest"] = plan["plan_digest"]
        metadata["runtime_implementation_sha256"] = registry.runtime_digest()
        metadata["runtime_code_matches"] = metadata["runtime_implementation_sha256"] == plan["runtime_profile"]["implementation_sha256"]
    resource_root=Path(request['plan_path']).parent if plan is not None else None
    if plan is not None and 'resources' in plan:
        from scene_factory.resources import verify_resources
        verify_resources(resource_root,plan['resources'])
    spec = load_spec(request["spec_path"]) if plan is None else None
    if spec is not None and spec["schema_version"] != 1:
        raise ValueError("SceneSpec v2 requires a compiled BuildPlan")
    if action == "build":
        if plan is not None:
            if 'effects' in plan:
                from scene_factory.blender.effect_runtime import build
                validation=build(plan,registry,resource_root,out,request.get('reuse_effect_base'))
            elif 'damage' in plan:
                from scene_factory.blender.damage_runtime import build
                validation=build(plan,registry,resource_root)
            else:
                generate_plan(plan, registry,resource_root)
            if 'damage' not in plan and 'effects' not in plan and plan.get('appearance'):
                from scene_factory.blender.appearance import apply
                apply(plan,resource_root)
            if 'damage' not in plan and 'effects' not in plan:validation = validate_scene(plan, registry,domain_validators=(validate_interior,) if "interior" in plan else (),resource_root=resource_root)
        else:
            generate(spec)
            validation = validate_legacy_scene(spec)
        path = out / "scene.blend"
        bpy.context.preferences.filepaths.save_version = 0
        if bpy.ops.wm.save_as_mainfile(filepath=str(path)) != {"FINISHED"}:
            raise RuntimeError("Failed to save scene.blend")
        return {**metadata, **validation, "scene_file": str(path)}
    if action in ("validate", "preview"):
        bpy.ops.wm.open_mainfile(filepath=request["blend_path"], load_ui=False, use_scripts=False)
        if plan is not None and 'effects' in plan:
            from scene_factory.blender.effect_runtime import validate_saved
            validation=validate_saved(plan,registry,resource_root,cache=request.get('effect_base_cache'))
        elif plan is not None and 'damage' in plan:
            from scene_factory.blender.damage_runtime import validate_saved
            validation=validate_saved(plan,registry,resource_root)
        else:validation = validate_scene(plan, registry,domain_validators=(validate_interior,) if "interior" in plan else (),resource_root=resource_root) if plan is not None else validate_legacy_scene(spec)
        if action == "validate":
            return {**metadata, **validation, "reopened": True}
        selected = render(out / "preview.png", request["device"], request["resolution"], request["samples"],
                          view_direction=request.get('view_direction'),hide_groups=request.get('hide_groups',[]),denoise=request.get('denoise',False),preview_lighting=request.get('preview_lighting'))
        return {**metadata, **validation, "render": selected, "preview": "preview.png",
                "resolution": request["resolution"], "samples": request["samples"]}
    raise ValueError(f"Unknown worker action: {action}")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    request_path, result_path = map(Path, args)
    request = {}
    try:
        loaded = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(loaded,dict):
            raise ValueError("worker request must be a JSON object")
        request = loaded
        if type(request.get("protocol_version",1)) is not int or request.get("protocol_version", 1) not in (1, 2):
            raise ValueError("Unsupported worker protocol_version")
        if request.get("protocol_version") == 2 and not isinstance(request.get("attempt_id"), str):
            raise ValueError("protocol 2 requires attempt_id")
        started=time.monotonic()
        result = execute(request, result_path.parent)
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result['performance']={'worker_seconds':round(time.monotonic()-started,4),
            'peak_rss_bytes':int(rss if sys.platform=='darwin' else rss*1024)}
        if action_plan:=request.get('plan_path'):
            metrics=read_json(action_plan)
            if metrics.get('resources'):
                result['performance'].update(material_build_seconds=bpy.context.scene.get('material_build_seconds',0),
                    asset_import_seconds=sum(float(o.get('asset_import_seconds',0)) for o in bpy.context.scene.objects),
                    mesh_count=sum(o.type=='MESH' for o in bpy.context.scene.objects),
                    unique_mesh_count=len({o.data.name for o in bpy.context.scene.objects if o.type=='MESH'}),
                    vertex_count=sum(len(o.data.vertices) for o in bpy.context.scene.objects if o.type=='MESH'),
                    face_count=sum(len(o.data.polygons) for o in bpy.context.scene.objects if o.type=='MESH'),
                    furniture_count=len(metrics.get('interior',{}).get('items',[])),
                    material_count=len({m.name for o in bpy.context.scene.objects if o.type=='MESH' for m in o.data.materials if m}),
                    texture_count=len({n.image.name for o in bpy.context.scene.objects if o.type=='MESH' for m in o.data.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}))
        result.update(protocol_version=request.get("protocol_version", 1), attempt_id=request.get("attempt_id"))
        write(result_path, result)
    except Exception as exc:
        write(result_path, {"ok": False, "protocol_version": request.get("protocol_version", 1),
                           "attempt_id": request.get("attempt_id"), "plan_digest": request.get("plan_digest"),
                           "action": request.get("action"), "error_type": type(exc).__name__,
                           "error": str(exc), "traceback": traceback.format_exc()})
        raise
