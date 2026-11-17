"""Damage application and independent replay/reopen verification.

The normal generator/skill checks remain authoritative for undamaged geometry.
Reopen verification replays into an isolated temporary scene, then compares all
saved artifacts and independently checks closed solids, support and penetration.
"""
import copy,json
import bpy
from mathutils import Vector
from scene_factory.contract_utils import canonical_digest
from scene_factory.damage_contracts import GEOMETRY
from .engine import generate_plan,callback
from .damage_geometry import bounds,cutter,boolean_mesh,solid_volume,remove_object,pose


def effective_plan(plan):
    result=copy.deepcopy(plan);nodes={n['node_id']:n for n in result['nodes']}
    for a in plan['damage']['fragments']:
        nodes[a['producer_node_id']]['expected_artifacts'].append(copy.deepcopy(a))
        if result.get('appearance'):
            original=a['damage']['original_artifact_id'];source=next(v for v in plan['baseline_plan']['expected_artifacts'] if v['artifact_id']==original)
            for b in plan['appearance']['bindings']:
                if b['node_id']==source['producer_node_id'] and b['role']==source['local_role']:
                    result['appearance']['bindings'].append({**copy.deepcopy(b),'role':a['local_role']})
    return result


def stamp_fragment(obj,declaration,node):
    obj.name=declaration['artifact_id']
    for k in ['artifact_id','source_node_id','producer_node_id','role','local_role']:obj[k]=declaration[k]
    obj['stable_id']=node['node_id'];obj['generator']=node['skill']['skill_id'];obj['node_seed']=node['node_seed']
    obj['logical_parent']=node['parent_id'] or '';obj['typed_inputs']=json.dumps(node['resolved_inputs'],sort_keys=True)
    obj['component_state']='detached';obj['damage_lineage']=canonical_digest(declaration['damage'])


def apply_operations(plan,context):
    from .validation import geometry_digest
    expected=effective_plan(plan);nodes={n['node_id']:n for n in expected['nodes']}
    objects={o['artifact_id']:o for o in bpy.context.scene.objects}
    baseline={aid:geometry_digest(o.data) for aid,o in objects.items() if o.type=='MESH'}
    modified=set();affected=set();skip=set();support_records=[]
    for op in plan['damage']['operations']:
        selected=[objects[k] for k in op['artifact_ids']];affected.update(op['artifact_ids'])
        for aid in op['artifact_ids']:
            a=next(a for a in expected['expected_artifacts'] if a['artifact_id']==aid);n=nodes[a['producer_node_id']]
            skip.update([n['node_id'],*n['lineage']])
            # Structural validators also own cross-node wall/space references.
            if n['skill']['skill_id'].startswith('arch_'):skip.update(v['node_id'] for v in nodes.values() if v['skill']['skill_id'].startswith('arch_'))
        anchor=objects[nodes[op['resolved_node_id']]['expected_artifacts'][0]['artifact_id']]
        pivot=list(anchor.matrix_world@Vector(op['pivot']))
        if op['damage_type'] in GEOMETRY:
            source=selected[0];low,high=bounds(source,False)
            if op['damage_type']=='component_fracture':
                axis=op['parameters'].get('axis',2);fraction=op['parameters'].get('split_fraction',.15+.7*op['severity'])
                minimum=[low[i]-(high[i]-low[i])*.1 for i in range(3)];maximum=[high[i]+(high[i]-low[i])*.1 for i in range(3)]
                minimum[axis]=low[axis]+(high[axis]-low[axis])*fraction
            else:
                lo=op['damage_region']['minimum'];hi=op['damage_region']['maximum'];scale=.35+.65*op['severity']
                minimum=[(lo[i]+hi[i])/2-(hi[i]-lo[i])*scale/2 for i in range(3)]
                maximum=[(lo[i]+hi[i])/2+(hi[i]-lo[i])*scale/2 for i in range(3)]
            cut=cutter(minimum,maximum,op['seed'],op['parameters'].get('irregularity',0)*op['severity']);cut.matrix_world=source.matrix_world.copy()
            try:
                remaining=boolean_mesh(source,cut,'DIFFERENCE');fragment=boolean_mesh(source,cut,'INTERSECT')
                solid_volume(remaining);solid_volume(fragment)
            finally:remove_object(cut)
            original_volume=solid_volume(source.data);retained=solid_volume(remaining);removed=solid_volume(fragment)
            if abs(retained+removed-original_volume)>max(original_volume*1e-4,1e-8):raise ValueError('damage: cut does not conserve solid volume')
            source.data=remaining;modified.add(source['artifact_id'])
            declaration=next(a for a in plan['damage']['fragments'] if a['artifact_id']==op['fragment_artifact_id'])
            obj=bpy.data.objects.new(declaration['artifact_id'],fragment);bpy.context.scene.collection.objects.link(obj);obj.matrix_world=source.matrix_world.copy()
            stamp_fragment(obj,declaration,nodes[declaration['producer_node_id']]);objects[declaration['artifact_id']]=obj
            affected.add(declaration['artifact_id']);modified.add(declaration['artifact_id'])
            pose([obj],op,pivot)
            source['damage_state']=op['state'];source['damage_operation_id']=op['operation_id']
        else:
            pose(selected,op,pivot)
            for obj in selected:obj['damage_state']=op['state'];obj['damage_operation_id']=op['operation_id']
        support_records.append(dict(operation_id=op['operation_id'],artifact_ids=op['artifact_ids'],fragment_artifact_id=op.get('fragment_artifact_id'),support=op['support'],floor_elevation=op['floor_elevation'],state=op['state']))
    bpy.context.scene['plan_digest']=plan['plan_digest'];bpy.context.scene['damage_specification_hash']=plan['damage']['specification_hash']
    if expected.get('appearance'):
        from .appearance import apply
        apply(expected,context['resource_root'])
    bpy.context.view_layer.update()
    records={o['artifact_id']:dict(parent=o.parent.get('artifact_id') if o.parent else None,basis=[list(r) for r in o.matrix_basis],world=[list(r) for r in o.matrix_world],digest=geometry_digest(o.data) if o.type=='MESH' else None,state=o.get('damage_state'),operation=o.get('damage_operation_id'),lineage=o.get('damage_lineage')) for o in bpy.context.scene.objects}
    sharing={aid:sorted(k for k,other in objects.items() if other.type=='MESH' and other.data is obj.data) for aid,obj in objects.items() if obj.type=='MESH'}
    return dict(plan=expected,records=records,sharing=sharing,modified=modified,affected=affected,skip=skip,baseline=baseline,supports=support_records)


def build(plan,registry,resource_root,return_state=False):
    from .validation import validate_scene
    from .interior import validate as interior_validate
    normal=plan['baseline_plan'];generate_plan(normal,registry,resource_root)
    if normal.get('appearance'):
        from .appearance import apply
        apply(normal,resource_root)
    validate_scene(normal,registry,domain_validators=(interior_validate,) if 'interior' in normal else (),resource_root=resource_root)
    state=callback(registry,plan['damage_postprocess'])(plan,dict(resource_root=resource_root))
    validation=validate_saved(plan,registry,resource_root,state)
    return (validation,state) if return_state else validation


def replay(plan,registry,resource_root):
    def builder():
        from .validation import validate_scene
        from .interior import validate as interior_validate
        normal=plan['baseline_plan'];generate_plan(normal,registry,resource_root)
        if normal.get('appearance'):
            from .appearance import apply
            apply(normal,resource_root)
        validate_scene(normal,registry,domain_validators=(interior_validate,) if 'interior' in normal else (),resource_root=resource_root)
        return callback(registry,plan['damage_postprocess'])(plan,dict(resource_root=resource_root))
    return isolated_replay(builder)


def isolated_replay(builder):
    original=bpy.context.window.scene;old=list(original.objects);names={o:o.name for o in old}
    for obj in old:obj.name='damage.saved.'+obj.name
    existing={k:set(getattr(bpy.data,k)) for k in ['objects','meshes','materials']}
    temp=bpy.data.scenes.new('Damage verification');bpy.context.window.scene=temp
    try:
        return builder()
    finally:
        bpy.context.window.scene=original
        for obj in set(bpy.data.objects)-existing['objects']:bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.scenes.remove(temp)
        for kind in ['meshes','materials']:
            collection=getattr(bpy.data,kind)
            for item in set(collection)-existing[kind]:
                if item.users==0:collection.remove(item)
        for obj,name in names.items():obj.name=name


def validate_saved(plan,registry,resource_root,state=None):
    from .validation import validate_scene,geometry_digest
    from .damage_validation import domain
    if bpy.context.scene.get('damage_specification_hash')!=plan['damage']['specification_hash']:raise ValueError('damage specification marker mismatch')
    state=state or replay(plan,registry,resource_root)
    objects={o.get('artifact_id'):o for o in bpy.context.scene.objects}
    if set(objects)!=set(state['records']):raise ValueError('damage: saved artifact inventory mismatch')
    for aid,record in state['records'].items():
        obj=objects[aid]
        for key,expected in [('damage_state',record['state']),('damage_operation_id',record['operation']),('damage_lineage',record['lineage'])]:
            if obj.get(key)!=expected:raise ValueError('damage: state/lineage metadata mismatch')
        if obj.type=='MESH':
            if geometry_digest(obj.data)!=record['digest']:raise ValueError('damage: geometry differs from deterministic replay')
            if aid in state['affected']:solid_volume(obj.data)
            if aid in state['baseline'] and aid not in state['modified'] and geometry_digest(obj.data)!=state['baseline'][aid]:raise ValueError('damage: untouched geometry changed')
            actual=sorted(k for k,o in objects.items() if o.type=='MESH' and o.data is obj.data)
            if actual!=state['sharing'][aid]:raise ValueError('damage: copy-on-write / mesh sharing mismatch')
    result=validate_scene(state['plan'],registry,resource_root=resource_root,artifact_state=state)
    result['domain_results'].append(domain(plan,state,objects))
    return result
