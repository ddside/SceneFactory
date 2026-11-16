"""Pure logical compilation: data/manifest -> resolved nodes and execution DAG.

No geometry generation, bpy imports, subprocesses or writes.
"""
import copy
import hashlib

from .contract_utils import (canonical_digest, check_digest, evaluate, normalize_parameters, normalize_transform,
                             topological_order, typed_value)
from .scene_v2 import migrate_v1, validate_v2
from .registry import Registry
from .spec import SpecError
from .transforms import identity, multiply, trs

SEED_VERSION = "sha256-scene-seed-node-id-v1"


def node_seed(seed, node_id):
    return hashlib.sha256(f"{seed}:{node_id}".encode()).hexdigest()


def child_id(parent_id, local_key):
    return "n." + canonical_digest([parent_id, local_key])[:40]


def artifact_id(node_id, role):
    return "a." + canonical_digest([node_id, role])[:40]


def compile_scene(source, registry=None, source_sha256=None, runtime_profile=None, allow_candidates=(), resources=None):
    registry = registry or Registry()
    version = source.get("schema_version") if isinstance(source, dict) else None
    if version == 1:
        authored = migrate_v1(source, source_sha256)
    elif version == 2:
        authored = copy.deepcopy(source)
    else:
        raise SpecError("$.schema_version: expected 1 or 2")
    authored = validate_v2(authored, registry, allow_candidates)
    from .resources import validate_bundle
    validate_bundle(authored,resources)
    source_sha256 = source_sha256 or canonical_digest(source)
    expanded, used = {}, {}

    def expand(node, source_id, prefix, lineage, depth=0):
        if depth > 16 or len(expanded) >= 1000:
            raise SpecError("recipe expansion: depth/node budget exceeded")
        node = copy.deepcopy(node)
        nid = node["node_id"]
        if nid in expanded:
            raise SpecError(f"recipe expansion: duplicate node ID {nid}")
        manifest = registry.get(node["skill"]["skill_id"], node["skill"]["version"], allow_candidates)
        for port_name, port in manifest["inputs"].items():
            if port["required"] and port_name not in node["inputs"]:
                raise SpecError(f"{nid}.inputs.{port_name}: required binding missing")
        used[(manifest["skill_id"], manifest["version"])] = registry.pin(manifest)
        for dependency in manifest["dependencies"]:
            pin_dependency(dependency)
        node.update(source_node_id=source_id, role_prefix=prefix, lineage=lineage,
                    kind=manifest["kind"], node_seed=node_seed(authored["seed"], nid))
        expanded[nid] = node
        if manifest["kind"] == "recipe":
            mapping = {c["local_key"]: child_id(nid, c["local_key"]) for c in manifest["recipe"]["nodes"]}
            for child in manifest["recipe"]["nodes"]:
                cm = registry.get(child["skill"]["skill_id"], child["skill"]["version"], allow_candidates)
                parameters = {key: evaluate(value, node["parameters"]) for key, value in child["parameters"].items()}
                transform = {key: evaluate(value, node["parameters"]) for key, value in child["transform"].items()}
                key = child["local_key"]
                expanded_child = {"node_id": mapping[key], "skill": child["skill"],
                    "parent_id": nid, "depends_on": [mapping[x] for x in child["depends_on"]],
                    "inputs": {port: {"node_id": mapping[b["node_id"]], "output": b["output"]}
                               for port, b in child["inputs"].items()},
                    "parameters": normalize_parameters(parameters, cm["parameter_schema"], "recipe parameters"),
                    "transform": normalize_transform(transform, "recipe transform")}
                expand(expanded_child, source_id, prefix + [key], lineage + [nid], depth + 1)

    def pin_dependency(ref):
        key = (ref["skill_id"], ref["version"])
        if key not in used:
            m = registry.get(*key, allow_candidates)
            used[key] = registry.pin(m)
            for dependency in m["dependencies"]:
                pin_dependency(dependency)

    for node in authored["nodes"]:
        expand(node, node["node_id"], [], [])
    edges = {}
    for nid, node in expanded.items():
        edges[nid] = set(node["depends_on"])
        if node["parent_id"]:
            edges[nid].add(node["parent_id"])
        edges[nid].update(port["node_id"] for port in node["inputs"].values())
    order = topological_order(edges, "expanded dependency DAG")
    resolved, expected = {}, []
    for nid in order:
        node = expanded[nid]
        manifest = registry.get(node["skill"]["skill_id"], node["skill"]["version"], allow_candidates)
        effective = copy.deepcopy(node["transform"])
        bindings = {}
        for port_name, binding in node["inputs"].items():
            if port_name not in manifest["inputs"]:
                raise SpecError(f"{nid}.inputs.{port_name}: unknown input")
            producer = resolved[binding["node_id"]]
            output = producer["typed_outputs"].get(binding["output"])
            declared = manifest["inputs"][port_name]
            if output is None or output["type"] != declared["type"]:
                raise SpecError(f"{nid}.inputs.{port_name}: missing output/type mismatch")
            value = typed_value(output["value"], output["type"], f"{nid}.{port_name}")
            if declared["target"] == "elevation":
                effective["location"][2] += value
            bindings[port_name] = {**binding, **output, "target": declared["target"]}
        effective = normalize_transform(effective, nid + ".resolved_transform")
        local = trs(effective)
        world = multiply(resolved[node["parent_id"]]["world_matrix"], local) if node["parent_id"] else local
        outputs = {name: {"type": port["type"], "value": typed_value(evaluate(port["value"], node["parameters"]),
                   port["type"], f"{nid}.outputs.{name}")} for name, port in manifest["outputs"].items()}
        node.update(resolved_transform=effective, local_matrix=local, world_matrix=world,
                    resolved_inputs=bindings, typed_outputs=outputs, dependencies=sorted(edges[nid]))
        node["expected_artifacts"] = []
        declarations=copy.deepcopy(manifest['artifacts'])
        if 'asset_ref' in node:
            key=canonical_digest(node['asset_ref']);record=resources['assets'][key]
            from .format_adapters import FORMATS
            adapter=FORMATS.get(record['format'])
            if adapter is None or record['units']!=adapter['units'] or record['up_axis']!=adapter['up_axis']:
                raise SpecError('No supported import adapter for asset format/units/axis')
            node['asset_key']=key
            for part in record['source_metadata'][adapter['metadata_key']]['parts']:
                declarations.append({'role':part['role'],'type':part['type'],'component':{
                    'parent_role':part['parent_role'],'local_matrix':part['local_matrix']},
                    'asset':{**node['asset_ref'],'source_part':part['source_index']}})
        for declaration in declarations:
            local_role = declaration["role"]
            artifact = {"artifact_id": artifact_id(nid, local_role), "source_node_id": node["source_node_id"],
                        "producer_node_id": nid, "role": ".".join(node["role_prefix"] + [local_role]),
                        "local_role": local_role, "type": declaration["type"], "lineage": node["lineage"],
                        "dependencies": [artifact_id(dep, resolved[dep]["expected_artifacts"][0]["local_role"])
                                         for dep in sorted(edges[nid])]}
            for key in ('component','asset'):
                if key in declaration:artifact[key]=declaration[key]
            node["expected_artifacts"].append(artifact)
            expected.append(artifact)
        resolved[nid] = node
    # Reviewed pure skill contracts own cross-node architectural semantics.
    # Generic compiler/validator never branch on a particular shape.
    import importlib
    for nid in order:
        node = resolved[nid]
        manifest = registry.get(node['skill']['skill_id'], node['skill']['version'], allow_candidates)
        if 'contract' in manifest:
            binding = registry.binding(manifest['contract'])
            getattr(importlib.import_module(binding['module']), binding['function'])(node, resolved)
    if 'appearance' in authored:
        occupied=set();binding_groups={}
        for binding in authored['appearance']['bindings']:
            target=expanded.get(binding['node_id'])
            if target is None or not any(a['local_role']==binding['role'] and a['type']=='Mesh' for a in target['expected_artifacts']):
                raise SpecError('appearance binding references missing node/Mesh role')
            key=(binding['node_id'],binding['role'],canonical_digest(binding.get('region')))
            if key in occupied:raise SpecError('duplicate material binding target/region')
            occupied.add(key)
            binding_groups.setdefault((binding['node_id'],binding['role']),[]).append(binding)
        for bindings in binding_groups.values():
            if len(bindings)>7:raise SpecError('material layer/UV budget exceeded')
            if sum('region' not in b for b in bindings)!=1:raise SpecError('exactly one base material binding required')
            regions=[b['region'] for b in bindings if 'region' in b]
            for i,a in enumerate(regions):
                for b in regions[:i]:
                    if min(a['xmax'],b['xmax'])>max(a['xmin'],b['xmin']) and min(a['ymax'],b['ymax'])>max(a['ymin'],b['ymin']):raise SpecError('overlapping material regions')
    interior_report = None
    if "interior" in authored:
        from .interior_contracts import check
        for node in resolved.values():
            if "asset_ref" in node:
                node["interior_asset_bounds"] = resources["assets"][node["asset_key"]]["bounding_box"]
        interior_report = check(authored["interior"], resolved)
    runtime = {"blender_series": "4.5", "worker_python_series": "3.11", **(runtime_profile or {})}
    if (set(runtime) - {"blender_series","worker_python_series","implementation_sha256","application_python","os","architecture"}
        or any(not isinstance(v,str) or not v for v in runtime.values())):
        raise SpecError("runtime_profile: unknown fields or invalid string values")
    if runtime["blender_series"] != "4.5" or runtime["worker_python_series"] != "3.11":
        raise SpecError("runtime_profile: requires Blender 4.5 / Python 3.11")
    # Aggregate runtime hash is provenance, not an all-or-nothing cache key.
    # Revalidation preserves recorded provenance, then verifies exact skill pins
    # and recomputed plan values. Actual executing runtime is reported separately.
    runtime.setdefault("implementation_sha256", registry.runtime_digest())
    check_digest(runtime["implementation_sha256"],"runtime_profile.implementation_sha256")
    lock = {"schema_version": 1, "skills": [used[key] for key in sorted(used)]}
    resolved_scene = {"schema_version": 1, "authoring_spec": authored,
                      "nodes": [resolved[key] for key in sorted(resolved)]}
    plan = {"schema_version": 1, "scene_id": authored["scene_id"], "seed": authored["seed"], "units": "m",
            "source_schema_version": version, "source_sha256": source_sha256,
            "migration": authored.get("migration"), "seed_derivation_version": SEED_VERSION,
            "compiler_version":"1.0.0", "arithmetic_version":"fsum-trs-round12-v1",
            "skill_manifest_schema_version": 1, "runtime_profile": runtime, "skills_lock": lock,
            "resolved_scene_digest": canonical_digest(resolved_scene),
            "execution_order": order, "dependency_dag": {k: sorted(edges[k]) for k in sorted(edges)},
            "nodes": [resolved[k] for k in sorted(resolved)], "expected_artifacts": sorted(expected, key=lambda a: a["artifact_id"]),
            "validation_candidates": sorted(set(allow_candidates))}
    if resources is not None:
        plan['resources']=copy.deepcopy(resources)
        plan['appearance']=copy.deepcopy(authored.get('appearance'))
    if interior_report is not None:
        plan["interior"] = copy.deepcopy(authored["interior"])
        plan["interior_metadata"] = interior_report
    plan["plan_digest"] = canonical_digest(plan)
    return {"resolved_scene": resolved_scene, "build_plan": plan, "skills_lock": lock}


def verify_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise SpecError("BuildPlan.schema_version: expected 1")
    actual = canonical_digest({k: v for k, v in plan.items() if k != "plan_digest"})
    if actual != plan.get("plan_digest"):
        raise SpecError("BuildPlan.plan_digest: digest mismatch")
    return plan
