"""Pure layout and domain rejection tests; no Blender stand-ins."""
import copy
import pytest
from scene_factory.compiler import compile_scene,child_id
from scene_factory.interior_layout import interior_scene,edit_office,apply_materials
from scene_factory.workflow_store import diff_specs
from scene_factory.spec import SpecError
from scene_factory.quality_profiles import profile


def get(s,ending):return next(n for n in s['nodes'] if n['node_id'].endswith(ending))
def compile(s):return compile_scene(s)['build_plan']

@pytest.mark.parametrize('kind',['living','office','retail','bedroom','kitchen'])
def test_patterns(kind):
    s=interior_scene(kind);p=compile(s);assert p==compile(copy.deepcopy(s))
    assert p['interior_metadata']['state']=='passed'
    assert all(i['initial_state']=='normal' and i['component_ids'] for i in p['interior_metadata']['items'])
    assert len(p['nodes'])<350


def test_edit_preserves_unrelated_nodes_and_seed_identity():
    a=interior_scene();b=edit_office(a);pa,pb=compile(a),compile(b)
    diff=diff_specs(a,b);assert len(diff['removed_nodes'])==2 and len(diff['added_nodes'])==1 and not diff['changed_nodes']
    na,nb=[{n['node_id']:n for n in p['nodes']} for p in (pa,pb)]
    assert all(na[k]==nb[k] for k in na.keys() & nb.keys())
    assert [r['requirements'].get('workstation') for r in b['interior']['rooms']][0]==4

@pytest.mark.parametrize('case',['negative','outside','overlap','door','passage','floating','attachment','facing','state','count','clearance','untracked','wall_alignment','missing_node','duplicate','unsupported_scale'])
def test_invalid_interior(case):
    s=interior_scene('living');chair=get(s,'chair.left');table=get(s,'table');decl=s['interior']['items'][0]
    if case=='negative':chair['parameters']['height']=-1
    elif case=='outside':chair['transform']['location'][0]=10
    elif case=='overlap':chair['transform']['location']=[0,1,0]
    elif case=='door':chair['transform']['location']=[0,-3.2,0]
    elif case=='passage':s['interior']['minimum_passage']=1.2
    elif case=='floating':chair['transform']['location'][2]=.1
    elif case=='attachment':next(i for i in s['interior']['items'] if i['support']['kind']=='on_top')['support']['node_id']=child_id(table['node_id'],'leg.0')
    elif case=='facing':chair['transform']['rotation_degrees'][2]=45
    elif case=='state':decl['initial_state']='fallen'
    elif case=='count':s['interior']['rooms'][0]['requirements']['chair']=3
    elif case=='clearance':decl['placement']['minimum_clearance']=-1
    elif case=='untracked':s['interior']['items'].pop(0)
    elif case=='wall_alignment':get(s,'shelf')['transform']['location'][1]-=.1
    elif case=='missing_node':decl['node_id']='missing'
    elif case=='duplicate':s['interior']['items'].append(copy.deepcopy(decl))
    else:chair['transform']['scale']=[2,1,1]
    with pytest.raises((SpecError,ValueError)):compile(s)


def test_interiors_use_exact_pbr_refs_and_stable_component_targets():
    from scene_factory.resources import resolve_resources
    s=apply_materials(interior_scene('living'));p=compile_scene(s,resources=resolve_resources(s))['build_plan']
    parts=[n for n in p['nodes'] if n['skill']['skill_id']=='furniture_part']
    assert len(parts)==len([b for b in s['appearance']['bindings'] if b['role']=='geometry' and b['node_id'] in {n['node_id'] for n in parts}])
    bad=copy.deepcopy(s);bad['appearance']['materials']['wood']['content_hash']='0'*64
    with pytest.raises((SpecError,ValueError)):compile_scene(bad,resources=resolve_resources(bad))


def test_profiles_keep_old_meanings():
    assert profile('interior')['required_stages']==profile('appearance')['required_stages']
    assert 'furniture' in profile('interior')['scope']
    assert 'furniture' not in profile('appearance')['scope']


def test_two_dimensional_passage_detects_room_partition():
    from scene_factory.architecture_layout import building_scene
    from scene_factory.interior_layout import item
    s=building_scene(6,6,3,1);rid='building.main.room.01'
    s['interior']=dict(schema_version=1,minimum_passage=.8,rooms=[dict(room_id=rid,purpose='storage',requirements=dict(furniture_part=1))],items=[])
    item(s,'barrier','furniture_part',rid,(0,0,0),dict(width=5.4,depth=.2,height=1))
    with pytest.raises(SpecError,match='partitioned'):compile(s)


def test_unvalidated_furniture_cannot_enter_normal_compile(tmp_path):
    import json,shutil
    from scene_factory.registry import Registry,CATALOG
    catalog=tmp_path/'skills';shutil.copytree(CATALOG,catalog)
    path=catalog/'filing_cabinet.skill.json';m=json.loads(path.read_text());m['validation_status']='candidate';m.pop('validation_evidence');path.write_text(json.dumps(m))
    with pytest.raises(SpecError,match='candidate'):
        compile_scene(interior_scene('office'),registry=Registry(catalog))


def test_pbr_office_edit_removes_only_affected_bindings():
    from scene_factory.resources import resolve_resources
    a=apply_materials(interior_scene('office'));b=edit_office(a)
    pa,pb=[compile_scene(s,resources=resolve_resources(s))['build_plan'] for s in [a,b]]
    assert pb['interior_metadata']['state']=='passed'
    na,nb=[{n['node_id'] for n in p['nodes']} for p in [pa,pb]]
    common=na & nb
    assert [x for x in a['appearance']['bindings'] if x['node_id'] in common]==[x for x in b['appearance']['bindings'] if x['node_id'] in common]
    assert a['appearance']['materials']==b['appearance']['materials']
    assert apply_materials(a)==a


def test_untracked_corridor_furniture_is_rejected():
    from scene_factory.architecture_layout import node
    s=interior_scene('office')
    s['nodes'].append(node('corridor.obstacle','desk',{},'building.main.corridor.main'))
    with pytest.raises(SpecError,match='untracked furniture'):compile(s)


def test_non_furniture_mesh_cannot_bypass_occupancy_declarations():
    from scene_factory.architecture_layout import node
    s=interior_scene('office');s['nodes'].append(node('undeclared.prop','box_building',{},'building.main.corridor.main'))
    with pytest.raises(SpecError,match='untracked furniture'):compile(s)


def test_south_wall_strip_is_not_a_passage():
    from scene_factory.architecture_layout import building_scene
    from scene_factory.interior_layout import item
    # A north/south barrier stops 0.65m short of the south wall. The remaining
    # gap cannot be traversed by the required 0.8m passage.
    s=building_scene(8,8,3,1);rid='building.main.room.01'
    s['interior']=dict(schema_version=1,minimum_passage=.8,rooms=[dict(room_id=rid,purpose='storage',requirements=dict(furniture_part=1))],items=[])
    item(s,'barrier','furniture_part',rid,(1,.225,0),dict(width=.1,depth=6.75,height=1))
    with pytest.raises(SpecError,match='partitioned'):compile(s)
