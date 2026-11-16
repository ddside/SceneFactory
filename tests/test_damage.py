"""Pure damage schema and scale-aware policy, never a substitute for bpy tests."""
import copy
import pytest
from scene_factory.damage_contracts import validate,classify_intersection
from scene_factory.spec import SpecError


def damage():
    return dict(schema_version=1,controller_node_id='damage.controller',operations=[dict(operation_id='move',target_node_id='chair',damage_type='object_topple',severity=.5,seed=42,displacement=[0,0,0],rotation_degrees=[90,0,0],pivot=[0,0,0],support=dict(kind='floor',ground=True),parameters={})])


def test_damage_schema_preserves_input():
    d=damage();assert validate(d)==d and validate(d) is not d

@pytest.mark.parametrize('case',['severity','seed','type','vector','support','region','duplicate','rigid_region','unknown'])
def test_damage_rejections(case):
    d=damage();o=d['operations'][0]
    if case=='severity':o['severity']=2
    elif case=='seed':o['seed']=-1
    elif case=='type':o['damage_type']='earthquake_simulation'
    elif case=='vector':o['pivot']=[0,0,float('nan')]
    elif case=='support':o['support']=dict(kind='retained',ground=True)
    elif case=='region':o['damage_type']='partial_collapse';o['damage_region']=dict(minimum=[0,0,0],maximum=[1,1,0])
    elif case=='duplicate':d['operations'].append(copy.deepcopy(o))
    elif case=='rigid_region':o['damage_region']=dict(minimum=[0,0,0],maximum=[1,1,1])
    else:o['surprise']=True
    with pytest.raises(SpecError):validate(d)

@pytest.mark.parametrize('scale',[.01,1,10])
def test_scale_aware_pass_warning_fail(scale):
    assert [classify_intersection(v*scale**3,scale**3,scale**3,scale) for v in [.01,.15,.8]]==(['WARNING','WARNING','FAIL'] if scale==100 else ['PASS','WARNING','FAIL'])


def test_semantic_and_contact_intent_affect_policy():
    assert classify_intersection(.3,1,1,1,'floor')=='FAIL'
    assert classify_intersection(.3,1,1,1,'furniture',True)=='WARNING'


def test_damage_compile_resolution_and_normal_baseline():
    from scene_factory.damage_layout import acceptance_scene
    from scene_factory.compiler import compile_scene
    from scene_factory.resources import resolve_resources
    spec=acceptance_scene('B');p=compile_scene(spec,allow_candidates=['damage_processor'],resources=resolve_resources(spec))['build_plan']
    assert len(p['damage']['fragments'])==1 and len(p['damage']['operations'])==3
    assert 'damage' not in p['baseline_plan']
    base={a['artifact_id'] for a in p['baseline_plan']['expected_artifacts']}
    assert base.issubset({a['artifact_id'] for a in p['expected_artifacts']})
    assert p==compile_scene(copy.deepcopy(spec),allow_candidates=['damage_processor'],resources=resolve_resources(spec))['build_plan']

@pytest.mark.parametrize('case',['node','component','role','conflict','support','whole_recipe'])
def test_resolved_target_rejections(case):
    from scene_factory.damage_layout import acceptance_scene
    from scene_factory.compiler import compile_scene
    from scene_factory.resources import resolve_resources
    s=acceptance_scene('B');o=s['damage']['operations'][0]
    if case=='node':o['target_node_id']='missing'
    elif case=='component':o['target_component_id']='missing'
    elif case=='role':o['target_role']='missing'
    elif case=='conflict':other=copy.deepcopy(o);other['operation_id']='conflict';s['damage']['operations'].append(other)
    elif case=='support':o['support']['node_id']='building.main.room.01'
    else:o.pop('target_component_id')
    with pytest.raises(SpecError):compile_scene(s,allow_candidates=['damage_processor'],resources=resolve_resources(s))


def test_undamaged_specs_and_profile_semantics_unchanged():
    from scene_factory.quality_profiles import profile
    assert 'upright' not in profile('damaged_interior')['scope']
    assert 'Normal-state' in profile('interior')['scope']
    assert profile('damaged_interior')['required_stages']==profile('interior')['required_stages']


def test_damage_clear_restores_the_normal_spec_without_geometry_edits():
    from scene_factory.damage_layout import normal_office,acceptance_scene,clear_damage
    assert clear_damage(acceptance_scene('D'))==normal_office()
    partial=clear_damage(acceptance_scene('D'),['work.shelf.topple'])
    assert all(o['operation_id']!='work.shelf.topple' for o in partial['damage']['operations'])
    with pytest.raises(ValueError):clear_damage(partial,['missing'])


def test_floor_beam_door_targets_and_competing_ancestor_operations():
    from scene_factory.damage_layout import member_damage_scene
    from scene_factory.resources import resolve_resources
    from scene_factory.compiler import compile_scene
    s=member_damage_scene();p=compile_scene(s,allow_candidates=['damage_processor'],resources=resolve_resources(s))['build_plan']
    assert len(p['damage']['fragments'])==2
    op=copy.deepcopy(s['damage']['operations'][0]);op['operation_id']='overlapping';op.pop('target_component_id')
    s['damage']['operations'].append(op)
    with pytest.raises(SpecError):compile_scene(s,allow_candidates=['damage_processor'],resources=resolve_resources(s))


def test_absolute_contact_budget_bounds_large_objects():
    assert classify_intersection(.01*100**3,100**3,100**3,100)=='WARNING'


def test_passage_intent_must_reference_a_real_space():
    from scene_factory.damage_layout import acceptance_scene
    from scene_factory.compiler import compile_scene
    from scene_factory.resources import resolve_resources
    s=acceptance_scene('D');s['damage']['passage_expectations']={'missing.space':'blocked'}
    with pytest.raises(SpecError):compile_scene(s,allow_candidates=['damage_processor'],resources=resolve_resources(s))
    d=damage();d['passage_expectations']={'room':'flying'}
    with pytest.raises(SpecError):validate(d)
