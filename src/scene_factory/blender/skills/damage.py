"""Registered controller for deterministic post-generation damage operations."""
import bpy


def generate(node,context):
    obj=bpy.data.objects.new(node['node_id'],None);bpy.context.scene.collection.objects.link(obj)
    return {'frame':obj}


def validate(node,objects,context):
    if objects['frame'].type!='EMPTY':raise ValueError('damage controller frame missing')


def apply(plan,context):
    from scene_factory.blender.damage_runtime import apply_operations
    return apply_operations(plan,context)
