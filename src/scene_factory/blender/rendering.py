"""Explicit Cycles backend selection; no hidden fallback on render failure."""
import math

import bpy
from mathutils import Vector


def inventory():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    devices = [{"backend": "cpu", "name": "CPU", "type": "CPU"}]
    diagnostics = {}
    for backend in ("METAL", "OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            devices.extend({"backend": backend.lower(), "name": d.name, "type": d.type}
                           for d in prefs.devices if d.type == backend)
        except (TypeError, ValueError, RuntimeError) as exc:
            diagnostics[backend.lower()] = str(exc)
    return {"devices": devices, "backend_diagnostics": diagnostics,
            "evidence": "Blender device enumeration; rendering requires a successful render probe"}


def select_device(requested):
    detected = inventory()
    choices = {d["backend"] for d in detected["devices"]}
    selected = requested
    if requested == "auto":
        selected = next((d for d in ("metal", "optix", "cuda") if d in choices), "cpu")
    if selected not in choices:
        raise ValueError(f"device '{requested}' unavailable in Blender; detected {sorted(choices)}")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    if selected == "cpu":
        scene.cycles.device = "CPU"
    else:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = selected.upper()
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == selected.upper()
        scene.cycles.device = "GPU"
    return {"requested": requested, "selected": selected, "inventory": detected,
            "policy": "auto selects first enumerated backend; render failure never falls back"}


def setup_camera_lights(direction=None):
    scene = bpy.context.scene
    corners = [o.matrix_world @ Vector(v) for o in scene.objects if o.type == "MESH"
               for v in o.bound_box]
    low = Vector([min(v[i] for v in corners) for i in range(3)])
    high = Vector([max(v[i] for v in corners) for i in range(3)])
    center = (low + high) / 2
    radius = max((high - low).length, 1.0)
    data = bpy.data.cameras.new("preview.camera")
    camera = bpy.data.objects.new("preview.camera", data)
    scene.collection.objects.link(camera)
    direction=direction or (1,-1.4,1.1)
    if len(direction)!=3 or not all(type(v) in (int,float) and math.isfinite(v) for v in direction) or Vector(direction).length<.001:
        raise ValueError('preview view_direction must be a finite nonzero vector')
    camera.location = center + Vector(direction).normalized() * radius * 2
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    data.type = "ORTHO"
    rotation = camera.rotation_euler.to_matrix().transposed()
    projected = [rotation @ (v - center) for v in corners]
    span = [max(v[i] for v in projected) - min(v[i] for v in projected) for i in (0, 1)]
    data.ortho_scale = max(*span, 1.0) * 1.15
    data.clip_end = radius * 10 + 100
    scene.camera = camera
    sun_data = bpy.data.lights.new("preview.sun", "SUN")
    sun_data.energy = 3.0
    sun_data.angle = math.radians(10)
    sun = bpy.data.objects.new("preview.sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(25), math.radians(-25), math.radians(-30))
    if scene.world is None:
        scene.world = bpy.data.worlds.new("preview.world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.25, 0.3, 0.4, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5


def render(path, device="cpu", resolution=256, samples=8, engine="CYCLES",view_direction=None):
    selected = select_device(device)
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.seed = int(scene.get("seed", 0)) % 2147483647
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    setup_camera_lights(view_direction)
    if bpy.ops.render.render(write_still=True) != {"FINISHED"}:
        raise RuntimeError("Render did not finish")
    return selected
