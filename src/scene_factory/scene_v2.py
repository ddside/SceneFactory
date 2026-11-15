"""Strict logical-node specification and explicit, non-destructive v1 migration."""
import copy
from pathlib import Path

from .spec import SpecError, fields, identifier, number, read_json, validate_spec
from .contract_utils import (canonical_digest, check_digest, check_version,
                             normalize_parameters, normalize_transform, topological_order)

MIGRATION_VERSION = "1.0.0"


def migrate_v1(data, source_sha256=None):
    source = validate_spec(data)
    if source["schema_version"] != 1:
        raise SpecError("migration: source must be SceneSpec v1")
    source_sha256 = source_sha256 or canonical_digest(data)
    check_digest(source_sha256, "migration.source_sha256")
    return {"schema_version": 2, "scene_id": source["scene_id"], "seed": source["seed"],
            "units": source["units"], "nodes": [
                {"node_id": obj["stable_id"], "skill": {"skill_id": obj["generator"], "version": "1.0.0"},
                 "parent_id": None, "depends_on": [], "inputs": {},
                 "transform": obj["transform"], "parameters": obj["parameters"],
                 "legacy": {"stable_id": obj["stable_id"], "generator": obj["generator"]}}
                for obj in source["objects"]],
            "migration": {"source_schema_version": 1, "source_sha256": source_sha256,
                          "migration_version": MIGRATION_VERSION}}


def migrate_file(source, destination):
    """Write a distinct new file exclusively; never overwrite source or destination."""
    from .registry import file_hash
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise SpecError("migration destination must differ from source")
    migrated = migrate_v1(read_json(source), file_hash(source))
    import json
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(migrated, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return migrated


def validate_v2(data, registry=None, allow_candidates=()):
    if registry is None:
        from .registry import Registry
        registry = Registry()
    fields(data, "$", ("schema_version", "scene_id", "seed", "units", "nodes"), ("migration",))
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise SpecError("$.schema_version: only integer version 2 supported")
    identifier(data["scene_id"], "$.scene_id")
    if type(data["seed"]) is not int or not 0 <= data["seed"] <= 4294967295:
        raise SpecError("$.seed: expected integer in [0, 4294967295]")
    if data["units"] != "m":
        raise SpecError("$.units: only meters/Z-up supported")
    if not isinstance(data["nodes"], list) or not 1 <= len(data["nodes"]) <= 1000:
        raise SpecError("$.nodes: expected 1..1000 logical nodes")
    result = copy.deepcopy(data)
    if "migration" in result:
        m = result["migration"]
        fields(m, "migration", ("source_schema_version", "source_sha256", "migration_version"))
        if type(m["source_schema_version"]) is not int or m["source_schema_version"] != 1 or m["migration_version"] != MIGRATION_VERSION:
            raise SpecError("migration: unsupported source/migration version")
        check_digest(m["source_sha256"], "migration.source_sha256")
    seen, skills = {}, {}
    for index, node in enumerate(result["nodes"]):
        path = f"$.nodes[{index}]"
        fields(node, path, ("node_id", "skill", "transform", "parameters"),
               ("parent_id", "depends_on", "inputs", "legacy"))
        identifier(node["node_id"], path + ".node_id")
        if node["node_id"] in seen:
            raise SpecError(f"{path}.node_id: duplicate ID")
        fields(node["skill"], path + ".skill", ("skill_id", "version"))
        identifier(node["skill"]["skill_id"], path + ".skill.skill_id")
        check_version(node["skill"]["version"], path + ".skill.version")
        manifest = registry.get(node["skill"]["skill_id"], node["skill"]["version"], allow_candidates)
        node["parameters"] = normalize_parameters(node["parameters"], manifest["parameter_schema"], path + ".parameters")
        node["transform"] = normalize_transform(node["transform"], path + ".transform")
        node.setdefault("parent_id", None)
        node.setdefault("depends_on", [])
        node.setdefault("inputs", {})
        if node["parent_id"] is not None:
            identifier(node["parent_id"], path + ".parent_id")
        if (not isinstance(node["depends_on"], list)
            or not all(isinstance(x, str) for x in node["depends_on"])
            or len(set(node["depends_on"])) != len(node["depends_on"])):
            raise SpecError(f"{path}.depends_on: expected unique node IDs")
        fields(node["inputs"], path + ".inputs", (), tuple(manifest["inputs"]))
        for name, port in manifest["inputs"].items():
            if port["required"] and name not in node["inputs"]:
                raise SpecError(f"{path}.inputs.{name}: required binding missing")
        for name, binding in node["inputs"].items():
            fields(binding, path + ".inputs." + name, ("node_id", "output"))
            identifier(binding["node_id"], path + ".inputs.node_id")
            identifier(binding["output"], path + ".inputs.output")
        if "legacy" in node:
            fields(node["legacy"], path + ".legacy", ("stable_id", "generator"))
            if (node["legacy"]["stable_id"] != node["node_id"]
                or node["legacy"]["generator"] != node["skill"]["skill_id"]
                or node["skill"]["skill_id"] not in ("ground", "box_building", "pillar", "roof")
                or node["skill"]["version"] != "1.0.0"):
                raise SpecError(f"{path}.legacy: invalid v1 identity mapping")
        seen[node["node_id"]] = node
        skills[node["node_id"]] = manifest
    parents, dependencies = {}, {}
    for node_id, node in seen.items():
        parents[node_id] = [] if node["parent_id"] is None else [node["parent_id"]]
        dependencies[node_id] = [*node["depends_on"], *parents[node_id]]
        for name, binding in node["inputs"].items():
            producer = binding["node_id"]
            if producer not in seen:
                raise SpecError(f"{node_id}.inputs.{name}: missing node reference {producer}")
            output = skills[producer]["outputs"].get(binding["output"])
            if output is None or output["type"] != skills[node_id]["inputs"][name]["type"]:
                raise SpecError(f"{node_id}.inputs.{name}: missing output or type mismatch")
            dependencies[node_id].append(producer)
    topological_order(parents, "parent hierarchy")
    topological_order(dependencies, "node dependencies")
    result["nodes"].sort(key=lambda n: n["node_id"])
    return result


def example_v2(scene_id="example"):
    return {"schema_version":2,"scene_id":scene_id,"seed":42,"units":"m","nodes":[
        {"node_id":"ground.main","skill":{"skill_id":"ground","version":"1.0.0"},
         "transform":{"location":[0,0,-.2]},"parameters":{}},
        {"node_id":"building.main","skill":{"skill_id":"building_recipe","version":"1.0.0"},
         "depends_on":["ground.main"],"transform":{"location":[-2,0,0],"rotation_degrees":[0,0,15]},"parameters":{}},
        {"node_id":"column.side","skill":{"skill_id":"cylinder","version":"1.0.0"},
         "parent_id":"building.main","transform":{"location":[4,-2,0]},"parameters":{}}]}
