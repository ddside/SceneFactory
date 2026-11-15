import copy

import pytest

from scene_factory.artifacts import check_manifest, structure_digest
from scene_factory.contract_utils import canonical_digest
from scene_factory.quality import report, validate_report
from scene_factory.runner import RunnerError, check_result
from scene_factory.spec import SpecError


def fixture_manifest():
    a={'artifact_id':'a.test','source_node_id':'source','producer_node_id':'producer','role':'part.geometry','local_role':'geometry',
       'type':'Mesh','lineage':['source'],'dependencies':[], 'reference':{'object':'temporary-name','mesh':'mesh-data'},
       'geometry_digest':'a'*64,'vertex_count':32,'face_count':18,'bounds':[[-1,-1,0],[1,1,2]],
       'local_matrix':[[float(i==j) for j in range(4)] for i in range(4)],
       'world_matrix':[[float(i==j) for j in range(4)] for i in range(4)]}
    return {'schema_version':1,'plan_digest':'b'*64,'artifact_count':1,'artifacts':[a],'node_artifacts':{'source':['a.test']}}


@pytest.mark.parametrize('case',['count','duplicate','mapping','type','geometry','nonfinite','missing_dep','missing_role','missing_artifact','unexpected_artifact','empty_mesh','object_geometry'])
def test_artifact_contract_rejections(case):
    manifest=fixture_manifest()
    expected=[{k:v for k,v in manifest['artifacts'][0].items() if k in
               ('artifact_id','source_node_id','producer_node_id','role','local_role','type','lineage','dependencies')}]
    if case=='count': manifest['artifact_count']=999
    elif case=='duplicate': manifest['artifacts'].append(copy.deepcopy(manifest['artifacts'][0])); manifest['artifact_count']=2
    elif case=='mapping': manifest['node_artifacts']={}
    elif case=='type': manifest['artifacts'][0]['type']='Collection'
    elif case=='geometry': manifest['artifacts'][0]['geometry_digest']='invalid'
    elif case=='nonfinite': manifest['artifacts'][0]['world_matrix'][0][0]=float('inf')
    elif case=='missing_dep': manifest['artifacts'][0]['dependencies']=['a.missing']
    elif case=='missing_role': manifest['artifacts'][0]['role']='wrong'
    elif case=='missing_artifact': manifest.update(artifacts=[],artifact_count=0,node_artifacts={})
    elif case=='unexpected_artifact': expected=[]
    elif case=='empty_mesh': manifest['artifacts'][0]['vertex_count']=0
    elif case=='object_geometry':
        a=manifest['artifacts'][0]; a.update(type='Object',geometry_digest=None); a['reference']['mesh']=None
    with pytest.raises(SpecError): check_manifest(manifest,expected)


def test_ids_do_not_depend_on_blender_names_and_inventory_is_lightweight():
    manifest=fixture_manifest(); before=structure_digest(manifest)
    manifest['artifacts'][0]['reference']={'object':'renamed.001','mesh':'auto-name.009'}
    check_manifest(manifest)
    assert structure_digest(manifest)==before
    assert 'vertices' not in manifest['artifacts'][0] and 'faces' not in manifest['artifacts'][0]


@pytest.mark.parametrize('case',['count','protocol','attempt','digest','artifact_count','artifact_plan','artifact_count_bool'])
def test_worker_result_rejections(case):
    request={'protocol_version':2,'attempt_id':'attempt','plan_digest':'b'*64,'plan_path':'plan.json'}
    value={'ok':True,'action':'build','blender':'4.5.15','blender_hash':'fixture','blender_python':'3.11','protocol_version':2,'attempt_id':'attempt',
        'plan_digest':'b'*64,'structure_sha256':'c'*64,'object_count':1,'objects':[{'artifact_id':'a.test','stable_id':'producer'}],
        'artifact_count':1,'artifact_manifest':fixture_manifest()}
    if case=='count': value['object_count']=999
    elif case=='protocol': value['protocol_version']=1
    elif case=='attempt': value['attempt_id']='wrong'
    elif case=='digest': value['plan_digest']='d'*64
    elif case=='artifact_count': value['artifact_count']=999
    elif case=='artifact_plan': value['artifact_manifest']['plan_digest']='d'*64
    elif case=='artifact_count_bool': value['artifact_count']=True
    with pytest.raises(RunnerError): check_result(value,'build',request)


def test_quality_does_not_promote_structure_to_accepted():
    quality=report(('specification','execution','structure'))
    assert quality['acceptance']=='not_evaluated'
    assert {quality['stages'][k]['state'] for k in ('visual','domain','export','target_compatibility')}=={'not_run'}
    assert report(('specification',),('execution','crash'))['stages']['execution']['state']=='failed'
    quality['stages']['domain'].update(state='not_applicable',reason='explicit profile exclusion')
    validate_report(quality)
    quality['acceptance']='accepted'
    with pytest.raises(SpecError): validate_report(quality)
