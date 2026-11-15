import copy
import math

import pytest

from scene_factory.spec import SpecError, example_spec, load_spec, validate_spec


def change(spec, path, value):
    container = spec
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value


@pytest.mark.parametrize("path,value,field", [
    (["schema_version"], 2, "schema_version"),
    (["schema_version"], True, "schema_version"),
    (["scene_id"], "../escape", "scene_id"),
    (["seed"], -1, "seed"), (["seed"], True, "seed"),
    (["units"], "cm", "units"), (["objects"], [], "objects"),
    (["objects", 0, "generator"], "cave", "generator"),
    (["objects", 0, "generator"], [], "generator"),
    (["objects", 0, "parameters", "width"], 0, "width"),
    (["objects", 0, "parameters", "width"], -1, "width"),
    (["objects", 0, "parameters", "width"], True, "width"),
    (["objects", 0, "parameters", "width"], 10**1000, "width"),
    (["objects", 0, "parameters", "width"], math.inf, "width"),
    (["objects", 0, "parameters", "width"], math.nan, "width"),
    (["objects", 0, "parameters", "typo"], 1, "typo"),
    (["objects", 0, "transform", "location"], [0, 0], "location"),
    (["objects", 0, "transform", "location"], [0, math.nan, 0], "location"),
    (["objects", 0, "transform", "location"], [0, 10001, 0], "location"),
    (["objects", 0, "transform", "rotation_degrees"], [0, 361, 0], "rotation_degrees"),
    (["objects", 0, "transform", "scale"], [1, 0, 1], "scale"),
    (["objects", 0, "transform", "scale"], [1, -1, 1], "scale"),
])
def test_invalid_values(path, value, field):
    spec = example_spec()
    change(spec, path, value)
    with pytest.raises(SpecError, match=field):
        validate_spec(spec)


@pytest.mark.parametrize("field", ["schema_version", "scene_id", "seed", "units", "objects"])
def test_missing_fields(field):
    spec = example_spec()
    del spec[field]
    with pytest.raises(SpecError, match=field):
        validate_spec(spec)


def test_duplicate_id():
    spec = example_spec()
    spec["objects"].append(copy.deepcopy(spec["objects"][0]))
    with pytest.raises(SpecError, match="stable_id.*duplicate"):
        validate_spec(spec)


def test_defaults_order_and_no_mutation():
    raw = example_spec()
    raw["objects"].reverse()
    raw["objects"][0]["transform"] = {}
    raw["objects"][0]["parameters"] = {}
    before = copy.deepcopy(raw)
    result = validate_spec(raw)
    assert raw == before
    assert result["objects"] == sorted(result["objects"], key=lambda o: o["stable_id"])
    roof = next(o for o in result["objects"] if o["generator"] == "roof")
    assert roof["parameters"] == {"width": 7., "depth": 5., "thickness": .25}
    assert roof["transform"]["scale"] == [1, 1, 1]


def test_json_duplicate_and_syntax(tmp_path):
    path = tmp_path / "scene.json"
    for content in ('{"seed":1,"seed":2}', '{bad'):
        path.write_text(content)
        with pytest.raises(SpecError):
            load_spec(path)
