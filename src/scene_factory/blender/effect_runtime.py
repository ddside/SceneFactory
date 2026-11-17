"""Reusable effects stage, immutable baseline reuse and independent replay."""
import copy,json,math
import bpy
from mathutils import Matrix,Vector
from scene_factory.effect_contracts import sample,count,rng
from scene_factory.contract_utils import canonical_digest
from .engine import generate_plan,callback
from .damage_geometry import bounds,solid_volume
from .damage_runtime import isolated_replay
from .appearance import apply as apply_appearance,signature


def capture(plan,base_state=None):
    from .validation import geometry_digest
    objects={o['artifact_id']:o for o in bpy.context.scene.objects}
    records={aid:dict(parent=o.parent.get('artifact_id') if o.parent else None,basis=[list(r) for r in o.matrix_basis],world=[list(r) for r in o.matrix_world],digest=geometry_digest(o.data) if o.type=='MESH' else None) for aid,o in objects.items()}
    sharing={aid:sorted(k for k,p in objects.items() if p.type=='MESH' and p.data is o.data) for aid,o in objects.items() if o.type=='MESH'}
    return dict(plan=plan,records=records,sharing=sharing,baseline={aid:r['digest'] for aid,r in records.items() if r['digest']},modified=set(base_state['modified']) if base_state else set(),affected=set(base_state['affected']) if base_state else set(),skip=set(base_state['skip']) if base_state else set(),supports=copy.deepcopy(base_state['supports']) if base_state else [])


def metadata(obj,node,a):
    obj.name=a['artifact_id']
    for k in ['artifact_id','source_node_id','producer_node_id','role','local_role']:obj[k]=a[k]
    for key,value in [('stable_id',node['node_id']),('generator',node['skill']['skill_id']),('node_seed',node['node_seed']),('logical_parent',node['parent_id'] or ''),('typed_inputs',json.dumps(node['resolved_inputs'],sort_keys=True))]:obj[key]=value
    if 'effect' in a:obj['effect_origin']=canonical_digest(a['effect'])


def build_baseline(base,registry,resource_root):
    if 'damage' in base:
        from .damage_runtime import build
        _,state=build(base,registry,resource_root,return_state=True)
        return state
    from .validation import validate_scene
    from .interior import validate
    generate_plan(base,registry,resource_root)
    if base.get('appearance'):apply_appearance(base,resource_root)
    validate_scene(base,registry,domain_validators=(validate,) if base.get('interior') else (),resource_root=resource_root)
    return capture(base)


def source_point(plan,e,objects):
    nodes={n['node_id']:n for n in plan['nodes']};n=nodes[e['target_node_id']]
    op=next((o for o in plan.get('damage',{}).get('operations',[]) if o['operation_id']==e.get('source_operation_id')),None)
    if op and 'damage_region' in op:
        region=op['damage_region'];center=Vector([(region['minimum'][i]+region['maximum'][i])/2 for i in range(3)])
        return Matrix(nodes[op['resolved_node_id']]['world_matrix'])@center
    selected=[o for o in objects.values() if o.type=='MESH' and (o['producer_node_id']==n['node_id'] or n['node_id'] in nodes[o['producer_node_id']]['lineage'])]
    if selected:
        bs=[bounds(o) for o in selected];return Vector([(min(b[0][i] for b in bs)+max(b[1][i] for b in bs))/2 for i in range(3)])
    return Vector([n['world_matrix'][i][3] for i in range(3)])


def place(group,e,index,plan,objects,anchor):
    room=next(n for n in plan['nodes'] if n['node_id']==e['region']['room_id']);matrix=Matrix(room['world_matrix']);inverse=matrix.inverted();floor=matrix.translation.z
    points=[o.matrix_world@v.co for o in group for v in o.data.vertices];center=Vector([(min(v[i] for v in points)+max(v[i] for v in points))/2 for i in range(3)])
    rotation=Matrix.Rotation(math.radians(rng(plan['seed'],e,index,'yaw').choice([0,90,180,270])),4,'Z')
    surface_points=points+[o.matrix_world@f.center for o in group for f in o.data.polygons]+[o.matrix_world@((o.data.vertices[e.vertices[0]].co+o.data.vertices[e.vertices[1]].co)/2) for o in group for e in o.data.edges]
    probes=[rotation@(p-center) for p in surface_points]
    local=[rotation@(p-center) for p in points];margin=max(abs(p.x) for p in local)+.005;margin=max(margin,max(abs(p.y) for p in local)+.005)
    source_local=list(inverse@anchor)
    # Eight deterministic placement candidates resolve tall existing obstacles;
    # this is bounded generation, never iterative repair of small contacts.
    environment=[(o,bounds(o),o.matrix_world.inverted()) for o in objects.values() if o.type=='MESH' and o not in group and o.get('preview_group') not in ('cover','wall','south_wall')]
    for attempt in range(8):
        x,y=sample(plan['seed'],e,index+attempt*10000,source_local,margin);world=matrix@Vector([x,y,0]);z=floor-min(p.z for p in local);support=None;contact=None
        for point in probes:
            px,py=world.x+point.x,world.y+point.y
            for obj,b,inv in environment:
                if not b[0][0]-.001<=px<=b[1][0]+.001 or not b[0][1]-.001<=py<=b[1][1]+.001:continue
                origin=inv@Vector([px,py,floor+room['parameters']['height']+.1]);direction=(inv.to_3x3()@Vector([0,0,-1])).normalized()
                hit,location,_,_=obj.ray_cast(origin,direction)
                if hit:
                    height=(obj.matrix_world@location).z-point.z
                    if height>z:z=height;support=obj['artifact_id'];contact=list(point)
        low=min(p.z for p in local)+z;high=max(p.z for p in local)+z
        if low<floor+e['region']['minimum'][2]-.001 or high>floor+e['region']['maximum'][2]+.001:continue
        z-=e['parameters'].get('settle_fraction',0)*(max(p.z for p in local)-min(p.z for p in local))
        delta=Matrix.Translation((world.x,world.y,z))@rotation@Matrix.Translation(-center)
        poses=[(o,o.matrix_world.copy()) for o in group]
        for obj,m in poses:obj.parent=None;obj.matrix_parent_inverse=Matrix.Identity(4);obj.matrix_world=delta@m
        bpy.context.view_layer.update()
        for obj in group:obj['effect_support']=support or 'floor';obj['effect_placement_id']=e['effect_id'];obj['effect_support_probe']=contact or []
        return support
    raise ValueError('effects: no supported placement within region height budget')


def apply_effects(plan,registry,resource_root,base_state):
    if bpy.context.scene.get('effect_specification_hash'):raise ValueError('effects: double application rejected')
    effective=copy.deepcopy(plan);base_ids={n['node_id'] for n in plan['effects_baseline_plan']['nodes']}
    effective['nodes']=[copy.deepcopy(n) for n in base_state['plan']['nodes']]+[copy.deepcopy(n) for n in plan['nodes'] if n['node_id'] not in base_ids]
    effective['appearance']=copy.deepcopy(base_state['plan'].get('appearance'))
    if effective['appearance']:effective['appearance']['bindings']+=copy.deepcopy(plan['effect_bindings'])
    nodes={n['node_id']:n for n in effective['nodes']};objects={o['artifact_id']:o for o in bpy.context.scene.objects};primary={n['node_id']:objects[n['expected_artifacts'][0]['artifact_id']] for n in base_state['plan']['nodes']};cache={};by_effect={}
    for nid in plan['effect_execution_order']:
        n=nodes[nid];m=registry.get(n['skill']['skill_id'],n['skill']['version'],plan['validation_candidates'])
        generated=callback(registry,m['implementation'])(n,dict(plan=effective,primary_objects=primary,mesh_cache=cache,resource_root=resource_root))
        for a in n['expected_artifacts']:
            obj=generated[a['local_role']];metadata(obj,n,a)
            if n['parent_id']:obj.parent=primary[n['parent_id']]
            obj.matrix_basis=Matrix(n['local_matrix']);objects[a['artifact_id']]=obj
        primary[nid]=generated[n['expected_artifacts'][0]['local_role']]
    bpy.context.view_layer.update();reports=[];moved=set();environment={k:o for k,o in objects.items() if k in base_state['records']};new_ids=set(objects)-set(base_state['records'])
    source_totals={}
    for e in sorted(plan['effects']['items'],key=lambda e:(e['parameters'].get('layer',0),e['effect_id'])):
        point=source_point(effective,e,objects);kind=e['effect_type'];support_records=[]
        if kind=='crack_geometry':reports.append(dict(effect_id=e['effect_id'],kind=kind,representation='obstacle',synthetic=False,source_operation_id='effect.crack.'+e['effect_id']))
        if kind in ('debris','scatter'):
            p=e['parameters'];measured=0.
            op=next((o for o in plan.get('damage',{}).get('operations',[]) if o['operation_id']==e.get('source_operation_id')),None)
            budget=p['volume_budget']
            if op and op.get('fragment_artifact_id'):budget=min(budget,.5*solid_volume(objects[op['fragment_artifact_id']].data)*abs(objects[op['fragment_artifact_id']].matrix_world.to_3x3().determinant()))
            source_key=e.get('source_operation_id',e['target_node_id']+':'+e['region']['room_id'])
            region_volume=math.prod(e['region']['maximum'][i]-e['region']['minimum'][i] for i in range(3))
            source_cap=budget if op and op.get('fragment_artifact_id') else region_volume*.2
            previous,cap=source_totals.get(source_key,(0.,source_cap));cap=max(cap,source_cap)
            for i,nid in enumerate(e['generated_root_ids']):
                group=[o for o in objects.values() if o.type=='MESH' and (o['producer_node_id']==nid or nid in nodes[o['producer_node_id']]['lineage'])]
                measured+=sum(solid_volume(o.data)*abs(o.matrix_world.to_3x3().determinant()) for o in group)
                if measured+previous>cap+1e-7:raise ValueError('effects: aggregate synthetic source volume exceeded')
                if measured>budget+1e-7:raise ValueError('effects: synthetic debris exceeds source/explicit volume budget')
                support_records.append(dict(node_id=nid,support=place(group,e,i,effective,environment,point)))
                environment.update({o['artifact_id']:o for o in group})
            source_totals[source_key]=(previous+measured,cap)
            for i,nid in enumerate(p['existing_ids']):
                group=[o for o in objects.values() if o.type=='MESH' and (o['producer_node_id']==nid or nid in nodes[o['producer_node_id']]['lineage'])]
                if not group:raise ValueError('effects: scatter source has no geometry')
                place(group,e,i+count(e),effective,environment,point);moved.update(o['artifact_id'] for o in group)
                for obj in group:obj['effect_existing_source']=e['target_node_id']
            reports.append(dict(effect_id=e['effect_id'],kind=kind,count=len(e['generated_root_ids']),existing_count=len(p['existing_ids']),synthetic_volume=measured,volume_budget=budget,source=list(point),supports=support_records))
    if effective.get('appearance'):apply_appearance(effective,resource_root)
    from .effect_surfaces import apply_layers
    for e in sorted(plan['effects']['items'],key=lambda e:(e['parameters'].get('layer',0),e['effect_id'])):
        if e['effect_type']=='surface':
            value=copy.deepcopy(e);value['anchor_world']=list(source_point(effective,e,objects));ids=apply_layers(effective,value,objects)
            if not ids:raise ValueError('effects: surface selection matched no Mesh')
            reports.append(dict(effect_id=e['effect_id'],kind='surface',representation='appearance',targets=ids,surface_type=e['parameters']['surface_type'],material=plan['appearance']['materials'][e['material']]))
    bpy.context.scene['plan_digest']=plan['plan_digest'];bpy.context.scene['effect_specification_hash']=plan['effects']['specification_hash']
    final=capture(effective,base_state);final['affected'].update(a for a in new_ids if objects[a].type=='MESH');final['affected'].update(moved)
    final['modified'].update(a for a in new_ids if objects[a].type=='MESH')
    for aid in moved:
        n=nodes[objects[aid]['producer_node_id']];final['skip'].update([n['node_id'],*n['lineage']])
    final['baseline']=copy.deepcopy(base_state['baseline']);final['effect_reports']=reports
    final['effect_metadata']={aid:{k:obj.get(k) for k in ['effect_origin','effect_support','effect_placement_id','effect_existing_source','effect_layers']} for aid,obj in objects.items()}
    final['shader_signatures']={aid:surface_signature(o.material_slots[0].material) for aid,o in objects.items() if o.type=='MESH' and o.material_slots}
    final['base_state']=base_state
    return final


def construct(plan,registry,resource_root):
    state=build_baseline(plan['effects_baseline_plan'],registry,resource_root)
    return callback(registry,plan['effects_postprocess'])(plan,dict(registry=registry,resource_root=resource_root,base_state=state))


def validate_saved(plan,registry,resource_root,state=None,cache=None):
    from .validation import validate_scene,geometry_digest
    from .effect_validation import domain
    if bpy.context.scene.get('effect_specification_hash')!=plan['effects']['specification_hash']:raise ValueError('effects: specification marker mismatch')
    if cache:verify_base(plan,cache)
    state=state or isolated_replay(lambda:construct(plan,registry,resource_root));objects={o.get('artifact_id'):o for o in bpy.context.scene.objects}
    if set(objects)!=set(state['records']):raise ValueError('effects: missing/duplicate generated artifacts')
    for aid,obj in objects.items():
        if {k:obj.get(k) for k in state['effect_metadata'][aid]}!=state['effect_metadata'][aid]:raise ValueError('effects: lineage/support/layer metadata mismatch')
        if obj.type=='MESH':
            if geometry_digest(obj.data)!=state['records'][aid]['digest']:raise ValueError('effects: deterministic geometry changed')
            if obj.material_slots and surface_signature(obj.material_slots[0].material)!=state['shader_signatures'][aid]:raise ValueError('effects: surface graph changed')
            actual=sorted(k for k,o in objects.items() if o.type=='MESH' and o.data is obj.data)
            if actual!=state['sharing'][aid]:raise ValueError('effects: mesh sharing / isolation mismatch')
            if aid in state['affected']:solid_volume(obj.data)
    result=validate_scene(state['plan'],registry,resource_root=resource_root,artifact_state=state)
    result['domain_results'].append(domain(plan,state,objects))
    return result


def surface_signature(material):
    options={n.name:{k:getattr(n,k,None) for k in ['noise_dimensions','wave_type','bands_direction']} for n in material.node_tree.nodes if n.name.startswith('effect.')}
    for n in material.node_tree.nodes:
        if n.name.startswith('effect.') and hasattr(n,'object'):
            options[n.name]['object']=n.object.get('artifact_id') if n.object else None
    return canonical_digest([signature(material),options])


def serializable(state):
    return {k:sorted(v) if isinstance(v,set) else v for k,v in state.items()}


def restore_state(value):
    value=copy.deepcopy(value)
    for k in ['modified','affected','skip']:value[k]=set(value[k])
    return value


def verify_base(plan,cache):
    from pathlib import Path
    from scene_factory.storage import digest
    base=plan['effects_baseline_plan']
    if cache['plan_digest']!=base['plan_digest']:raise ValueError('effects: baseline cache identity mismatch')
    for key in ['blend','state']:
        if digest(cache[key+'_path'])!=cache[key+'_sha256']:raise ValueError('effects: corrupt baseline cache')
    data=json.loads(Path(cache['state_path']).read_text())
    if data['plan_digest']!=base['plan_digest']:raise ValueError('effects: baseline state fingerprint mismatch')
    return restore_state(data['state'])


def load_base(plan,registry,resource_root,cache):
    from .validation import validate_scene
    from .interior import validate
    base=plan['effects_baseline_plan'];state=verify_base(plan,cache)
    bpy.ops.wm.open_mainfile(filepath=cache['blend_path'],load_ui=False,use_scripts=False)
    if 'damage' in base:
        from .damage_runtime import validate_saved
        validate_saved(base,registry,resource_root,state)
    else:validate_scene(base,registry,domain_validators=(validate,) if base.get('interior') else (),resource_root=resource_root)
    return state


def build(plan,registry,resource_root,out,reuse=None):
    from pathlib import Path
    from scene_factory.storage import write_json,digest
    out=Path(out);base=plan['effects_baseline_plan']
    state=load_base(plan,registry,resource_root,reuse) if reuse else build_baseline(base,registry,resource_root)
    state_path=out/'base-state.json';blend=out/'base-scene.blend'
    write_json(state_path,dict(plan_digest=base['plan_digest'],state=serializable(state)))
    bpy.context.preferences.filepaths.save_version=0
    if bpy.ops.wm.save_as_mainfile(filepath=str(blend))!={'FINISHED'}:raise ValueError('effects: baseline snapshot save failed')
    cache=dict(plan_digest=base['plan_digest'],blend_path=str(blend),state_path=str(state_path),blend_sha256=digest(blend),state_sha256=digest(state_path))
    result=validate_saved(plan,registry,resource_root,callback(registry,plan['effects_postprocess'])(plan,dict(registry=registry,resource_root=resource_root,base_state=state)))
    result['effects_cache']=cache;result['base_reused']=bool(reuse)
    return result
