"""Phase 1 cuboids as leaf skills. Independent boundary/topology validator."""
import itertools
import math

from scene_factory.blender.generators import make_cuboid
from .common import close, validate_material


def generate(node, context):
    obj = {"stable_id": node["node_id"], "generator": node["skill"]["skill_id"],
           "parameters": node["parameters"], "transform": node["resolved_transform"]}
    result = make_cuboid(obj, context["scene_seed"], node_seed=node["node_seed"])
    return {"geometry": result}


def validate(node, objects, context):
    obj = objects["geometry"]
    p = node["parameters"]
    width, depth = p["width"], p["depth"]
    height = p["height"] if "height" in p else p["thickness"]
    mesh = obj.data
    if len(mesh.vertices) != 8 or len(mesh.polygons) != 6:
        raise ValueError(f"{node['node_id']}: cuboid requires 8 vertices / 6 faces")
    # Expected corners and planes are derived independently of make_cuboid/from_pydata.
    corners = list(itertools.product((-width/2, width/2), (-depth/2, depth/2), (0, height)))
    actual = [tuple(v.co) for v in mesh.vertices]
    unmatched = list(corners)
    for point in actual:
        match = next((c for c in unmatched if all(math.isclose(a, b, rel_tol=1e-6, abs_tol=2e-5)
                     for a, b in zip(point, c))), None)
        if match is None:
            raise ValueError(f"{node['node_id']}: incorrect cuboid corner")
        unmatched.remove(match)
    if unmatched:
        raise ValueError("cuboid: missing corners")
    planes = set()
    center = (0, 0, height/2)
    edge_uses = {}
    for face in mesh.polygons:
        indices = list(face.vertices)
        if len(indices) != 4 or len(set(indices)) != 4:
            raise ValueError("cuboid: each face must have four distinct vertices")
        for i, a in enumerate(indices):
            edge = tuple(sorted((a, indices[(i+1) % 4])))
            edge_uses[edge] = edge_uses.get(edge, 0) + 1
        plane = [(axis, side) for axis, sides in enumerate(((-width/2, width/2), (-depth/2, depth/2), (0, height)))
                 for side in sides if all(math.isclose(actual[i][axis], side, rel_tol=1e-6, abs_tol=2e-5) for i in indices)]
        if len(plane) != 1 or plane[0] in planes:
            raise ValueError("cuboid: incorrect or repeated face plane")
        planes.add(plane[0])
        axis, side = plane[0]
        expected_normal = [0., 0., 0.]
        expected_normal[axis] = 1. if side > center[axis] else -1.
        close(face.normal, expected_normal, "cuboid outward normal")
    if len(edge_uses) != 12 or any(count != 2 for count in edge_uses.values()):
        raise ValueError("cuboid: incorrect closed edge topology")
    close([max(v[i] for v in actual) - min(v[i] for v in actual) for i in range(3)],
          [width, depth, height], "cuboid independent local dimensions")
    validate_material(obj)
