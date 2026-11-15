"""Reusable Blender checks; never calls a geometry construction function."""
import math


def close(actual, expected, label):
    if len(actual) != len(expected) or any(not math.isfinite(a) or not math.isclose(
        a, b, rel_tol=1e-6, abs_tol=2e-5) for a, b in zip(actual, expected)):
        raise ValueError(f"{label}: expected {list(expected)}, got {list(actual)}")


def validate_material(obj):
    if len(obj.data.materials) != 1 or obj.data.materials[0] is None:
        raise ValueError(f"{obj.name}: missing material")
    mat = obj.data.materials[0]
    if not mat.use_nodes or not all(math.isfinite(v) for v in mat.diffuse_color):
        raise ValueError(f"{obj.name}: invalid material")
    shader = mat.node_tree.nodes.get("Principled BSDF")
    output = mat.node_tree.nodes.get("Material Output")
    if shader is None or output is None or not output.inputs["Surface"].is_linked:
        raise ValueError(f"{obj.name}: missing connected Principled material")
    close(shader.inputs["Base Color"].default_value, mat.diffuse_color, "base color")
    close([shader.inputs["Roughness"].default_value], [.8], "roughness")
