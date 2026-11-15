"""Strict Scene Specification v1, shared with Blender's Python 3.11.

No third-party imports, IO side effects, or application runtime assumptions.
"""
import copy
import json
import math
import re
from pathlib import Path


class SpecError(ValueError):
    pass


# Each cuboid has a bottom-center origin, local X=width/Y=depth/Z=height.
GENERATORS = {
    "ground": {"width": 20.0, "depth": 20.0, "thickness": 0.2},
    "box_building": {"width": 6.0, "depth": 4.0, "height": 3.0},
    "pillar": {"width": 0.4, "depth": 0.4, "height": 3.0},
    "roof": {"width": 7.0, "depth": 5.0, "thickness": 0.25},
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def fail(path, message):
    raise SpecError(f"{path}: {message}")


def fields(value, path, required, optional=()):
    if not isinstance(value, dict):
        fail(path, "expected object")
    for key in required:
        if key not in value:
            fail(f"{path}.{key}", "required field missing")
    for key in value:
        if key not in (*required, *optional):
            fail(f"{path}.{key}", "unknown field")


def number(value, path, lower, upper):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail(path, "expected finite number (booleans are not numbers)")
    if not lower <= value <= upper:
        fail(path, f"expected {lower} <= value <= {upper}")
    return float(value)


def identifier(value, path):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail(path, "expected 1..64 ASCII letters/digits/._-, starting with letter/digit")


def validate_spec(data):
    """Return a normalized copy; reject unknown fields and all unsupported values."""
    fields(data, "$", ("schema_version", "scene_id", "seed", "units", "objects"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        fail("$.schema_version", "only integer version 1 is supported")
    identifier(data["scene_id"], "$.scene_id")
    if type(data["seed"]) is not int or not 0 <= data["seed"] <= 4294967295:
        fail("$.seed", "expected integer in [0, 4294967295]")
    if data["units"] != "m":
        fail("$.units", "only 'm' (meters, Z-up) is supported")
    if not isinstance(data["objects"], list) or not 1 <= len(data["objects"]) <= 1000:
        fail("$.objects", "expected array of 1..1000 objects")
    normalized = copy.deepcopy(data)
    seen = set()
    for i, obj in enumerate(normalized["objects"]):
        path = f"$.objects[{i}]"
        fields(obj, path, ("stable_id", "generator", "transform", "parameters"))
        identifier(obj["stable_id"], path + ".stable_id")
        if obj["stable_id"] in seen:
            fail(path + ".stable_id", "duplicate ID")
        seen.add(obj["stable_id"])
        if not isinstance(obj["generator"], str) or obj["generator"] not in GENERATORS:
            fail(path + ".generator", "unregistered generator")
        fields(obj["transform"], path + ".transform", (), ("location", "rotation_degrees", "scale"))
        for key, default, low, high in (
            ("location", [0, 0, 0], -10000, 10000),
            ("rotation_degrees", [0, 0, 0], -360, 360),
            ("scale", [1, 1, 1], 0.001, 100),
        ):
            values = obj["transform"].get(key, default)
            if not isinstance(values, list) or len(values) != 3:
                fail(path + ".transform." + key, "expected array of exactly 3 numbers")
            obj["transform"][key] = [number(v, f"{path}.transform.{key}[{j}]", low, high)
                                     for j, v in enumerate(values)]
        defaults = GENERATORS[obj["generator"]]
        fields(obj["parameters"], path + ".parameters", (), tuple(defaults))
        obj["parameters"] = {key: number(obj["parameters"].get(key, default),
                                        path + ".parameters." + key, 0.01, 1000)
                             for key, default in defaults.items()}
    normalized["objects"].sort(key=lambda obj: obj["stable_id"])
    return normalized


def dimensions(obj):
    params = obj["parameters"]
    return (params["width"], params["depth"], params.get("height", params.get("thickness")))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f"$.{key}", "duplicate JSON key")
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        raise SpecError(f"{path}: {exc}") from exc


def load_spec(path):
    return validate_spec(read_json(path))


def example_spec(scene_id="example"):
    objects = []
    for stable_id, generator, location in (
        ("ground.main", "ground", [0, 0, -0.2]),
        ("building.main", "box_building", [0, 0, 0]),
        ("pillar.entry", "pillar", [4, -2, 0]),
        ("roof.main", "roof", [0, 0, 3]),
    ):
        objects.append({"stable_id": stable_id, "generator": generator,
                        "transform": {"location": location}, "parameters": {}})
    return validate_spec({"schema_version": 1, "scene_id": scene_id,
                          "seed": 42, "units": "m", "objects": objects})
