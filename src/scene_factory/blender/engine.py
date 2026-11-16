"""Plan execution and dispatch of reviewed skill entry points."""
import importlib
import json

import bpy
from mathutils import Matrix


def callback(registry, key):
    binding = registry.binding(key)
    module = importlib.import_module(binding["module"])
    return getattr(module, binding["function"])


def generate_plan(plan, registry,resource_root=None):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene["schema_version"] = 2
    scene["source_schema_version"] = plan["source_schema_version"]
    scene["scene_id"] = plan["scene_id"]
    scene["seed"] = plan["seed"]
    scene["plan_digest"] = plan["plan_digest"]
    nodes = {n["node_id"]: n for n in plan["nodes"]}
    primary_objects = {}
    asset_prototypes = {}
    for nid in plan["execution_order"]:
        node = nodes[nid]
        manifest = registry.get(node["skill"]["skill_id"], node["skill"]["version"], plan["validation_candidates"])
        context = {"scene_seed": plan["seed"], "plan": plan, "primary_objects": primary_objects,"resource_root":resource_root,"asset_prototypes":asset_prototypes}
        objects = callback(registry, manifest["implementation"])(node, context)
        declarations = {a["local_role"]: a for a in node["expected_artifacts"]}
        if not isinstance(objects, dict) or set(objects) != set(declarations):
            raise ValueError(f"{nid}: implementation returned missing/unexpected roles")
        for role, obj in objects.items():
            a = declarations[role]
            obj.name = a["artifact_id"]
            obj["artifact_id"] = a["artifact_id"]
            obj["stable_id"] = nid
            obj["source_node_id"] = a["source_node_id"]
            obj["producer_node_id"] = nid
            obj["role"] = a["role"]
            obj["local_role"] = role
            obj["generator"] = node["skill"]["skill_id"]
            obj["node_seed"] = node["node_seed"]
            obj["logical_parent"] = node["parent_id"] or ""
            obj["typed_inputs"] = json.dumps(node["resolved_inputs"], sort_keys=True)
            if 'component' in a:
                obj.parent=objects[a['component']['parent_role']]
                obj.matrix_parent_inverse=Matrix.Identity(4)
                obj.matrix_basis=Matrix(a['component']['local_matrix'])
                continue
            if node["parent_id"]:
                obj.parent = primary_objects[node["parent_id"]]
                obj.matrix_parent_inverse = Matrix.Identity(4)
            t = node["resolved_transform"]
            from math import radians
            obj.location = t["location"]
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = [radians(x) for x in t["rotation_degrees"]]
            obj.scale = t["scale"]
        primary_objects[nid] = objects[node["expected_artifacts"][0]["local_role"]]
    bpy.context.view_layer.update()
