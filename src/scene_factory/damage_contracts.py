"""Versioned damage intent and deterministic artifact resolution; no bpy imports."""
import copy
from .spec import fields,identifier,number,SpecError
from .contract_utils import canonical_digest

TYPES={'rigid_displacement':'displaced','object_topple':'tilted','component_detach':'detached',
       'component_fracture':'fractured','structural_damage':'damaged','partial_collapse':'collapsed'}
GEOMETRY={'component_fracture','structural_damage','partial_collapse'}


def vector(value,label):
    if not isinstance(value,list) or len(value)!=3:raise SpecError(label+': finite 3-vector required')
    for v in value:number(v,label,-10000,10000)


def validate(value):
    fields(value,'damage',('schema_version','controller_node_id','operations'),('passage_expectations',))
    if type(value['schema_version']) is not int or value['schema_version']!=1:raise SpecError('damage: version 1 required')
    identifier(value['controller_node_id'],'damage.controller_node_id')
    if not isinstance(value['operations'],list) or not 1<=len(value['operations'])<=64:raise SpecError('damage: 1..64 operations required')
    expectations=value.get('passage_expectations',{})
    if not isinstance(expectations,dict):raise SpecError('damage: passage expectations must be a mapping')
    for nid,state in expectations.items():
        identifier(nid,'damage passage target')
        if state not in ('passable','partially_blocked','blocked'):raise SpecError('damage: invalid passage expectation')
    ids=set()
    for op in value['operations']:
        fields(op,'damage.operation',('operation_id','target_node_id','damage_type','severity','seed','displacement','rotation_degrees','pivot','support','parameters'),('target_component_id','target_role','damage_region'))
        for k in ['operation_id','target_node_id']:
            identifier(op[k],'damage.'+k)
        if op['operation_id'] in ids:raise SpecError('damage: duplicate operation ID')
        ids.add(op['operation_id'])
        for k in ['target_component_id','target_role']:
            if k in op:identifier(op[k],'damage.'+k)
        if op['damage_type'] not in TYPES:raise SpecError('damage: unsupported damage_type')
        number(op['severity'],'damage.severity',.01,1)
        if type(op['seed']) is not int or not 0<=op['seed']<=4294967295:raise SpecError('damage.seed: uint32 required')
        for k in ['displacement','rotation_degrees','pivot']:vector(op[k],'damage.'+k)
        fields(op['support'],'damage.support',('kind','ground'),('node_id',))
        if op['support']['kind'] not in ('floor','retained') or type(op['support']['ground']) is not bool:raise SpecError('damage: support requires floor/retained and boolean ground')
        if op['support']['kind']=='retained' and op['support']['ground']:raise SpecError('damage: retained support cannot request floor grounding')
        if 'node_id' in op['support']:identifier(op['support']['node_id'],'damage.support.node_id')
        fields(op['parameters'],'damage.parameters',(),('axis','split_fraction','irregularity'))
        if 'axis' in op['parameters'] and op['parameters']['axis'] not in (0,1,2):raise SpecError('damage.axis: 0/1/2 required')
        for k,lo,hi in [('split_fraction',.15,.85),('irregularity',0,.2)]:
            if k in op['parameters']:number(op['parameters'][k],'damage.'+k,lo,hi)
        if op['damage_type'] in ('structural_damage','partial_collapse'):
            if 'damage_region' not in op:raise SpecError('damage: geometry region required')
        if 'damage_region' in op:
            r=op['damage_region'];fields(r,'damage_region',('minimum','maximum'))
            vector(r['minimum'],'damage_region.minimum');vector(r['maximum'],'damage_region.maximum')
            if any(r['maximum'][i]-r['minimum'][i]<=1e-4 for i in range(3)):raise SpecError('damage: invalid/zero thickness region')
        if op['damage_type'] not in GEOMETRY and ('damage_region' in op or op['parameters']):raise SpecError('damage: rigid operations cannot change geometry')
    return copy.deepcopy(value)


def fragment_role(operation_id):return 'damage.fragment.'+operation_id


def resolve(value,plan):
    """Resolve immutable targets before executing any destructive operation."""
    from .compiler import artifact_id
    value=validate(value);nodes={n['node_id']:n for n in plan['nodes']};controller=nodes.get(value['controller_node_id'])
    if controller is None or controller['skill']!={'skill_id':'damage_processor','version':'1.0.0'}:raise SpecError('damage: registered controller missing')
    for nid in value.get('passage_expectations',{}):
        if nid not in nodes or nodes[nid]['skill']['skill_id'] not in ('arch_room','arch_corridor'):raise SpecError('damage: passage expectation references missing space')
    operations=[];geometry=set();rigid=set();fragments=[]
    for authored in value['operations']:
        op=copy.deepcopy(authored);owner=nodes.get(op['target_node_id'])
        if owner is None:raise SpecError('damage: target_node_id does not exist')
        target=nodes.get(op.get('target_component_id',op['target_node_id']))
        if target is None or target['node_id']!=owner['node_id'] and owner['node_id'] not in target['lineage']:raise SpecError('damage: component is not owned by target')
        descendants=[n for n in nodes.values() if n['node_id']==target['node_id'] or target['node_id'] in n['lineage']]
        selected=[a for n in descendants for a in n['expected_artifacts'] if a['type']=='Mesh' and ('target_role' not in op or a['local_role']==op['target_role'])]
        if not selected:raise SpecError('damage: target has no matching Mesh role')
        if op['damage_type'] in GEOMETRY or op['damage_type']=='component_detach':
            if len(selected)!=1:raise SpecError('damage: geometry/detach requires exactly one component/role')
        aids={a['artifact_id'] for a in selected}
        bucket=geometry if op['damage_type'] in GEOMETRY else rigid
        if aids.intersection(bucket) or aids.intersection(geometry if bucket is rigid else rigid):raise SpecError('damage: conflicting operations on the same artifact')
        bucket.update(aids)
        if op['support'].get('node_id') not in (None,*nodes):raise SpecError('damage: support node does not exist')
        floor=0.
        parent=target
        while parent is not None:
            if parent['skill']['skill_id']=='arch_building':
                floor=parent['world_matrix'][2][3];break
            parent=nodes.get(parent['parent_id'])
        support_node=op['support'].get('node_id')
        if support_node:
            sn=nodes[support_node]
            if sn['skill']['skill_id']!='arch_slab' or sn['parameters']['purpose']!=1:raise SpecError('damage: floor support must reference a floor slab')
            floor=sn['world_matrix'][2][3]+sn['parameters']['thickness']
        op.update(state=TYPES[op['damage_type']],resolved_node_id=target['node_id'],artifact_ids=sorted(aids),floor_elevation=floor)
        if op['damage_type'] in GEOMETRY:
            a=selected[0];role=fragment_role(op['operation_id']);fragment={**copy.deepcopy(a),'artifact_id':artifact_id(a['producer_node_id'],role),'local_role':role,'role':a['role']+'.'+role,'lineage':[*a['lineage'],a['producer_node_id']]}
            fragment.pop('component',None);fragment.pop('asset',None)
            fragment['damage']={'operation_id':op['operation_id'],'original_artifact_id':a['artifact_id'],'state':'detached','fixed':False}
            op['fragment_artifact_id']=fragment['artifact_id'];fragments.append(fragment)
        operations.append(op)
    return dict(schema_version=1,controller_node_id=value['controller_node_id'],operations=operations,fragments=fragments,
                passage_expectations=value.get('passage_expectations',{}),specification_hash=canonical_digest(value))


def classify_intersection(volume,volume_a,volume_b,short_dimension,semantic='furniture',intended_contact=False,penetration_depth=None):
    """A volume-based policy. AABB overlap is never supplied as exact volume.

    Fractions scale with object volume/thickness and declared contact intent.
    Absolute numerical tolerance is tied to object scale rather than cm examples.
    """
    if min(volume_a,volume_b,short_dimension)<=0:raise SpecError('damage: invalid collision measurement')
    fraction=volume/min(volume_a,volume_b)
    depth=fraction*short_dimension if penetration_depth is None else penetration_depth
    number(depth,'damage.penetration_depth',0,100000)
    scale=max(short_dimension,1e-6)
    # Geometric mean with the 1mm validation feature scale bounds absolute
    # contact depth for large objects without adopting the prompt's cm examples.
    tolerance=max(1e-6,min(scale*(.08 if intended_contact else .035),(scale*.001)**.5))
    if volume<=scale**3*1e-8 or fraction<=.04 and depth<=tolerance:return 'PASS'
    limit=.25 if semantic=='floor' else .55 if intended_contact else .4
    if fraction>=limit:return 'FAIL'
    return 'WARNING'
