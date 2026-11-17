"""Bpy-free effect contracts, deterministic plans and resource budgets."""
import copy
import pytest
from scene_factory.effect_layout import prepare_materials,with_effects,debris,surface,region,acceptance_scene
from scene_factory.interior_layout import interior_scene,apply_materials
from scene_factory.effect_contracts import validate,sample
from scene_factory.compiler import compile_scene
from scene_factory.resources import resolve_resources
from scene_factory.spec import SpecError

CANDIDATES=['debris_fragment','disaster_processor','damage_processor','asset_instance']
def small():
    s=prepare_materials(apply_materials(interior_scene('living')));rid='building.main.room.01'
    return with_effects(s,[debris('chips','earthquake',rid+'.furniture.shelf',region(rid,[-3,-3,0],[3,3,1]),count=12,distribution='uniform')])
def compile(s):return compile_scene(s,resources=resolve_resources(s),allow_candidates=CANDIDATES)['build_plan']

@pytest.mark.parametrize('label',list('ABCDEF'))
def test_scenarios_compile(label):
    p=compile(acceptance_scene(label));assert p['effects'] and p['effects_baseline_plan']
    assert len(p['nodes'])<=1000

@pytest.mark.parametrize('case',['source','room','count','density','extent','severity','size','seed','material','duplicate','distribution','direction','budget','outside','kind'])
def test_effect_rejections(case):
    s=small();e=s['effects']['items'][0];p=e['parameters']
    if case=='source':e['target_node_id']='absent'
    elif case=='room':e['region']['room_id']='absent'
    elif case=='count':p['fragment_count']=100000
    elif case=='density':p['density']=-1
    elif case=='extent':p['extent'][0]=-1
    elif case=='severity':e['severity']=2
    elif case=='size':p['size_min'][2]=0
    elif case=='seed':e['seed']=-1
    elif case=='material':s['appearance']['materials']['effect.concrete']['content_hash']='0'*64
    elif case=='duplicate':s['effects']['items'].append(copy.deepcopy(e))
    elif case=='distribution':p['distribution']='fluid_simulation'
    elif case=='direction':p['distribution']='directional';p['direction']=[0,0,0]
    elif case=='budget':p['volume_budget']=.000001
    elif case=='outside':e['region']['maximum'][0]=50
    else:p['material_type']='unregistered'
    with pytest.raises((ValueError,SpecError)):compile(s)


def test_edit_reuses_baseline_identity_and_preserves_fragment_ids_geometry():
    a=small();b=copy.deepcopy(a);b['effects']['items'][0]['parameters']['fragment_count']=6
    pa,pb=compile(a),compile(b)
    assert pa['effects_baseline_plan']==pb['effects_baseline_plan']
    roots=set(pb['effects']['items'][0]['generated_root_ids']);aa={n['node_id']:n for n in pa['nodes']}
    assert all(aa[n['node_id']]==n for n in pb['nodes'] if n['node_id'] in roots)
    assert pa==compile(copy.deepcopy(a))

@pytest.mark.parametrize('distribution',['uniform','clustered','source_based','directional'])
def test_distribution_reproducibility_and_bounds(distribution):
    e=small()['effects']['items'][0];e['parameters']['distribution']=distribution
    a=[sample(42,e,i,[0,0,0],.2) for i in range(30)]
    assert a==[sample(42,e,i,[0,0,0],.2) for i in range(30)]
    assert len(set(map(tuple,a)))>20
    assert all(-2.8<=x<=2.8 and -2.8<=y<=2.8 for x,y in a)


def test_surface_conflict_and_waterline_range():
    s=small();r=s['effects']['items'][0]['region'];rid=r['room_id']
    e=surface('water','flood',rid,['building.main.wall.north'],r,'waterline')
    other=copy.deepcopy(e);other['effect_id']='water.duplicate';s['effects']['items']=[e,other]
    with pytest.raises(SpecError,match='material layers'):compile(s)
    s['effects']['items']=[e];e['parameters']['height']=4
    with pytest.raises(SpecError,match='waterline'):compile(s)

@pytest.mark.parametrize('case',['operation','settle','total','existing','repeat_existing','surface_direction','crack_region'])
def test_extended_effect_contract_rejections(case):
    s=small();e=s['effects']['items'][0];p=e['parameters']
    if case=='operation':e['source_operation_id']='absent'
    elif case=='settle':p['settle_fraction']=.99
    elif case=='total':
        for i in range(4):
            other=copy.deepcopy(e);other['effect_id']='many.'+str(i);other['parameters']['fragment_count']=200;s['effects']['items'].append(other)
    elif case=='existing':p['existing_ids']=['absent']
    elif case=='repeat_existing':
        p['existing_ids']=[e['target_node_id']];other=copy.deepcopy(e);other['effect_id']='again';s['effects']['items'].append(other)
    elif case=='surface_direction':
        e=surface('fine','earthquake',e['target_node_id'],['building.main.wall.north'],e['region'],'fine_crack',material='effect.crack');e['parameters']['direction']=[0,0,0];s['effects']['items']=[e]
    else:
        e['effect_type']='crack_geometry';e['parameters']=dict(target_component_id=e['target_node_id'],target_role='geometry',minimum=[0,0,0],maximum=[0,1,1],displacement=[0,0,0])
    with pytest.raises((ValueError,SpecError)):compile(s)


def test_unvalidated_processor_cannot_execute_and_removal_restores_source():
    from scene_factory.registry import Registry
    registry=Registry();registry.manifests[('disaster_processor','1.0.0')]['validation_status']='candidate'
    s=small()
    with pytest.raises(ValueError):compile_scene(s,registry,resources=resolve_resources(s))
    baseline=compile(s)['effects_baseline_plan']
    s.pop('effects');s['nodes']=[n for n in s['nodes'] if n['node_id']!='effects.controller']
    plain=compile(s)
    assert baseline['nodes']==plain['nodes'] and baseline['expected_artifacts']==plain['expected_artifacts']
