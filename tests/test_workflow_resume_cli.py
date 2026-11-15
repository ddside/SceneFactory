import copy
import json
import os
from pathlib import Path

import pytest

from scene_factory.cli import main
from scene_factory.config import DEFAULTS
from scene_factory.storage import recover_stale_lock,write_json
from scene_factory.workflow import start,resume_context,resume
from scene_factory.workflow_store import read_state,commit_state,record_path,load_record,history
from workflow_fixtures import fake_blender,proposal

OPTS={**DEFAULTS,'resolution':64,'samples':1}


@pytest.fixture
def backend(monkeypatch): monkeypatch.setattr('scene_factory.project.run_blender',fake_blender)


def test_resume_interruption_keeps_budget_and_snapshot(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal('preview_reviewed'),'synthetic',OPTS)
    state=read_state(project); wid=state['active_workflow']
    attempt=first['build_attempts'][-1]; attempt['status']='running'
    write_json(record_path(project,'attempt',attempt['attempt_id']),attempt)
    state['workflow_progress'][wid]['status']='running'; commit_state(project,state)
    original_start=first['active_workflow']['started_at']
    second=resume(project,'synthetic',OPTS,True)
    assert second['active_workflow']['started_at']==original_start
    assert second['build_attempts'][0]['status']=='interrupted'
    assert len(second['build_attempts'])==2
    assert second['working_revision']['scene_spec_hash']==first['working_revision']['scene_spec_hash']
    assert second['accepted'] is None


def test_lock_recovery_refuses_active_owner(tmp_path):
    path=tmp_path/'.scene-factory.lock'; path.write_text(str(os.getpid()))
    with pytest.raises(ValueError,match='still exists'): recover_stale_lock(tmp_path)
    assert path.exists()


def test_lock_recovery_only_provably_dead_pid(tmp_path,monkeypatch):
    path=tmp_path/'.scene-factory.lock'; path.write_text('12345')
    def dead(*args): raise ProcessLookupError()
    monkeypatch.setattr('scene_factory.storage.os.kill',dead)
    assert recover_stale_lock(tmp_path) and not path.exists()


def test_cli_history_diff_rollback_and_resume(tmp_path,backend,capsys):
    project=tmp_path/'example'; data=tmp_path/'proposal.json'; write_json(data,proposal())
    # Runtime resolution is independent from the synthetic unit backend.
    assert main(['generate',str(project),'--proposal',str(data),'--blender-path',str(Path(__file__).resolve())])==1
    first=start(project,proposal(),'synthetic',OPTS)
    rid=first['working_revision']['revision_id']
    assert main(['history',str(project)])==0
    assert main(['diff',str(project),'--from',rid,'--to',rid])==0
    assert main(['resume',str(project)])==0
    assert main(['present',str(project)])==0
    assert main(['rollback',str(project),'--revision',rid,'--reason','元の状態に戻して'])==0
    assert main(['status',str(project)])==0
    assert 'accepted' in capsys.readouterr().out


def test_invalid_proposal_is_recorded_without_replacing_accepted(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    invalid=proposal(); invalid['scene_spec']['nodes'][0]['skill']['skill_id']='unregistered'
    with pytest.raises(ValueError): start(project,invalid,'synthetic',OPTS,True)
    after=resume_context(project)
    assert after['accepted']['acceptance_id']==first['accepted']['acceptance_id']
    assert after['latest_operation']['status']=='failed'
    assert history(project)['events'][-1]['action']=='proposal_rejected'


def test_repair_cannot_relax_intent_or_quality_profile(tmp_path,backend):
    from scene_factory.workflow import repair
    project=tmp_path/'example'; first=start(project,proposal('preview_reviewed'),'synthetic',OPTS)
    bad={'scene_spec':first['scene_spec'],'change_summary':'pretend fix','requested_quality_profile':'structural'}
    with pytest.raises(ValueError): repair(project,bad,'synthetic',OPTS)
    assert read_state(project)['accepted'] is None
