"""Shape-independent common checks and skill/domain validator dispatch."""
import hashlib
import json
import math
import struct

import bpy
from mathutils import Vector

from scene_factory.artifacts import check_manifest, structure_digest
from scene_factory.contract_utils import canonical_digest
from scene_factory.blender.engine import callback
from scene_factory.blender.skills.common import close


def rounded_matrix(matrix):
    return [[round(float(v), 6) for v in row] for row in matrix]


def geometry_digest(mesh):
    """Streaming digest: no full vertex arrays in JSON inventories."""
    sha = hashlib.sha256()
    sha.update(struct.pack("<QQ", len(mesh.vertices), len(mesh.polygons)))
    for vertex in mesh.vertices:
        values = [round(float(v), 6) for v in vertex.co]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("mesh has non-finite vertex coordinates")
        sha.update(struct.pack("<ddd", *values))
    for face in mesh.polygons:
        sha.update(struct.pack("<Q", len(face.vertices)))
        for index in face.vertices:
            sha.update(struct.pack("<Q", index))
    return sha.hexdigest()


def validate_scene(plan, registry, domain_validators=()):
    scene = bpy.context.scene
    for key, expected in (("scene_id", plan["scene_id"]), ("seed", plan["seed"]),
                          ("schema_version", 2), ("source_schema_version", plan["source_schema_version"]),
                          ("plan_digest", plan["plan_digest"])):
        if scene.get(key) != expected:
            raise ValueError(f"scene.{key}: metadata mismatch")
    if scene.unit_settings.system != "METRIC" or scene.unit_settings.scale_length != 1.0:
        raise ValueError("scene units: expected meters / Z-up")
    actual = {}
    for obj in scene.objects:
        aid = obj.get("artifact_id")
        if not aid or aid in actual:
            raise ValueError("scene contains duplicate or unexpected untracked artifacts")
        actual[aid] = obj
    expected = {a["artifact_id"]: a for a in plan["expected_artifacts"]}
    if set(expected) != set(actual):
        raise ValueError("scene contains missing/unexpected artifacts")
    nodes = {n["node_id"]: n for n in plan["nodes"]}
    primary = {nid: actual[n["expected_artifacts"][0]["artifact_id"]] for nid, n in nodes.items()}
    inventory, legacy_objects = [], []
    for aid, declaration in sorted(expected.items()):
        obj = actual[aid]
        node = nodes[declaration["producer_node_id"]]
        for key, value in (("stable_id", node["node_id"]), ("source_node_id", declaration["source_node_id"]),
                           ("producer_node_id", node["node_id"]), ("role", declaration["role"]),
                           ("local_role", declaration["local_role"]), ("generator", node["skill"]["skill_id"]),
                           ("node_seed", node["node_seed"]), ("logical_parent", node["parent_id"] or "")):
            if obj.get(key) != value:
                raise ValueError(f"{aid}.{key}: metadata mismatch")
        if obj.get("typed_inputs") != json.dumps(node["resolved_inputs"], sort_keys=True):
            raise ValueError(f"{aid}: typed input binding mismatch")
        if obj.parent != (primary[node["parent_id"]] if node["parent_id"] else None):
            raise ValueError(f"{aid}: spatial parent mismatch")
        if obj.modifiers or obj.constraints or obj.animation_data:
            raise ValueError(f"{aid}: undeclared modifiers/constraints/animation unsupported in Phase 2A")
        for row, exp in zip(obj.matrix_basis, node["local_matrix"]):
            close(row, exp, aid + ".local_matrix")
        for row, exp in zip(obj.matrix_world, node["world_matrix"]):
            close(row, exp, aid + ".world_matrix")
        for i, row in enumerate(obj.matrix_parent_inverse):
            close(row, [float(i == j) for j in range(4)], aid + ".matrix_parent_inverse")
        if declaration["type"] == "Mesh":
            if obj.type != "MESH" or not obj.data.vertices or not obj.data.polygons:
                raise ValueError(f"{aid}: required mesh missing")
            digest = geometry_digest(obj.data)
            low, high = [math.inf]*3, [-math.inf]*3
            for vertex in obj.data.vertices:
                point = obj.matrix_world @ vertex.co
                if not all(math.isfinite(v) for v in point):
                    raise ValueError(f"{aid}: non-finite world coordinates")
                for i in range(3):
                    low[i], high[i] = min(low[i], point[i]), max(high[i], point[i])
            vertex_count, face_count = len(obj.data.vertices), len(obj.data.polygons)
            legacy_objects.append({"artifact_id":aid, "stable_id": node["node_id"], "generator": node["skill"]["skill_id"],
                                   "dimensions": list(obj.dimensions), "world_bounds": [low, high]})
        else:
            if obj.type != "EMPTY":
                raise ValueError(f"{aid}: only Empty Object artifacts supported")
            digest = None
            vertex_count = face_count = 0
            point = obj.matrix_world @ Vector((0,0,0))
            low = high = list(point)
        inventory.append({**declaration, "reference": {"object": obj.name,
                          "mesh": obj.data.name if obj.type == "MESH" else None},
                          "geometry_digest": digest, "vertex_count": vertex_count, "face_count": face_count,
                          "bounds": [[round(v,6) for v in low], [round(v,6) for v in high]],
                          "local_matrix": rounded_matrix(obj.matrix_basis), "world_matrix": rounded_matrix(obj.matrix_world)})
    context = {"plan": plan, "primary_objects": primary}
    for node in plan["nodes"]:
        manifest = registry.get(node["skill"]["skill_id"], node["skill"]["version"], plan["validation_candidates"])
        objects = {a["local_role"]: actual[a["artifact_id"]] for a in node["expected_artifacts"]}
        callback(registry, manifest["validator"])(node, objects, context)
    domain_results = [validator(plan, context) for validator in domain_validators]
    mapping = {}
    for a in inventory:
        mapping.setdefault(a["source_node_id"], []).append(a["artifact_id"])
    manifest = check_manifest({"schema_version": 1, "plan_digest": plan["plan_digest"], "artifact_count": len(inventory),
                               "artifacts": inventory, "node_artifacts": {k: sorted(v) for k,v in mapping.items()}},
                              plan["expected_artifacts"])
    return {"ok": True, "object_count": len(legacy_objects), "objects": sorted(legacy_objects, key=lambda o: o["stable_id"]),
            "artifact_count": len(inventory), "artifact_manifest": manifest, "domain_results": domain_results,
            "structure_sha256": structure_digest(manifest)}
