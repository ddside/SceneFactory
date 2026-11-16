"""Reopened mesh measurements for the interior domain contract."""
import bpy
from scene_factory.interior_contracts import check


def validate(plan,context):
    if 'interior' not in plan:return None
    measured={}
    for obj in bpy.context.scene.objects:
        if obj.type=='MESH':
            measured.setdefault(obj['producer_node_id'],{})[obj['local_role']]=[list(obj.matrix_world @ v.co) for v in obj.data.vertices]
    return check(plan['interior'],{n['node_id']:n for n in plan['nodes']},measured)
