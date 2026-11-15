import copy
import json

import pytest

from scene_factory.compiler import compile_scene, child_id, node_seed, verify_plan
from scene_factory.contract_utils import canonical_digest
from scene_factory.registry import Registry
from scene_factory.scene_v2 import example_v2, migrate_file, migrate_v1, validate_v2
from scene_factory.spec import SpecError, example_spec


def compile_candidate(source, registry=None):
    registry = registry or Registry()
    return compile_scene(source, registry, allow_candidates=[key[0] for key in registry.manifests])


def simple():
    return {"schema_version":2,"scene_id":"test","seed":42,"units":"m","nodes":[
        {"node_id":"body","skill":{"skill_id":"box_building","version":"1.0.0"},"transform":{},"parameters":{}},
        {"node_id":"roof","skill":{"skill_id":"roof","version":"1.0.0"},"transform":{},"parameters":{},
         "depends_on":["body"],"inputs":{"elevation":{"node_id":"body","output":"height"}}}]}


def test_typed_roof_follows_height_and_topological_order():
    source = simple()
    source["nodes"][0]["parameters"]["height"] = 5
    result = compile_candidate(source)
    plan = result["build_plan"]
    assert plan["execution_order"].index("body") < plan["execution_order"].index("roof")
    roof = next(n for n in plan["nodes"] if n["node_id"] == "roof")
    assert roof["transform"]["location"] == [0,0,0]
    assert roof["resolved_transform"]["location"] == [0,0,5]
    assert roof["resolved_inputs"]["elevation"]["type"] == "Length"
    assert verify_plan(plan) is plan


@pytest.mark.parametrize("case", ["unknown_root","unknown_node","duplicate","missing_input_node","missing_output", "type_mismatch",
    "bad_parent","parent_cycle","dependency_cycle","combined_cycle","bad_version","negative_dimension", "nan", "unknown_parameter",
    "unknown_skill","duplicate_dependency","unsupported_state","unregistered_input"])
def test_invalid_v2(case):
    source = simple()
    a,b = source["nodes"]
    if case == "unknown_root": source["unexpected"] = 1
    elif case == "unknown_node": a["extra"] = 1
    elif case == "duplicate": b["node_id"] = a["node_id"]
    elif case == "missing_input_node": b["inputs"]["elevation"]["node_id"] = "missing"
    elif case == "missing_output": b["inputs"]["elevation"]["output"] = "missing"
    elif case == "type_mismatch": b["inputs"]["elevation"]["output"] = "dimensions"
    elif case == "bad_parent": a["parent_id"] = "missing"
    elif case == "parent_cycle": a["parent_id"],b["parent_id"] = "roof","body"
    elif case == "dependency_cycle": a["depends_on"] = ["roof"]
    elif case == "combined_cycle": a["parent_id"] = "roof"
    elif case == "bad_version": a["skill"]["version"] = "99.0.0"
    elif case == "negative_dimension": a["parameters"]["height"] = -1
    elif case == "nan": a["transform"]["location"] = [0,float('nan'),0]
    elif case == "unknown_parameter": a["parameters"]["room_count"] = 3
    elif case == "unknown_skill": a["skill"]["skill_id"] = "unknown"
    elif case == "duplicate_dependency": b["depends_on"] = ["body","body"]
    elif case == "unsupported_state": a["state"] = {"damage":1}
    elif case == "unregistered_input": a["inputs"] = {"bad":{"node_id":"roof","output":"height"}}
    with pytest.raises(SpecError):
        compile_candidate(source)


def test_parent_world_and_dependency_are_distinct():
    source = simple()
    body,roof = source["nodes"]
    body["transform"] = {"location":[10,0,0],"rotation_degrees":[0,0,90],"scale":[2,1,1]}
    roof.update(parent_id="body",inputs={},transform={"location":[1,0,0]})
    plan = compile_candidate(source)["build_plan"]
    roof = next(n for n in plan["nodes"] if n["node_id"] == "roof")
    assert roof["local_matrix"][0][3] == 1
    assert roof["world_matrix"][0][3] == pytest.approx(10)
    assert roof["world_matrix"][1][3] == pytest.approx(2)
    source["nodes"][1]["parent_id"] = None
    plan = compile_candidate(source)["build_plan"]
    roof = next(n for n in plan["nodes"] if n["node_id"] == "roof")
    assert roof["world_matrix"][0][3] == 1  # depends_on alone adds no spatial relationship.


def test_recipe_expansion_stable_ids_and_seeds():
    source = example_v2()
    before = copy.deepcopy(source)
    first = compile_candidate(source)["build_plan"]
    assert source == before
    assert len(first["nodes"]) == 7 and len(first["expected_artifacts"]) == 7
    recipe_id = "building.main"
    assert child_id(recipe_id,"roof") in first["execution_order"]
    assert first["execution_order"].index(child_id(recipe_id,"wall")) < first["execution_order"].index(child_id(recipe_id,"roof"))
    assert len([a for a in first["expected_artifacts"] if a["source_node_id"] == recipe_id]) == 5
    source["nodes"].reverse()
    reordered = compile_candidate(source)["build_plan"]
    assert reordered["nodes"] == first["nodes"] and reordered["execution_order"] == first["execution_order"]
    # Source provenance digest intentionally records a changed source file/order.
    assert compile_candidate(source)["build_plan"]["plan_digest"] == reordered["plan_digest"]
    source["nodes"].append({"node_id":"unrelated","skill":{"skill_id":"pillar","version":"1.0.0"},"transform":{},"parameters":{}})
    second = compile_candidate(source)["build_plan"]
    original = {n["node_id"]:n["node_seed"] for n in first["nodes"]}
    assert all(n["node_seed"] == original[n["node_id"]] for n in second["nodes"] if n["node_id"] in original)
    assert first["plan_digest"] != second["plan_digest"]
    assert node_seed(42,"same") == node_seed(42,"same") != node_seed(43,"same")


def test_plan_digest_detects_tampering():
    plan = compile_candidate(simple())["build_plan"]
    plan["nodes"][0]["parameters"]["height"] += 1
    with pytest.raises(SpecError,match="digest"):
        verify_plan(plan)


def test_v1_explicit_migration_preserves_semantics(tmp_path):
    source = example_spec()
    original = copy.deepcopy(source)
    source_path, dest = tmp_path/"source.json",tmp_path/"v2.json"
    source_path.write_text(json.dumps(source))
    raw = source_path.read_bytes()
    migrated = migrate_file(source_path,dest)
    assert source_path.read_bytes() == raw
    assert migrated["migration"]["source_sha256"] != canonical_digest(source)  # original bytes, not canonical JSON.
    assert source == original
    for obj,node in zip(source["objects"],migrated["nodes"]):
        assert node["node_id"] == obj["stable_id"] and node["parameters"] == obj["parameters"]
        assert node["transform"] == obj["transform"] and node["skill"]["skill_id"] == obj["generator"]
    a,b = compile_candidate(source)["build_plan"],compile_candidate(migrated)["build_plan"]
    assert [(n["node_id"],n["node_seed"],n["world_matrix"],n["parameters"]) for n in a["nodes"]] == [
        (n["node_id"],n["node_seed"],n["world_matrix"],n["parameters"]) for n in b["nodes"]]
    with pytest.raises(FileExistsError): migrate_file(source_path,dest)
    with pytest.raises(SpecError): migrate_file(source_path,source_path)


def test_new_leaf_and_recipe_are_data_registered():
    r = Registry()
    leaf = copy.deepcopy(r.manifests[("cylinder","1.0.0")])
    leaf.update(skill_id="new_leaf",validation_status="candidate")
    leaf.pop("validation_evidence",None)
    r.check_manifest(leaf)
    r.manifests[("new_leaf","1.0.0")] = leaf
    recipe = copy.deepcopy(r.manifests[("building_recipe","1.0.0")])
    recipe.update(skill_id="new_recipe",validation_status="candidate")
    recipe.pop("validation_evidence",None)
    r.check_manifest(recipe)
    r.manifests[("new_recipe","1.0.0")] = recipe
    source = example_v2()
    source["nodes"][1]["skill"]["skill_id"] = "new_recipe"
    source["nodes"][2]["skill"]["skill_id"] = "new_leaf"
    plan = compile_candidate(source,r)["build_plan"]
    assert {n["skill"]["skill_id"] for n in plan["nodes"]} >= {"new_leaf","new_recipe"}
