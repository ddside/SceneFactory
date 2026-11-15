import copy
from pathlib import Path

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.intent import effective_constraints, validate_intent, verify_references
from scene_factory.workflow import start,resume_context
from scene_factory.workflow_store import load_intent,read_state
from scene_factory.spec import SpecError
from workflow_fixtures import fake_blender,png_bytes,proposal

OPTS={**DEFAULTS,'resolution':64,'samples':1}


@pytest.fixture
def unit_backend(monkeypatch): monkeypatch.setattr('scene_factory.project.run_blender',fake_blender)


def test_raw_request_observations_assumptions_constraints_and_questions(tmp_path,unit_backend):
    image=tmp_path/'ref.png'; image.write_bytes(png_bytes(64))
    value=proposal(); value['reference_files']=[{'reference_id':'ref1','source_path':str(image),
        'inspection':{'state':'viewed','method':'synthetic unit fixture','notes':'Schema test only'}}]
    value['observations']=[{'text':'Observed example shape (synthetic fixture)','reference_ids':['ref1']}]
    value['assumptions']=[{'text':'Dimensions inferred, not visible measurements','reference_ids':['ref1'],'confidence':.5}]
    value['unresolved_questions']=[{'text':'Invisible interior unknown','blocking':False}]
    project=tmp_path/'example'; result=start(project,value,'synthetic',OPTS)
    intent=result['latest_intent']
    assert intent['raw_request']==value['raw_request']
    assert intent['observations']!=intent['assumptions']
    assert intent['unresolved_questions'][0]['blocking'] is False
    assert verify_references(project,intent)==intent
    assert not Path(intent['reference_files'][0]['relative_path']).is_absolute()
    assert result['accepted']['integrity']=='passed'


@pytest.mark.parametrize('mutation',['missing','modified'])
def test_reference_integrity(tmp_path,unit_backend,mutation):
    image=tmp_path/'ref.png'; image.write_bytes(png_bytes(64))
    value=proposal(); value['reference_files']=[{'reference_id':'ref1','source_path':str(image),
        'inspection':{'state':'viewed','method':'synthetic fixture','notes':'No actual vision claim'}}]
    project=tmp_path/'example'; result=start(project,value,'synthetic',OPTS)
    intent=result['latest_intent']; path=project/intent['reference_files'][0]['relative_path']
    if mutation=='missing': path.unlink()
    else: path.write_bytes(b'changed')
    with pytest.raises(SpecError,match='missing or modified'): load_intent(project,intent['intent_id'])
    context=resume_context(project)
    assert context['latest_intent']['integrity']=='failed' and context['accepted']['integrity']=='failed'


@pytest.mark.parametrize('mutation',['schema','unknown','budget','confidence','unknown_type','bad_source','unknown_reference','unviewed_observation','bad_target'])
def test_intent_schema_rejects_invalid(tmp_path,unit_backend,mutation):
    result=start(tmp_path/'example',proposal(),'synthetic',OPTS)
    intent=copy.deepcopy(result['latest_intent'])
    if mutation=='schema': intent['schema_version']=2
    elif mutation=='unknown': intent['arbitrary']=1
    elif mutation=='budget': intent['generation_budget']['max_attempts']=True
    elif mutation=='confidence': intent['constraints'][0]['confidence']=2
    elif mutation=='unknown_type': intent['constraints'][0]['type']='arbitrary_code'
    elif mutation=='bad_source': intent['constraints'][0]['source']['kind']='guess'
    elif mutation=='unknown_reference': intent['assumptions'][0]['reference_ids']=['missing']
    elif mutation=='unviewed_observation': intent['observations']=[{'text':'Not actually observed','reference_ids':[]}]
    elif mutation=='bad_target': intent['constraints'][0]['target_role']='invalid'
    with pytest.raises(SpecError): validate_intent(intent)


def test_explicit_user_constraint_overrides_inference(tmp_path,unit_backend):
    value=proposal(); inferred=copy.deepcopy(value['constraints'][2])
    inferred.update(constraint_id='height.guess',expected_value=6,source={'kind':'assumption','detail':'Uncertain estimate'},confidence=.3)
    value['constraints'].append(inferred)
    result=start(tmp_path/'example',value,'synthetic',OPTS)
    quality=result['quality_runs'][-1]
    assert quality['overridden_inferred_constraints']==['height.guess'] and quality['acceptance']=='eligible'


def test_conflicting_hard_constraints_stop_before_execution(tmp_path,unit_backend):
    value=proposal(); other=copy.deepcopy(value['constraints'][2]); other.update(constraint_id='height.other',expected_value=7)
    value['constraints'].append(other)
    result=start(tmp_path/'example',value,'synthetic',OPTS)
    assert not result['build_attempts'] and result['accepted'] is None
    assert result['active_workflow']['status']=='needs_input'


@pytest.mark.parametrize('field',['unresolved_questions','unsupported_requests'])
def test_blocking_items_preserved(tmp_path,unit_backend,field):
    value=proposal(); value[field]=[{'text':'Cannot satisfy requested unsupported feature','blocking':True}]
    result=start(tmp_path/'example',value,'synthetic',OPTS)
    assert result['latest_intent'][field]==value[field]
    assert result['active_workflow']['status']=='needs_input' and not result['accepted']


def test_soft_constraint_does_not_become_fake_pass(tmp_path,unit_backend):
    value=proposal(); soft=copy.deepcopy(value['constraints'][2]); soft.update(constraint_id='height.soft',strength='soft',expected_value=10)
    value['constraints'].append(soft)
    result=start(tmp_path/'example',value,'synthetic',OPTS)
    assert result['accepted'] is not None
    check=next(c for c in result['quality_runs'][-1]['constraint_checks'] if c['constraint_id']=='height.soft')
    assert check['state']=='failed'
