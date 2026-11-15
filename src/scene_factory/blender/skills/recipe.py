"""Recipe container; child leaf implementations generate the actual components."""
import bpy


def generate(node, context):
    frame = bpy.data.objects.new(node["node_id"], None)
    bpy.context.scene.collection.objects.link(frame)
    return {"frame": frame}


def validate(node, objects, context):
    frame = objects["frame"]
    if frame.type != "EMPTY" or frame.data is not None:
        raise ValueError("recipe frame must be an Empty Object")
    children = [n for n in context["plan"]["nodes"] if n["parent_id"] == node["node_id"]]
    if not children:
        raise ValueError("recipe produced no child nodes")
    # Common validation checks the full declared child artifact inventory.
    if any(c["node_id"] not in context["primary_objects"] for c in children):
        raise ValueError("recipe child frame/object missing")
