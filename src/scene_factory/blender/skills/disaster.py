"""Registered effects controller. All execution remains in Blender CLI."""
import bpy


def generate(node,context):
    obj=bpy.data.objects.new(node['node_id'],None);bpy.context.scene.collection.objects.link(obj);return {'frame':obj}


def validate(node,objects,context):
    if objects['frame'].type!='EMPTY':raise ValueError('disaster controller must be an Empty')


def apply(plan,context):
    from scene_factory.blender.effect_runtime import apply_effects
    return apply_effects(plan,context['registry'],context['resource_root'],context['base_state'])
