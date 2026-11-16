"""Reusable low-poly beveled furniture components, independent mesh validation."""
import math
import bpy
import bmesh
from scene_factory.blender.generators import cuboid_vertices,FACES
from scene_factory.blender.skills.common import close,validate_material
from scene_factory.contract_utils import canonical_digest

COLORS=((.42,.23,.10),(.33,.37,.41),(.12,.28,.42),(.025,.035,.045),(.72,.72,.68),(.65,.35,.12))


def generate(node,context):
    p=node['parameters'];size=[p[k] for k in ('width','depth','height')]
    bindings=[]
    for b in (context['plan'].get('appearance') or {}).get('bindings',[]):
        if b['node_id']==node['node_id']:
            bindings.append({**{k:v for k,v in b.items() if k!='node_id'},'ref':context['plan']['appearance']['materials'][b['material']]})
    key=canonical_digest([p,bindings]);cache=context.setdefault('mesh_cache',{})
    mesh=cache.get(key)
    if mesh is None:
        mesh=bpy.data.meshes.new('furniture.component');mesh.from_pydata(cuboid_vertices(size),[],FACES);mesh.update()
        if p['bevel']:
            bm=bmesh.new();bm.from_mesh(mesh)
            bmesh.ops.bevel(bm,geom=list(bm.edges),offset=p['bevel'],segments=2,affect='EDGES')
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free();mesh.update()
        mat=bpy.data.materials.new('furniture.surface');mat.use_nodes=True;mat.diffuse_color=(*COLORS[p['surface']],1)
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=mat.diffuse_color
        mat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.8;mesh.materials.append(mat);cache[key]=mesh
    obj=bpy.data.objects.new(node['node_id'],mesh);bpy.context.scene.collection.objects.link(obj)
    obj['component_state']='normal';obj['component_surface']=p['surface']
    return {'geometry':obj}


def validate(node,objects,context):
    obj=objects['geometry'];p=node['parameters'];mesh=obj.data
    points=[v.co for v in mesh.vertices];dims=[p[k] for k in ('width','depth','height')]
    close([min(v[i] for v in points) for i in range(3)],[-dims[0]/2,-dims[1]/2,0],'furniture lower bounds')
    close([max(v[i] for v in points) for i in range(3)],[dims[0]/2,dims[1]/2,dims[2]],'furniture upper bounds')
    bm=bmesh.new();bm.from_mesh(mesh)
    try:
        if not all(e.is_manifold and e.is_contiguous for e in bm.edges):raise ValueError('furniture component must be closed and consistently oriented')
        volume=bm.calc_volume(signed=True);maximum=math.prod(dims);minimum=math.prod(max(d-2*p['bevel'],1e-6) for d in dims)
        if not minimum-1e-6<=volume<=maximum+1e-6:raise ValueError('furniture component volume outside beveled solid envelope')
        center=(0,0,dims[2]/2)
        for f in bm.faces:
            if f.calc_area()<=1e-10 or sum((f.calc_center_median()[i]-center[i])*f.normal[i] for i in range(3))<=0:
                raise ValueError('furniture degenerate/inward component face')
    finally:bm.free()
    if obj.get('component_state')!='normal' or obj.get('component_surface')!=p['surface']:raise ValueError('furniture component metadata mismatch')
    validate_material(obj)


def _validate_parts(node,objects,context,connected):
    if objects['frame'].type!='EMPTY':raise ValueError('furniture assembly frame missing')
    from scene_factory.furniture_contracts import assembly
    # Actual local mesh bounds, transformed by independently checked object matrices.
    boxes={}
    for n in context['plan']['nodes']:
        if n['skill']['skill_id']=='furniture_part' and node['node_id'] in n['lineage']:
            obj=context['primary_objects'][n['node_id']]
            points=[obj.matrix_world @ v.co for v in obj.data.vertices]
            boxes[n['node_id']]=[[min(v[i] for v in points) for i in range(3)],[max(v[i] for v in points) for i in range(3)]]
    assembly(node,{n['node_id']:n for n in context['plan']['nodes']},boxes,connected=connected)


def validate_assembly(node,objects,context):
    _validate_parts(node,objects,context,True)


def validate_group(node,objects,context):
    _validate_parts(node,objects,context,False)
