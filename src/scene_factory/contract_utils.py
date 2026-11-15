"""Small, Python 3.11-compatible data contracts (no Blender imports)."""
import hashlib
import json
import math
import re

from .spec import SpecError, fields, number

VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
TYPES = ("Length", "Dimensions", "WallRef", "OpeningRef", "SpaceRef")


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def check_digest(value, path):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise SpecError(f"{path}: expected SHA-256 digest")


def check_version(value, path):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise SpecError(f"{path}: expected exact major.minor.patch version")


def normalize_transform(value, path):
    fields(value, path, (), ("location", "rotation_degrees", "scale"))
    result = {}
    for key, default, low, high in (
        ("location", [0, 0, 0], -10000, 10000),
        ("rotation_degrees", [0, 0, 0], -360, 360),
        ("scale", [1, 1, 1], .001, 100),
    ):
        values = value.get(key, default)
        if not isinstance(values, list) or len(values) != 3:
            raise SpecError(f"{path}.{key}: expected 3 numbers")
        result[key] = [number(v, f"{path}.{key}[{i}]", low, high) for i, v in enumerate(values)]
    return result


def parameter_schema(schema, path):
    if not isinstance(schema, dict):
        raise SpecError(f"{path}: expected parameter schema object")
    for key, rule in schema.items():
        if not isinstance(key, str) or not key.isidentifier():
            raise SpecError(f"{path}: invalid parameter name")
        fields(rule, f"{path}.{key}", ("type", "default", "minimum", "maximum"), ("multiple_of",))
        if rule["type"] not in ("number", "integer"):
            raise SpecError(f"{path}.{key}.type: only number/integer supported")
        number(rule["minimum"], path, -1e6, 1e6)
        number(rule["maximum"], path, rule["minimum"], 1e6)
        if "multiple_of" in rule:
            number(rule["multiple_of"], path, .000001, 1e6)
    normalize_parameters({}, schema, path)


def normalize_parameters(value, schema, path):
    fields(value, path, (), tuple(schema))
    result = {}
    for key, rule in schema.items():
        v = value.get(key, rule["default"])
        n = number(v, f"{path}.{key}", rule["minimum"], rule["maximum"])
        if rule["type"] == "integer" and type(v) is not int:
            raise SpecError(f"{path}.{key}: expected integer")
        if "multiple_of" in rule and not math.isclose(n / rule["multiple_of"], round(n / rule["multiple_of"]), abs_tol=1e-8):
            raise SpecError(f"{path}.{key}: not a multiple of {rule['multiple_of']}")
        result[key] = int(n) if rule["type"] == "integer" else n
    return result


def check_expression(expr, parameter_names, path):
    if type(expr) in (int, float):
        number(expr, path, -1e6, 1e6)
    elif isinstance(expr, list):
        if len(expr) != 3:
            raise SpecError(f"{path}: expression vectors require 3 values")
        for item in expr:
            check_expression(item, parameter_names, path)
    elif isinstance(expr, dict) and set(expr) == {"parameter"}:
        if not isinstance(expr["parameter"],str) or expr["parameter"] not in parameter_names:
            raise SpecError(f"{path}: unknown parameter expression")
    elif isinstance(expr, dict) and set(expr) == {"op", "args"}:
        if expr["op"] not in ("add", "multiply") or not isinstance(expr["args"], list) or not 2 <= len(expr["args"]) <= 8:
            raise SpecError(f"{path}: invalid arithmetic expression")
        for arg in expr["args"]:
            check_expression(arg, parameter_names, path)
    else:
        raise SpecError(f"{path}: unsupported expression (no Python evaluation)")


def evaluate(expr, parameters):
    if type(expr) in (int, float):
        return expr
    if isinstance(expr, list):
        return [evaluate(x, parameters) for x in expr]
    if "parameter" in expr:
        return parameters[expr["parameter"]]
    args = [evaluate(x, parameters) for x in expr["args"]]
    value = math.fsum(args) if expr["op"] == "add" else math.prod(args)
    return number(value, "expression", -1e6, 1e6)


def typed_value(value, kind, path):
    if kind == "Length":
        return number(value, path, 0, 1e6)
    if kind in ("Dimensions", "WallRef", "OpeningRef", "SpaceRef") and isinstance(value, list) and len(value) == 3:
        return [number(v, path, .000001, 1e6) for v in value]
    raise SpecError(f"{path}: unsupported/mismatched typed value {kind}")


def topological_order(edges, path):
    """edges maps node -> prerequisites; deterministic and cycle rejecting."""
    remaining = {key: set(value) for key, value in edges.items()}
    for key, dependencies in remaining.items():
        if dependencies - remaining.keys():
            raise SpecError(f"{path}.{key}: missing references {sorted(dependencies - remaining.keys())}")
    result = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:
            raise SpecError(f"{path}: cyclic dependency involving {sorted(remaining)}")
        result.extend(ready)
        for key in ready:
            del remaining[key]
        for deps in remaining.values():
            deps.difference_update(ready)
    return result
