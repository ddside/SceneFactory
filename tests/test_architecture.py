"""Pure architectural contract tests; candidate execution is explicit test-only."""
import copy
import pytest
from scene_factory.architecture_layout import building_scene,enlarge_window
from scene_factory.compiler import compile_scene,child_id
from scene_factory.registry import Registry
from scene_factory.spec import SpecError
from scene_factory.workflow_store import diff_specs
from scene_factory.quality_profiles import profile,evaluate

SKILLS=('arch_wall','arch_slab','arch_space','arch_opening','arch_door','arch_window','arch_corridor','arch_room','arch_building')

def compile(spec): return compile_scene(spec,allow_candidates=SKILLS)['build_plan']
def get(spec,nid): return next(n for n in spec['nodes'] if n['node_id']==nid)

@pytest.mark.parametrize('rooms',[1,2,3])
def test_layout_recipe_dimensions_references_and_determinism(rooms):
    spec=building_scene(8 if rooms==1 else 12,6 if rooms==1 else 8,3,rooms)
    plan=compile(spec); assert plan==compile(copy.deepcopy(spec))
    assert len([n for n in plan['nodes'] if n['skill']['skill_id']=='arch_room'])==rooms
    assert len([n for n in plan['nodes'] if n['skill']['skill_id']=='arch_corridor'])==(rooms>1)
    nodes={n['node_id']:n for n in plan['nodes']}
    assert child_id('building.main','floor') in nodes
    assert all(n['typed_outputs']['wall']['value']==[n['parameters']['length'],.2,3] for n in plan['nodes'] if n['skill']['skill_id']=='arch_wall')
    for n in plan['nodes']:
        if n['skill']['skill_id']=='arch_opening':
            assert n['resolved_transform']['location']==n['transform']['location']
            assert n['resolved_inputs']['wall']['target']=='reference'
            assert n['parent_id'] in plan['dependency_dag'][n['node_id']]


def test_window_edit_only_three_nodes_preserves_all_seeds_and_artifact_ids():
    before=building_scene(); after=enlarge_window(before,'building.main.window.room02',1.8,1.4)
    diff=diff_specs(before,after)
    assert set(diff['changed_nodes'])=={'building.main.window.room02','building.main.opening.window.room02','building.main.wall.north'}
    a,b=compile(before),compile(after)
    assert {n['node_id']:n['node_seed'] for n in a['nodes']}=={n['node_id']:n['node_seed'] for n in b['nodes']}
    assert {n['artifact_id'] for n in a['expected_artifacts']}=={n['artifact_id'] for n in b['expected_artifacts']}

@pytest.mark.parametrize('case',['big_window','outside_door','overlap','negative_wall','negative_floor','bad_parent','missing_wallref',
    'fitting_mismatch','unconnected_room','duplicate_id','duplicate_slot','thickness','perimeter','wall_intersection','hidden_space','floating_slab','wrong_type','roof_missing','inward_space'])
def test_invalid_scene_d(case):
    s=building_scene(); wall=get(s,'building.main.wall.north'); opening=get(s,'building.main.opening.window.room02')
    if case=='big_window': s=enlarge_window(s,'building.main.window.room02',20)
    elif case=='outside_door': get(s,'building.main.wall.south')['parameters']['o1_offset']=9
    elif case=='overlap': wall['parameters']['o2_offset']=wall['parameters']['o1_offset']
    elif case=='negative_wall': wall['parameters']['thickness']=-.2
    elif case=='negative_floor': get(s,'building.main')['parameters']['floor_thickness']=-.2
    elif case=='bad_parent': opening['parent_id']='building.main'
    elif case=='missing_wallref': opening['inputs']['wall']['node_id']='missing.wall'
    elif case=='fitting_mismatch': get(s,'building.main.window.room02')['parameters']['width']=2
    elif case=='unconnected_room': get(s,'building.main.room.02')['inputs']['access']['node_id']='building.main.opening.room01'
    elif case=='duplicate_id': s['nodes'].append(copy.deepcopy(s['nodes'][1]))
    elif case=='duplicate_slot': extra=copy.deepcopy(opening); extra['node_id']='duplicate.opening'; s['nodes'].append(extra)
    elif case=='thickness': wall['parameters']['thickness']=.3
    elif case=='perimeter': wall['transform']['location'][1]+=1
    elif case=='wall_intersection': get(s,'building.main.wall.partition01')['transform']['location'][0]=0
    elif case=='hidden_space': get(s,'building.main.room.02')['parameters']['width']=1
    elif case=='floating_slab': get(s,'building.main')['parameters']['ceiling_thickness']=-1
    elif case=='wrong_type': opening['inputs']['wall']={'node_id':'building.main.corridor.main','output':'space'}
    elif case=='roof_missing': get(s,'building.main')['parameters']['roof_thickness']=0
    elif case=='inward_space': get(s,'building.main.room.02')['transform']['location'][1]-=1
    with pytest.raises(SpecError): compile(s)

@pytest.mark.parametrize('case',['no_end_pier','no_header','door_sill','touching_openings','fractional_count','negative_thickness'])
def test_wall_contract_invalid(case):
    p={'opening_count':1};
    if case=='no_end_pier': p['o1_width']=8
    elif case=='no_header': p['o1_height']=3
    elif case=='door_sill': p['o1_sill']=.1
    elif case=='touching_openings': p.update(opening_count=2,o1_offset=-.5,o2_offset=.5)
    elif case=='fractional_count': p['opening_count']=1.5
    else: p['thickness']=-1
    s={'schema_version':2,'scene_id':'wall','seed':1,'units':'m','nodes':[{'node_id':'wall','skill':{'skill_id':'arch_wall','version':'1.0.0'},'parameters':p,'transform':{}}]}
    with pytest.raises(SpecError): compile(s)


def test_architectural_profile_preserves_legacy_profiles():
    assert profile('structural')['required_stages']==['specification','execution','structure']
    assert profile('architectural')['required_stages']==['specification','execution','structure','visual','domain']


def test_manifest_pins_include_pure_contract_and_support(tmp_path,monkeypatch):
    r=Registry(); p=r.pin(r.manifests[('arch_wall','1.0.0')])
    assert p['contract']['module']=='scene_factory.architecture_contracts'
    assert 'architecture_contracts.py' in p['implementation']['support_sha256']
    assert r.manifests[('arch_building','1.0.0')]['kind']=='recipe'
    assert r.manifests[('building_recipe','1.0.0')]['version']=='1.0.0'
    import json,shutil
    import scene_factory.skill_testing as testing
    from scene_factory.registry import CATALOG
    catalog=tmp_path/'catalog'; shutil.copytree(CATALOG,catalog)
    path=catalog/'arch_space.skill.json'; manifest=json.loads(path.read_text())
    manifest['test_scenes']=[{'schema_version':2,'scene_id':'wrong-target','seed':1,'units':'m','nodes':[
        {'node_id':'unrelated','skill':{'skill_id':'ground','version':'1.0.0'},'parameters':{},'transform':{}}]}]
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(testing,'Registry',lambda:Registry(catalog))
    with pytest.raises(ValueError,match='target skill'):
        testing.validate_skill('arch_space','1.0.0','must-not-run',tmp_path/'evidence')

@pytest.mark.parametrize('rooms',[0,4,1.5])
def test_layout_rejects_unsupported_room_counts(rooms):
    with pytest.raises(ValueError): building_scene(rooms=rooms)

@pytest.mark.parametrize('slot',[0,1,2,3])
def test_wall_material_slots_are_explicit(slot):
    s=building_scene(); get(s,'building.main.wall.north')['parameters']['material_slot']=slot
    plan=compile(s); assert next(n for n in plan['nodes'] if n['node_id']=='building.main.wall.north')['parameters']['material_slot']==slot


def test_architectural_domain_evidence_is_required_and_not_visual_evidence():
    from scene_factory.intent import BUDGET,now
    from scene_factory.quality import report
    intent={'schema_version':1,'intent_id':'intent.test','raw_request':'building','reference_files':[],
        'observations':[],'assumptions':[],'constraints':[],'unresolved_questions':[],'unsupported_requests':[],
        'requested_quality_profile':'architectural','generation_budget':BUDGET,'created_at':now()}
    scene=building_scene(); plan=compile(scene); base=report(('specification','execution','structure'))
    args=(intent,scene,plan,{'artifacts':[]},base,'revision.test','attempt.test','quality.test',now(),profile('architectural'))
    missing=evaluate(*args)
    assert missing['stages']['domain']['state']=='not_run' and missing['acceptance']=='not_eligible'
    # Synthetic data here tests the pure policy only, never proves geometry/image review.
    evidence=[{'kind':'architecture','node_id':'building.main','state':'passed'}]
    checked=evaluate(*args,domain_results=evidence)
    assert checked['stages']['domain']['state']=='passed' and checked['stages']['visual']['state']=='not_run'
    assert checked['acceptance']=='not_eligible'
    intent['constraints']=[{'constraint_id':'width','target_node_id':'building.main','type':'parameter_equals',
        'property':'width','expected_value':13,'strength':'hard','source':{'kind':'user','detail':'test'},'confidence':1,'tolerance':0}]
    failed=evaluate(*args,domain_results=evidence)
    assert failed['stages']['domain']['state']=='failed' and failed['acceptance']=='not_eligible'


def test_binding_syntax_cache_uses_exact_source_bytes():
    from scene_factory.registry import defined_functions
    assert defined_functions(b'def first(): pass')=={'first'}
    assert defined_functions(b'def second(): pass')=={'second'}
