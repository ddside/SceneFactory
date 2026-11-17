"""Codex authoring helpers for reusable disaster-effect intents."""
import copy
from .architecture_layout import node
from .library import builtins,mat_ref,material_record,Catalog


def prepare_materials(spec,catalog=None):
    s=copy.deepcopy(spec);catalog=catalog or Catalog()
    s.setdefault('appearance',dict(schema_version=1,materials={},bindings=[]))
    for name in ['concrete','plaster','wood','glass','metal']:
        s['appearance']['materials']['effect.'+name]=mat_ref(builtins()[name])
    for name,color,roughness in [('soot',[.018,.016,.014,1],.95),('scorch',[.1,.035,.012,1],.9),('char',[.028,.018,.01,1],.96),('heat',[.32,.16,.05,1],.8),('mud',[.15,.075,.025,1],.78),('waterline',[.23,.18,.09,1],.8),('wet',[.24,.2,.13,1],.12),('crack',[.035,.03,.025,1],.9)]:
        record=material_record('effect.'+name,'effect',dict(base_color=color,roughness=roughness))
        s['appearance']['materials']['effect.'+name]=catalog.put_material(record)
    return s


def with_effects(spec,items):
    s=copy.deepcopy(spec)
    if not any(n['node_id']=='effects.controller' for n in s['nodes']):s['nodes'].append(node('effects.controller','disaster_processor',{}))
    s['effects']=dict(schema_version=1,controller_node_id='effects.controller',items=copy.deepcopy(items));return s


def region(room,lo,hi):return dict(room_id=room,minimum=list(lo),maximum=list(hi))


def debris(eid,disaster,target,area,kind='concrete',count=12,size_min=(.08,.06,.04),size_max=(.2,.14,.1),distribution='source_based',source=None,material=None,seed=42):
    e=dict(effect_id=eid,disaster_type=disaster,effect_type='debris',target_node_id=target,region=area,severity=.7,seed=seed,material=material or 'effect.'+kind,parameters=dict(fragment_count=count,density=1,size_min=list(size_min),size_max=list(size_max),extent=[2,2,1],direction=[1,0,0],distribution=distribution,material_type=kind,irregularity=.25,variants=4,volume_budget=.5,existing_ids=[],scatter_skill='product_package'))
    if source:e['source_operation_id']=source
    return e


def surface(eid,disaster,target,targets,area,kind='soot',layer=1,height=1,material=None,seed=42):
    return dict(effect_id=eid,disaster_type=disaster,effect_type='surface',target_node_id=target,region=area,severity=.9,seed=seed,material=material or 'effect.'+kind,parameters=dict(surface_type=kind,layer=layer,targets=list(targets),band_width=.07,height=height,direction=[1,.35,0]))


def _room_area(spec,rid,height=3):
    room=next(n for n in spec['nodes'] if n['node_id']==rid);w,d=room['parameters']['width'],room['parameters']['depth']
    return region(rid,[-w/2,-d/2,0],[w/2,d/2,height])


def _flood(spec,rid,target):
    from .compiler import child_id
    full=_room_area(spec,rid);w=full['maximum'][0];d=full['maximum'][1]
    walls=[n['node_id'] for n in spec['nodes'] if n['skill']['skill_id']=='arch_wall']
    floor=child_id('building.main','floor')
    effects=[surface('flood.waterline.'+rid,'flood',target,walls,full,'waterline',2,1),surface('flood.mud.'+rid,'flood',target,[floor,*walls],full,'mud',1,1),surface('flood.wet.'+rid,'flood',target,[floor,*walls],full,'wet',3,1)]
    mud=debris('flood.deposit.'+rid,'flood',target,region(rid,[-w+.15,-d+.3,0],[w-.15,-d/3,.3]),'generic',8,(.35,.2,.03),(.7,.35,.07),'uniform',material='effect.mud');mud['parameters']['volume_budget']=.3;effects.append(mud)
    timber=debris('flood.wood.'+rid,'flood',target,region(rid,[-w+.2,-d+.3,0],[w-.2,d-.3,.8]),'wood',12,(.24,.03,.015),(.4,.05,.03),'directional');timber['parameters']['direction']=[-1,-1,0];timber['parameters']['extent']=[4,4,1];effects.append(timber)
    boxes=debris('flood.boxes.'+rid,'flood',target,region(rid,[-w+.2,-d+.3,0],[w-.2,d-.5,.8]),'generic',4,(.2,.15,.12),(.28,.2,.18),'directional',material='effect.wood');boxes['effect_type']='scatter';boxes['parameters']['direction']=[-1,-1,0];boxes['parameters']['extent']=[4,4,1];effects.append(boxes)
    return effects


def _fire(spec,rid,target):
    from .compiler import child_id
    full=_room_area(spec,rid);structural=[n['node_id'] for n in spec['nodes'] if n['skill']['skill_id']=='arch_wall']+[child_id('building.main','ceiling')]
    out=[surface('fire.soot.'+rid,'fire',target,structural,full,'soot',1,material='effect.soot'),surface('fire.scorch.'+rid,'fire',target,structural,full,'scorch',2),surface('fire.char.'+rid,'fire',target,[target],full,'char',3),surface('fire.heat.'+rid,'fire',target,structural,full,'discoloration',4,material='effect.heat')]
    room=next(n for n in spec['nodes'] if n['node_id']==rid);w,d=room['parameters']['width'],room['parameters']['depth']
    residue=debris('fire.residue.'+rid,'fire',target,region(rid,[-w/2+.15,-1.7,0],[-w/2+2.3,1.7,.45]),'wood',8,(.24,.03,.015),(.36,.05,.03),'source_based',material='effect.char');residue['parameters']['extent']=[2,3,1];out.append(residue)
    return out


def acceptance_scene(label='A',catalog=None):
    from .damage_layout import acceptance_scene as damaged,with_damage,operation
    from .interior_layout import interior_scene,apply_materials
    from .compiler import child_id
    if label in ('A','D','E'):
        s=damaged('D');meeting='building.main.room.02';work='building.main.room.01';store='building.main.room.03'
        s=prepare_materials(s,catalog);area=region(meeting,[-2.65,3.5,0],[2.65,5.75,.8])
        concrete=debris('quake.concrete','earthquake','building.main.wall.north',area,'concrete',16,source='wall.hole')
        plaster=debris('quake.plaster','earthquake','building.main',region(meeting,[-2.7,-2,0],[-.4,.7,.8]),'plaster',20,(.12,.1,.01),(.25,.18,.016),source='meeting.ceiling.collapse')
        glass=debris('quake.glass','earthquake','building.main.wall.north',area,'glass',8,(.08,.06,.003),(.15,.1,.004),source='wall.hole')
        boxes=debris('quake.boxes','earthquake',work+'.furniture.shelf.damage-demo',region(work,[.7,4,0],[2.65,5.75,.8]),'generic',4,(.18,.14,.1),(.26,.19,.16),material='effect.wood');boxes['effect_type']='scatter'
        fine=surface('quake.fine','earthquake','building.main.wall.north',['building.main.wall.north'],_room_area(s,meeting),'fine_crack',0,material='effect.crack')
        effects=[concrete,plaster,glass,boxes,fine]
        if label=='D':
            # Composition fixture, not a claim of co-occurring real disasters.
            effects=[boxes,*_fire(s,meeting,meeting+'.column'),*_flood(s,store,store+'.furniture.cabinet.damage-demo')]
            rubble=debris('quake.work','earthquake',work+'.furniture.shelf.damage-demo',region(work,[.7,3.8,0],[2.65,5.75,.8]),'wood',12,(.24,.03,.015),(.36,.05,.03),source='work.shelf.topple');effects.insert(0,rubble)
        if label=='E':
            for e in effects:
                if e['effect_type']=='debris':
                    e['parameters']['fragment_count']//=2;e['parameters']['distribution']='clustered';e['region']=region(meeting,[-2.65,4.8,0],[2.65,5.75,.8])
        return with_effects(s,effects)
    if label=='B':
        s=apply_materials(interior_scene('retail'));rid='building.main.room.02';target=rid+'.furniture.filing'
        s=with_damage(s,[operation('fire.drawer.detach',target,'component_detach',component=child_id(target,'drawer.0.front'),displacement=(1,-1,0),rotation=(80,0,0))]);s=prepare_materials(s,catalog)
        return with_effects(s,_fire(s,rid,target))
    if label=='C':
        s=apply_materials(interior_scene('living'));rid='building.main.room.01';target=rid+'.furniture.cabinet'
        s=with_damage(s,[operation('flood.chair.move',rid+'.furniture.chair.left','rigid_displacement',displacement=(.3,-.4,0),rotation=(10,0,15))]);s=prepare_materials(s,catalog)
        effects=_flood(s,rid,target);effects[-1]['parameters']['existing_ids']=[rid+'.furniture.small.0']
        return with_effects(s,effects)
    if label=='F':
        from .architecture_layout import building_scene
        s=prepare_materials(apply_materials(building_scene(8,8,3,1)),catalog);rid='building.main.room.01';effects=[]
        s['interior']=dict(schema_version=1,minimum_passage=.8,rooms=[dict(room_id=rid,purpose='contact_test',requirements={'furniture_part':0})],items=[])
        for i,(fraction,y) in enumerate([(.01,-2.4),(.15,0),(.6,2.4)]):
            e=debris('contact.'+str(i),'earthquake',rid,region(rid,[-2,y-.8,0],[2,y+.8,1]),'concrete',8,(.12,.09,.08),(.22,.16,.14),'clustered');e['parameters']['settle_fraction']=fraction;e['parameters']['density']=[1,.75,.5][i];effects.append(e)
        return with_effects(s,effects)
    raise ValueError('Supported effect fixtures A..F')
