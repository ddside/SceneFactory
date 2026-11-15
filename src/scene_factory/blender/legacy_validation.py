"""Frozen Phase 1 validation for reading existing, plan-less validated builds."""
import hashlib
import json
import math

import bpy
from mathutils import Euler, Matrix, Vector

from scene_factory.spec import dimensions
from scene_factory.blender.generators import cuboid_vertices, FACES


def close(actual, expected, label):
    if len(actual) != len(expected) or any(
        not math.isfinite(a) or not math.isclose(a, b, rel_tol=1e-6, abs_tol=2e-5)
        for a, b in zip(actual, expected)
    ):
        raise ValueError(f"{label}: expected {list(expected)}, got {list(actual)}")


def validate_scene(spec):
    scene = bpy.context.scene
    if scene.get("scene_id") != spec["scene_id"] or scene.get("seed") != spec["seed"]:
        raise ValueError("scene metadata: scene_id/seed mismatch")
    if scene.get("schema_version") != 1:
        raise ValueError("scene metadata: schema_version mismatch")
    if scene.unit_settings.system != "METRIC" or scene.unit_settings.scale_length != 1.0:
        raise ValueError("scene units: expected meters")
    meshes = [o for o in scene.objects if o.type == "MESH"]
    expected_ids = {o["stable_id"] for o in spec["objects"]}
    actual_ids = [o.get("stable_id") for o in meshes]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        raise ValueError(f"stable_id mismatch: expected {sorted(expected_ids)}, got {actual_ids}")
    actual = {o["stable_id"]: o for o in meshes}
    records = []
    for obj in spec["objects"]:
        sid = obj["stable_id"]
        mesh_obj = actual[sid]
        if mesh_obj.get("generator") != obj["generator"]:
            raise ValueError(f"{sid}: generator mismatch")
        if mesh_obj.parent or mesh_obj.modifiers or mesh_obj.constraints or mesh_obj.animation_data:
            raise ValueError(f"{sid}: unexpected parent/modifier/constraint/animation")
        expected_vertices = cuboid_vertices(dimensions(obj))
        vertices = [tuple(v.co) for v in mesh_obj.data.vertices]
        faces = [tuple(p.vertices) for p in mesh_obj.data.polygons]
        if len(vertices) != 8 or faces != FACES:
            raise ValueError(f"{sid}: expected cuboid mesh with 8 vertices and 6 quads")
        for i, (v, expected) in enumerate(zip(vertices, expected_vertices)):
            close(v, expected, f"{sid}.vertices[{i}]")
        transform = obj["transform"]
        rotation = [math.radians(a) for a in transform["rotation_degrees"]]
        close(mesh_obj.location, transform["location"], sid + ".location")
        close(mesh_obj.scale, transform["scale"], sid + ".scale")
        expected_matrix = Matrix.LocRotScale(Vector(transform["location"]),
                                            Euler(rotation, "XYZ").to_quaternion(),
                                            Vector(transform["scale"]))
        for row, expected in zip(mesh_obj.matrix_world, expected_matrix):
            close(row, expected, sid + ".matrix_world")
        world = [mesh_obj.matrix_world @ Vector(v) for v in vertices]
        expected_world = [expected_matrix @ Vector(v) for v in expected_vertices]
        bounds = [[min(v[i] for v in world) for i in range(3)],
                  [max(v[i] for v in world) for i in range(3)]]
        expected_bounds = [[min(v[i] for v in expected_world) for i in range(3)],
                           [max(v[i] for v in expected_world) for i in range(3)]]
        for row, expected in zip(bounds, expected_bounds):
            close(row, expected, sid + ".world_bounds")
        if len(mesh_obj.data.materials) != 1 or mesh_obj.data.materials[0] is None:
            raise ValueError(f"{sid}: missing material")
        material = mesh_obj.data.materials[0]
        if not all(math.isfinite(v) for v in material.diffuse_color):
            raise ValueError(f"{sid}: non-finite material")
        close(mesh_obj.dimensions, [dimensions(obj)[i] * transform["scale"][i]
                                   for i in range(3)], sid + ".dimensions")
        records.append({"stable_id": sid, "generator": obj["generator"],
                        "vertices": [[round(v, 6) for v in row] for row in vertices],
                        "faces": faces, "matrix_world": [[round(v, 6) for v in row]
                                                           for row in mesh_obj.matrix_world],
                        "world_bounds": bounds, "dimensions": list(mesh_obj.dimensions)})
    fingerprint_data = [{k: r[k] for k in ("stable_id", "generator", "vertices", "faces", "matrix_world")}
                        for r in records]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
    return {"ok": True, "object_count": len(records), "objects": records,
            "structure_sha256": fingerprint}
