import copy
import json
import shutil

import pytest

from scene_factory.registry import CATALOG, Registry
from scene_factory.spec import SpecError, example_spec
from scene_factory.compiler import compile_scene
from scene_factory.skill_testing import unit_test_evidence


def test_catalog_and_discovery():
    r=Registry()
    assert {m["skill_id"] for m in r.search()} == {"ground","box_building","pillar","roof","cylinder","building_recipe",
        "arch_wall","arch_opening","arch_door","arch_window","arch_slab","arch_space","arch_room","arch_corridor","arch_building","asset_instance",
        "furniture_part","desk","chair","shelf","cabinet","storage_box","monitor","partition","counter",
        "product_package","bed","light_fixture","workstation","filing_cabinet","damage_processor","debris_fragment","disaster_processor"}
    assert "building_recipe" in {m["skill_id"] for m in r.search("components")}
    assert r.search("cylinder")[0]["category"] == "primitive"


@pytest.mark.parametrize("case",["unknown_field","unknown_entry","unknown_module","bad_version","bad_status","unknown_type",
    "bad_default","bad_example","bad_artifact","bad_compatibility","duplicate_role","unsupported_expression"])
def test_manifest_rejections(case):
    r=Registry(); m=copy.deepcopy(r.manifests[("cylinder","1.0.0")])
    if case=="unknown_field": m['extra']=1
    elif case=="unknown_entry": m['implementation']='unregistered.generate'
    elif case=="unknown_module":
        r.bindings['bad']={'module':'os','function':'system'}; m['implementation']='bad'
    elif case=="bad_version": m['version']='latest'
    elif case=="bad_status": m['validation_status']='enabled'
    elif case=="unknown_type": m['outputs']['height']['type']='Geometry'
    elif case=="bad_default": m['parameter_schema']['radius']['default']=-1
    elif case=="bad_example": m['examples']=[{'segments':9}]
    elif case=="bad_artifact": m['artifacts'][0]['type']='Instance'
    elif case=="bad_compatibility": m['blender_compatibility']['series']='5.0'
    elif case=="duplicate_role": m['artifacts'].append(copy.deepcopy(m['artifacts'][0]))
    elif case=="unsupported_expression": m['outputs']['height']['value']={'python':'do_something()'}
    with pytest.raises(SpecError): r.check_manifest(m)


@pytest.mark.parametrize("status",['candidate','disabled'])
def test_inactive_skills_cannot_execute(status):
    r=Registry(); r.manifests[('ground','1.0.0')]['validation_status']=status
    source=example_spec(); source['objects']=[o for o in source['objects'] if o['generator']=='ground']
    with pytest.raises(SpecError,match=status): compile_scene(source,r)


def test_stale_validation_evidence_rejected():
    r=Registry(); m=r.manifests[('ground','1.0.0')]
    m['validation_status']='validated'
    m['validation_evidence']={'status':'passed','pin':{},'tests':['fixture'],'unit_tests':{'cases':['fixture']},'runtime':{'os':'fixture'}}
    with pytest.raises(SpecError,match='stale'): r.get('ground','1.0.0')


@pytest.mark.parametrize("case",['cycle','missing_version','recipe_cycle','undeclared_recipe_dependency'])
def test_registry_graph_rejections(tmp_path,case):
    directory=tmp_path/'catalog'; shutil.copytree(CATALOG,directory)
    if case in ('cycle','missing_version'):
        p=directory/'ground.skill.json'; m=json.loads(p.read_text())
        m['dependencies']=[{'skill_id':'roof','version':'1.0.0' if case=='cycle' else '99.0.0'}]; p.write_text(json.dumps(m))
        if case=='cycle':
            p=directory/'roof.skill.json'; m=json.loads(p.read_text()); m['dependencies']=[{'skill_id':'ground','version':'1.0.0'}]; p.write_text(json.dumps(m))
    else:
        p=directory/'building_recipe.skill.json'; m=json.loads(p.read_text())
        if case=='recipe_cycle': m['recipe']['nodes'][0]['depends_on']=['roof']
        else: m['dependencies']=[]
        p.write_text(json.dumps(m))
    with pytest.raises(SpecError): Registry(directory)


def test_activation_requires_passing_unit_report(tmp_path):
    with pytest.raises(ValueError): unit_test_evidence(None)
    report=tmp_path/'report.xml'
    for tag in ('failure','error','skipped'):
        report.write_text(f'<testsuite><testcase name="x"><{tag}/></testcase></testsuite>')
        with pytest.raises(ValueError): unit_test_evidence(report)
    report.write_text('<testsuite><testcase name="skill_contract"/></testsuite>')
    assert unit_test_evidence(report)['case_count']==1
