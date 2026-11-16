"""Furniture contracts use real recipe expansion and independent bounds."""
import copy
import pytest
from scene_factory.compiler import compile_scene
from scene_factory.registry import Registry
from scene_factory.spec import SpecError

FURNITURE=('furniture_part','desk','chair','shelf','cabinet','storage_box','monitor','partition','counter','product_package','bed','light_fixture','workstation','filing_cabinet')
def scene(skill,parameters=None):
    return dict(schema_version=2,scene_id='furniture-test',seed=42,units='m',nodes=[dict(node_id='item',skill=dict(skill_id=skill,version='1.0.0'),parameters=parameters or {},transform={})])
def compile(spec):return compile_scene(spec,allow_candidates=FURNITURE)['build_plan']

@pytest.mark.parametrize('skill',FURNITURE)
def test_furniture_recipe_examples(skill):
    for parameters in Registry().manifests[(skill,'1.0.0')]['examples']:
        plan=compile(scene(skill,parameters));assert plan==compile(copy.deepcopy(scene(skill,parameters)))
        parts=[n for n in plan['nodes'] if n['skill']['skill_id']=='furniture_part']
        assert parts and len({n['node_seed'] for n in parts})==len(parts)
        assert all(a['artifact_id'] for a in plan['expected_artifacts'])
        if skill!='furniture_part':assert all(n['lineage'] for n in parts)

@pytest.mark.parametrize('skill',FURNITURE)
def test_negative_furniture_dimension(skill):
    with pytest.raises(SpecError):compile(scene(skill,dict(width=-1)))

@pytest.mark.parametrize('parameters',[dict(bevel=.1,height=.01),dict(surface=6),dict(width=0),dict(surface=1.1)])
def test_invalid_component(parameters):
    with pytest.raises(SpecError):compile(scene('furniture_part',parameters))


def test_detached_and_intersecting_components():
    from scene_factory.furniture_contracts import assembly
    plan=compile(scene('desk'));nodes={n['node_id']:n for n in plan['nodes']};root=nodes['item']
    part=next(n for n in nodes.values() if n['role_prefix']==['leg.0'])
    part['world_matrix'][0][3]+=10
    with pytest.raises(SpecError,match='detached'):assembly(root,nodes)
    part['world_matrix'][0][3]-=10;part['world_matrix'][2][3]+=.1
    with pytest.raises(SpecError,match='intersect'):assembly(root,nodes)


def test_dimension_edit_preserves_ids_seeds():
    a,b=compile(scene('desk')),compile(scene('desk',dict(width=1.8)))
    assert {n['node_id']:n['node_seed'] for n in a['nodes']}=={n['node_id']:n['node_seed'] for n in b['nodes']}
