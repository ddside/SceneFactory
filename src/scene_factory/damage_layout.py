"""Codex authoring helpers. Normal nodes/materials remain the editable source."""
import copy
from .architecture_layout import node
from .compiler import child_id
from .interior_layout import interior_scene,item,apply_materials


def operation(operation_id,target,kind,component=None,role=None,displacement=(0,0,0),rotation=(0,0,0),region=None,severity=.5,seed=42,ground=True,parameters=None,pivot=(0,0,0)):
    result=dict(operation_id=operation_id,target_node_id=target,damage_type=kind,severity=severity,seed=seed,displacement=list(displacement),rotation_degrees=list(rotation),pivot=list(pivot),support=dict(kind='floor' if ground else 'retained',ground=ground),parameters=parameters or {})
    if component:result['target_component_id']=component
    if role:result['target_role']=role
    if region:result['damage_region']=dict(minimum=region[0],maximum=region[1])
    return result


def with_damage(spec,operations):
    s=copy.deepcopy(spec)
    if not any(n['node_id']=='damage.controller' for n in s['nodes']):s['nodes'].append(node('damage.controller','damage_processor',{}))
    s['damage']=dict(schema_version=1,controller_node_id='damage.controller',operations=copy.deepcopy(operations))
    return s


def normal_office():
    s=interior_scene('office');r='building.main.room.01';shelf=r+'.furniture.shelf.damage-demo'
    room=next(n for n in s['nodes'] if n['node_id']==r)
    item(s,shelf,'shelf',r,(1.7,room['parameters']['depth']/2-.08-.225,0))
    s['interior']['rooms'][0]['requirements']['shelf']=1
    r='building.main.room.03';item(s,r+'.furniture.cabinet.damage-demo','cabinet',r,(2.1,1.7,0))
    s['interior']['rooms'][2]['requirements']['cabinet']=1
    r='building.main.room.02';item(s,r+'.column','pillar',r,(-2,0,0),dict(width=.3,depth=.3,height=3))
    s['interior']['rooms'][1]['requirements']['pillar']=1
    s=apply_materials(s)
    s['appearance']['bindings'].append(dict(node_id=r+'.column',role='geometry',material='concrete',uv=dict(meters_per_repeat=[1,1],rotation_degrees=0)))
    return s


def acceptance_scene(label='D'):
    s=normal_office();work='building.main.room.01';storage='building.main.room.03';meeting='building.main.room.02';shelf=work+'.furniture.shelf.damage-demo'
    ws=work+'.furniture.workstation.'
    a=[operation('work.shelf.topple',shelf,'object_topple',rotation=(90,0,0)),
       operation('chair.01.tilt',ws+'01','object_topple',component=child_id(ws+'01','chair'),rotation=(20,0,0),displacement=(-.05,-.1,0)),
       operation('chair.02.tilt',ws+'02','object_topple',component=child_id(ws+'02','chair'),rotation=(15,0,0),displacement=(.05,-.1,0))]
    b=[operation('storage.shelf.detach',storage+'.furniture.shelf.00','component_detach',component=child_id(storage+'.furniture.shelf.00','board.top'),rotation=(90,0,10),displacement=(0,-2,0)),
       operation('cabinet.door.detach',storage+'.furniture.cabinet.damage-demo','component_detach',component=child_id(storage+'.furniture.cabinet.damage-demo','door.-1'),rotation=(90,0,0),displacement=(-1,-1,0)),
       operation('chair.leg.fracture',ws+'03','component_fracture',component=child_id(child_id(ws+'03','chair'),'leg.0'),rotation=(70,0,0),displacement=(.5,.4,0))]
    ceiling=child_id('building.main','ceiling')
    # Slab geometry is building-local; this is over the north-west meeting area.
    c=[operation('wall.hole','building.main.wall.north','structural_damage',region=([1.4,-.4,.5],[2.4,.4,2]),parameters=dict(irregularity=.12),displacement=(0,-1,0),rotation=(90,0,0)),
       operation('meeting.ceiling.collapse','building.main','partial_collapse',component=ceiling,region=([-2.5,-1,-.1],[-.7,1,.4]),displacement=(0,0,0)),
       operation('column.notch',meeting+'.column','structural_damage',region=([-.3,-.3,.8],[.05,.3,1.4]),displacement=(.6,0,0),parameters=dict(irregularity=.08))]
    # Controller operations are ordered data. No overlap/repair search loop.
    if label=='A':ops=a
    elif label=='B':ops=b
    elif label=='C':ops=c
    elif label in ('D','E'):
        ops=[a[0],b[0],*c]
        # A slab piece falls at the meeting-room entrance as an intentional barrier.
        op=next(o for o in ops if o['operation_id']=='meeting.ceiling.collapse')
        room=next(n for n in s['nodes'] if n['node_id']==meeting);cx=room['transform']['location'][0];cy=room['transform']['location'][1]-room['parameters']['depth']/2
        # Original cut center (-1,0,3) -> entrance position.
        op['displacement']=[cx+1.6,cy+.3,0]
        if label=='E':
            ops=[o for o in ops if o['operation_id']!='work.shelf.topple']
            op=next(o for o in ops if o['operation_id']=='meeting.ceiling.collapse');op['damage_region']=dict(minimum=[-1.4,-.4,-.1],maximum=[-.6,.4,.4]);op['severity']=.25
    else:raise ValueError('Supported damage acceptance scenes: A..E')
    result=with_damage(s,ops)
    if label=='D':result['damage']['passage_expectations']={meeting:'blocked'}
    return result


def intersection_scene(fractions=(.01,.15,.8),scale=1):
    from .architecture_layout import building_scene
    s=building_scene(8,8,3,1,scene_id='damage-contact-boundaries');rid='building.main.room.01'
    s['interior']=dict(schema_version=1,minimum_passage=.6,rooms=[dict(room_id=rid,purpose='contact_test',requirements=dict(furniture_part=6))],items=[])
    operations=[]
    for i,(y,fraction) in enumerate(zip([-2,0,2],fractions)):
        for suffix,x,surface in [('a',-scale,0),('b',scale,1)]:item(s,f'pair.{i}.{suffix}','furniture_part',rid,(x,y,0),dict(width=scale,depth=.8*scale,height=.6*scale,surface=surface))
        operations.append(operation(f'contact.{i}',f'pair.{i}.a','rigid_displacement',displacement=((1+fraction)*scale,0,0)))
    return with_damage(apply_materials(s),operations)


def clear_damage(spec,operation_ids=None):
    """Restore selected operations or the complete normal authoring specification."""
    s=copy.deepcopy(spec)
    if 'damage' not in s:return s
    if operation_ids is None:s['damage']['operations']=[]
    else:
        requested=set(operation_ids);known={o['operation_id'] for o in s['damage']['operations']}
        if not requested.issubset(known):raise ValueError('Unknown damage operation to clear')
        s['damage']['operations']=[o for o in s['damage']['operations'] if o['operation_id'] not in requested]
    if not s['damage']['operations']:
        controller=s.pop('damage')['controller_node_id'];s['nodes']=[n for n in s['nodes'] if n['node_id']!=controller]
    return s


def member_damage_scene():
    """Additional floor/beam/door coverage beyond representative A..E."""
    s=normal_office();room='building.main.room.02';beam=room+'.beam'
    item(s,beam,'pillar',room,(1.5,0,2.7),dict(width=1.5,depth=.25,height=.3),support=dict(kind='ceiling',node_id=child_id('building.main','ceiling')))
    s['interior']['items'][-1]['semantic_type']='beam';s['interior']['rooms'][1]['requirements']['pillar']=2
    s['appearance']['bindings'].append(dict(node_id=beam,role='geometry',material='concrete',uv=dict(meters_per_repeat=[1,1],rotation_degrees=0)))
    return with_damage(s,[
        operation('floor.hole','building.main','partial_collapse',component=child_id('building.main','floor'),region=([-.8,4.2,-.2],[.8,5.8,.4]),displacement=(1,-5,0)),
        operation('beam.break',beam,'component_fracture',parameters=dict(axis=0),rotation=(0,30,0),displacement=(0,-2,0)),
        operation('door.detach','building.main.door.room02','component_detach',role='leaf',rotation=(90,0,0),displacement=(2,3,0))])
