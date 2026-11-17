"""Compile an effects layer over an independently reusable normal/damaged plan."""
import copy,math
from .effect_contracts import validate,count,rng,KINDS
from .contract_utils import canonical_digest
from .spec import SpecError


def compile_effects(source,registry,source_sha256,runtime_profile,allow_candidates,resources):
    from .compiler import compile_scene,child_id,artifact_id,node_seed
    from .scene_v2 import validate_v2
    from .architecture_layout import node
    from .damage_layout import with_damage,operation
    authored=validate_v2(source,registry,allow_candidates);effects=validate(authored['effects']);controller=effects['controller_node_id']
    cn=next((n for n in authored['nodes'] if n['node_id']==controller),None)
    if cn is None or cn['skill']!={'skill_id':'disaster_processor','version':'1.0.0'}:raise SpecError('effects: validated disaster controller required')
    base=copy.deepcopy(authored);base.pop('effects');base['nodes']=[n for n in base['nodes'] if n['node_id']!=controller]
    for e in effects['items']:
        if e['effect_type']=='crack_geometry':
            p=e['parameters'];op=operation('effect.crack.'+e['effect_id'],e['target_node_id'],'structural_damage',component=p['target_component_id'],role=p['target_role'],region=(p['minimum'],p['maximum']),displacement=p['displacement'],severity=e['severity'],seed=e['seed'])
            old=base.get('damage',{}).get('operations',[]);base=with_damage(base,[*old,op])
    compiled=compile_scene(base,registry,canonical_digest(base),runtime_profile,allow_candidates,resources)
    baseline=compiled['build_plan'];nodes={n['node_id']:n for n in baseline['nodes']};added=[];bindings=[];total=0;used={}
    controller_plan=compile_scene(dict(schema_version=2,scene_id=base['scene_id'],seed=base['seed'],units='m',nodes=[cn]),registry,runtime_profile=runtime_profile,allow_candidates=allow_candidates)['build_plan']
    added.extend(controller_plan['nodes']);used.update({(p['skill_id'],p['version']):p for p in controller_plan['skills_lock']['skills']})
    material_aliases=authored.get('appearance',{}).get('materials',{})
    resolved=[];surface_pairs=[];execution=[controller]
    for e in effects['items']:
        if e['target_node_id'] not in nodes:raise SpecError('effects: source target does not exist')
        room=nodes.get(e['region']['room_id'])
        if room is None or room['skill']['skill_id']!='arch_room':raise SpecError('effects: target region room does not exist')
        if e['material'] not in material_aliases:raise SpecError('effects: missing MaterialRef alias')
        lo,hi=e['region']['minimum'],e['region']['maximum'];p=e['parameters']
        if any(lo[i]<-room['parameters'][k]/2-1e-6 or hi[i]>room['parameters'][k]/2+1e-6 for i,k in enumerate(['width','depth'])) or lo[2]<0 or hi[2]>room['parameters']['height']+.001:raise SpecError('effects: region outside room')
        op=None
        if 'source_operation_id' in e:
            op=next((o for o in baseline.get('damage',{}).get('operations',[]) if o['operation_id']==e['source_operation_id']),None)
            if op is None or e['target_node_id'] not in (op['target_node_id'],op['resolved_node_id']):raise SpecError('effects: missing/mismatched damage source operation')
        item=copy.deepcopy(e);item.update(generated_root_ids=[],generated_node_ids=[])
        if e['effect_type']=='surface':
            for nid in p['targets']:
                if nid not in nodes:raise SpecError('effects: surface target missing')
            selected=set()
            for n in nodes.values():
                ancestors=set(n['lineage']);parent=n
                while parent['parent_id']:
                    ancestors.add(parent['parent_id']);parent=nodes[parent['parent_id']]
                if n['node_id'] in p['targets'] or ancestors.intersection(p['targets']):
                    selected.update(a['artifact_id'] for a in baseline['expected_artifacts'] if a['type']=='Mesh' and a['producer_node_id']==n['node_id'])
            if not selected:raise SpecError('effects: surface selector matched no Mesh')
            item['target_mesh_ids']=sorted(selected)
            if p['surface_type']=='waterline' and not lo[2]<=p['height']<=hi[2]:raise SpecError('effects: waterline outside target region')
            if sum(len(x['target_mesh_ids']) for x in surface_pairs)+len(selected)>512:raise SpecError('effects: surface assignment budget exceeded')
            for aid in selected:
                if sum(aid in x['target_mesh_ids'] for x in surface_pairs)>=8:raise SpecError('effects: material layer budget exceeded')
            for old in surface_pairs:
                if old['parameters']['layer']==p['layer'] and set(old['target_mesh_ids']).intersection(selected) and old['region']['room_id']==e['region']['room_id'] and all(min(old['region']['maximum'][i],hi[i])>max(old['region']['minimum'][i],lo[i]) for i in range(3)):
                    raise SpecError('effects: overlapping material layers require explicit distinct order')
            surface_pairs.append(item)
        elif e['effect_type'] in ('debris','scatter'):
            for nid in p['existing_ids']:
                if nid not in nodes:raise SpecError('effects: existing scatter target missing')
                if any(nid in x.get('parameters',{}).get('existing_ids',[]) for x in resolved):raise SpecError('effects: object scattered twice')
            roots=[];volume_bound=0.
            for i in range(count(e)):
                nid=child_id(controller,e['effect_id']+'.'+str(i));r=rng(base['seed'],e,i%p['variants'],'shape')
                dims=[round(r.uniform(p['size_min'][k],p['size_max'][k]),8) for k in range(3)]
                if e['effect_type']=='debris':
                    kind=KINDS.index(p['material_type'])
                    if kind==1 and dims[2]>.2*min(dims[:2]) or kind==3 and dims[2]>.08*min(dims[:2]) or kind==2 and max(dims[:2])<3*min(dims[:2]):raise SpecError('effects: dimensions do not fit material-specific shape')
                    params=dict(width=dims[0],depth=dims[1],height=dims[2],kind=kind,shape_seed=r.randrange(1000000),variant=i%p['variants'],irregularity=p['irregularity'])
                    skill='debris_fragment'
                else:params=dict(width=dims[0],depth=dims[1],height=dims[2]);skill=p['scatter_skill']
                roots.append(node(nid,skill,params));item['generated_root_ids'].append(nid);volume_bound+=math.prod(dims)
            if volume_bound>p['volume_budget']+1e-9:raise SpecError('effects: requested debris exceeds explicit volume budget')
            item['volume_bound']=volume_bound
            if roots:
                part=compile_scene(dict(schema_version=2,scene_id=base['scene_id'],seed=base['seed'],units='m',nodes=roots),registry,allow_candidates=allow_candidates,runtime_profile=runtime_profile)['build_plan']
                execution.extend(part['execution_order'])
                for n in part['nodes']:
                    if n['node_id'] in nodes or any(a['node_id']==n['node_id'] for a in added):raise SpecError('effects: generated node ID collision')
                    n['effect_id']=e['effect_id'];item['generated_node_ids'].append(n['node_id'])
                    for a in n['expected_artifacts']:
                        a['effect']=dict(effect_id=e['effect_id'],source_node_id=e['target_node_id'],source_operation_id=e.get('source_operation_id'),synthetic=True,representation='detail' if e['effect_type']=='debris' and p['material_type']=='glass' and p['size_max'][2]<=.005 else 'obstacle',semantic=p['material_type'],fixed=False)
                        if a['type']=='Mesh':bindings.append(dict(node_id=n['node_id'],role=a['local_role'],material=e['material'],uv=dict(meters_per_repeat=[1,1],rotation_degrees=0)))
                    added.append(n)
                used.update({(p['skill_id'],p['version']):p for p in part['skills_lock']['skills']})
                total+=len(part['nodes'])
        resolved.append(item)
    if len(nodes)+len(added)>1000 or total>800:raise SpecError('effects: expanded node budget exceeded')
    plan=copy.deepcopy(baseline);plan['effects_baseline_plan']=baseline;plan['nodes']=baseline['nodes']+added
    plan['expected_artifacts']=sorted(baseline['expected_artifacts']+[a for n in added for a in n['expected_artifacts']],key=lambda a:a['artifact_id'])
    used.update({(p['skill_id'],p['version']):p for p in baseline['skills_lock']['skills']})
    plan['skills_lock']={'schema_version':1,'skills':[used[k] for k in sorted(used)]}
    plan['effects']=dict(schema_version=1,controller_node_id=controller,items=resolved,specification_hash=canonical_digest(effects))
    plan['effects_postprocess']=registry.get('disaster_processor','1.0.0',allow_candidates)['postprocess']
    plan['effect_execution_order']=execution;plan['effect_bindings']=bindings;plan['source_sha256']=source_sha256 or canonical_digest(source);plan['appearance']=copy.deepcopy(authored.get('appearance'))
    plan['source_schema_version']=2;plan['plan_digest']=canonical_digest({k:v for k,v in plan.items() if k!='plan_digest'})
    return dict(build_plan=plan,skills_lock=plan['skills_lock'],resolved_scene=dict(schema_version=1,authoring_spec=authored,nodes=plan['nodes']))
