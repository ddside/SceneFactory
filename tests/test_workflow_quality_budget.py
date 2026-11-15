import copy
import time

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.quality import validate_report
from scene_factory.workflow import start,submit_review,repair,resume_context
from scene_factory.workflow_store import read_state
from workflow_fixtures import fake_blender,proposal,visual_fixture

OPTS={**DEFAULTS,'resolution':64,'samples':1}


@pytest.fixture
def backend(monkeypatch): monkeypatch.setattr('scene_factory.project.run_blender',fake_blender)


def floating_proposal():
    value=proposal()
    pillar=next(n for n in value['scene_spec']['nodes'] if n['node_id']=='pillar.01')
    pillar.pop('parent_id',None); pillar['transform']['location'][2]=2
    return value


def test_automatic_grounding_repair_new_revision_and_bounded_attempts(tmp_path,backend):
    result=start(tmp_path/'example',floating_proposal(),'synthetic',OPTS)
    assert len(result['build_attempts'])==2
    assert result['working_revision']['origin']=='repair'
    assert result['accepted'] is not None
    bad=result['quality_runs'][0]
    assert bad['findings'][0]['node_id']=='pillar.01' and bad['acceptance']=='not_eligible'
    assert next(n for n in result['scene_spec']['nodes'] if n['node_id']=='pillar.01')['transform']['location'][2]==0


def test_attempt_limit_does_not_refresh_on_resume(tmp_path,backend):
    value=floating_proposal(); value['generation_budget']['max_attempts']=1
    project=tmp_path/'example'; result=start(project,value,'synthetic',OPTS)
    assert len(result['build_attempts'])==1 and result['accepted'] is None
    assert result['active_workflow']['status']=='stopped' and 'Maximum' in result['active_workflow']['stop_reason']
    with pytest.raises(ValueError): repair(project,{'scene_spec':result['scene_spec'],'change_summary':'try again'},'synthetic',OPTS)


def test_no_improvement_stops_and_protects_previous_accepted(tmp_path,backend,monkeypatch):
    project=tmp_path/'example'; accepted=start(project,proposal(),'synthetic',OPTS)['accepted']['acceptance_id']
    def ineffective(quality,spec,artifacts):
        result=copy.deepcopy(spec)
        next(n for n in result['nodes'] if n['node_id']=='ground.main')['parameters']['width']+=1
        return {'scene_spec':result,'change_summary':'Synthetic ineffective repair for stop-condition test'}
    monkeypatch.setattr('scene_factory.workflow.propose_repair',ineffective)
    result=start(project,floating_proposal(),'synthetic',OPTS,True)
    assert result['active_workflow']['status']=='stopped' and 'No improvement' in result['active_workflow']['stop_reason']
    assert read_state(project)['accepted']==accepted
    assert len([a for a in result['build_attempts'] if a['workflow_id']==result['active_workflow']['workflow_id']])==2


@pytest.mark.parametrize('limit',['time','nodes'])
def test_resource_budget_stops_before_blender(tmp_path,backend,monkeypatch,limit):
    value=proposal()
    if limit=='nodes': value['generation_budget']['max_nodes']=1
    if limit=='time':
        from datetime import datetime,timezone
        fixed=datetime.now(timezone.utc).timestamp()+10000
        monkeypatch.setattr('scene_factory.workflow.time.time',lambda:fixed)
    result=start(tmp_path/'example',value,'synthetic',OPTS)
    assert result['active_workflow']['status']=='stopped' and not result['build_attempts']


def test_visual_is_not_inferred_from_png_generation(tmp_path,backend):
    result=start(tmp_path/'example',proposal('basic_scene'),'synthetic',OPTS)
    assert result['accepted'] is None and result['active_workflow']['status']=='awaiting_review'
    quality=result['quality_runs'][-1]
    assert quality['stages']['visual']['state']=='not_run'
    assert quality['stages']['domain']['state']=='passed'
    false=copy.deepcopy(quality); false['acceptance']='eligible'
    with pytest.raises(ValueError): validate_report(false)


@pytest.mark.parametrize('mutation',['not_viewed','hash','attempt','missing_check'])
def test_visual_review_bound_to_actual_attempt_and_images(tmp_path,backend,mutation):
    project=tmp_path/'example'; result=start(project,proposal('preview_reviewed'),'synthetic',OPTS)
    review=visual_fixture(result['build_attempts'][-1])
    if mutation=='not_viewed': review['viewed']=False
    elif mutation=='hash': review['images'][0]['sha256']='a'*64
    elif mutation=='attempt': review['attempt_id']='attempt.'+'0'*32
    else: review['checks'].pop('request_conformance')
    with pytest.raises(ValueError): submit_review(project,review)
    assert read_state(project)['accepted'] is None


def test_review_adds_quality_run_without_mutating_revision(tmp_path,backend):
    project=tmp_path/'example'; result=start(project,proposal('preview_reviewed'),'synthetic',OPTS)
    rid=result['working_revision']['revision_id']; sha=result['working_revision']['scene_spec_hash']
    reviewed=submit_review(project,visual_fixture(result['build_attempts'][-1]))
    assert reviewed['accepted']['revision_id']==rid
    resumed=resume_context(project)
    assert resumed['working_revision']['scene_spec_hash']==sha
    assert len(resumed['build_attempts'])==1 and len(resumed['quality_runs'])==2
    assert resumed['quality_runs'][0]['stages']['visual']['state']=='not_run'
    assert resumed['quality_runs'][1]['stages']['visual']['state']=='passed'


def test_stale_review_cannot_publish_new_revision(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal('preview_reviewed'),'synthetic',OPTS)
    old=visual_fixture(first['build_attempts'][-1]); edit=proposal('preview_reviewed')
    start(project,edit,'synthetic',OPTS,True)
    with pytest.raises(ValueError,match='Stale'): submit_review(project,old)
