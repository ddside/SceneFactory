"""Non-cuboid leaf skill and its independent geometric validator."""
import math
import bpy

from .common import close, validate_material


def generate(node, context):
    p = node["parameters"]
    bpy.ops.mesh.primitive_cylinder_add(vertices=p["segments"], radius=p["radius"], depth=p["height"],
                                       end_fill_type="NGON", location=(0,0,0))
    obj = bpy.context.object
    for vertex in obj.data.vertices:
        vertex.co.z += p["height"] / 2
    obj.data.update()
    mat = bpy.data.materials.new(node["node_id"] + ".material")
    mat.use_nodes = True
    mat.diffuse_color = (.45,.5,.55,1)
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = .8
    obj.data.materials.append(mat)
    return {"geometry": obj}


def validate(node, objects, context):
    obj = objects["geometry"]
    mesh, p = obj.data, node["parameters"]
    n, radius, height = p["segments"], p["radius"], p["height"]
    if len(mesh.vertices) != n * 2 or len(mesh.polygons) != n + 2:
        raise ValueError("cylinder: incorrect topology counts")
    rings = {0: [], 1: []}
    for vertex in mesh.vertices:
        x,y,z = vertex.co
        close([math.hypot(x,y)], [radius], "cylinder radius")
        ring = 0 if abs(z) < abs(z-height) else 1
        close([z], [0 if ring == 0 else height], "cylinder height")
        rings[ring].append(math.atan2(y,x))
    for angles in rings.values():
        if len(angles) != n:
            raise ValueError("cylinder: uneven ring counts")
        angles.sort()
        close([(angles[(i+1)%n]-angles[i]) % (2*math.pi) for i in range(n)],
              [2*math.pi/n]*n, "cylinder angular spacing")
    if sorted(len(p.vertices) for p in mesh.polygons) != sorted([4]*n+[n,n]):
        raise ValueError("cylinder: invalid cap/side topology")
    points = [v.co for v in mesh.vertices]
    close([min(v[i] for v in points) for i in range(3)], [-radius,-radius,0], "cylinder lower bound")
    close([max(v[i] for v in points) for i in range(3)], [radius,radius,height], "cylinder upper bound")
    validate_material(obj)
