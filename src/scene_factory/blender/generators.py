"""Deterministic Phase 1 cuboid generators, Blender Python only."""
import hashlib
import random

import bpy

from scene_factory.spec import dimensions


def cuboid_vertices(size):
    x, y, z = size
    return [(-x/2, -y/2, 0), (-x/2, -y/2, z), (-x/2, y/2, 0), (-x/2, y/2, z),
            (x/2, -y/2, 0), (x/2, -y/2, z), (x/2, y/2, 0), (x/2, y/2, z)]


FACES = [(0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1),
         (2, 3, 7, 6), (0, 1, 3, 2), (4, 6, 7, 5)]
PALETTE = {"ground": (0.22, 0.27, 0.21), "box_building": (0.62, 0.56, 0.44),
           "pillar": (0.5, 0.53, 0.56), "roof": (0.25, 0.31, 0.37)}


def make_cuboid(obj, seed, node_seed=None):
    mesh = bpy.data.meshes.new(obj["stable_id"] + ".mesh")
    mesh.from_pydata(cuboid_vertices(dimensions(obj)), [], FACES)
    mesh.update()
    result = bpy.data.objects.new(obj["stable_id"], mesh)
    bpy.context.scene.collection.objects.link(result)
    result["stable_id"] = obj["stable_id"]
    result["generator"] = obj["generator"]
    result.location = obj["transform"]["location"]
    from math import radians
    result.rotation_euler = [radians(v) for v in obj["transform"]["rotation_degrees"]]
    result.scale = obj["transform"]["scale"]
    # Independent deterministic stream per ID; object insertion doesn't recolor others.
    seed_bytes = bytes.fromhex(node_seed) if node_seed is not None else hashlib.sha256(f"{seed}:{obj['stable_id']}".encode()).digest()
    rng = random.Random(int.from_bytes(seed_bytes, "big"))
    factor = rng.uniform(0.9, 1.1)
    color = tuple(v * factor for v in PALETTE[obj["generator"]]) + (1.0,)
    material = bpy.data.materials.new(obj["stable_id"] + ".material")
    material.use_nodes = True
    material.diffuse_color = color
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 0.8
    mesh.materials.append(material)
    return result


# Explicit registry: future generators may have different geometry implementations.
GENERATORS = {name: make_cuboid for name in PALETTE}


def generate(spec):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene["scene_id"] = spec["scene_id"]
    scene["seed"] = spec["seed"]
    scene["schema_version"] = spec["schema_version"]
    for obj in spec["objects"]:
        GENERATORS[obj["generator"]](obj, spec["seed"])
    bpy.context.view_layer.update()
