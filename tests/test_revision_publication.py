import copy
import json
import subprocess
import sys

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.project import current_spec_path
from scene_factory.publication import check_accepted,rollback
from scene_factory.workflow import start,rebuild,resume_context,resume
from scene_factory.workflow_store import diff_revisions,history,load_record,read_state,revision_spec
from workflow_fixtures import fake_blender,proposal

OPTS={**DEFAULTS,'resolution':64,'samples':1}


@pytest.fixture
def backend(monkeypatch): monkeypatch.setattr('scene_factory.project.run_blender',fake_blender)


def height_edit(context,height=5):
    spec=copy.deepcopy(context['scene_spec'])
    next(n for n in spec['nodes'] if n['node_id']=='building.main')['parameters']['height']=height
    constraint=copy.deepcopy(next(c for c in context['working_intent']['constraints'] if c['constraint_id']=='building.height'))
    constraint['expected_value']=height; constraint['source']['detail']='Explicit subsequent height edit'
    return {'raw_request':f'建物の高さを{height}mにして','scene_spec':spec,'change_summary':'Change only building height','constraints':[constraint]}


def test_revision_snapshot_diff_and_relationships(tmp_path,backend):
    project=tmp_path/'example'; original=start(project,proposal(),'synthetic',OPTS)
    old_id=original['working_revision']['revision_id']; old_bytes=current_spec_path(project).read_bytes()
    updated=start(project,height_edit(original),'synthetic',OPTS,True)
    new_id=updated['working_revision']['revision_id']
    assert new_id!=old_id and updated['working_revision']['parent_revision_id']==old_id
    difference=diff_revisions(project,old_id,new_id)
    assert set(difference['changed_nodes'])=={'building.main'} and not difference['added_nodes'] and not difference['removed_nodes']
    old_record=load_record(project,'revision',old_id)
    assert (project/old_record['scene_spec_snapshot']).read_bytes()==old_bytes
    rows=history(project)['revisions']
    assert rows[0]['status']=='previously_accepted' and rows[0]['related_build_attempts']
    assert rows[1]['quality_run_ids'] and rows[1]['status']=='accepted'


def test_same_revision_multiple_attempts(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    second=rebuild(project,'synthetic',OPTS)
    assert first['working_revision']['revision_id']==second['working_revision']['revision_id']
    assert len(second['build_attempts'])==2
    assert second['build_attempts'][0]['build_id']!=second['build_attempts'][1]['build_id']
    assert len(second['working_revision']['related_build_attempts'])==2


def test_snapshot_mutation_detected(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    current_spec_path(project).write_text('{}')
    with pytest.raises(ValueError,match='modified'): revision_spec(project,first['working_revision']['revision_id'])


def test_rollback_changes_references_without_rebuild(tmp_path,backend,monkeypatch):
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    second=start(project,height_edit(first),'synthetic',OPTS,True)
    old=check_accepted(project,first['accepted']['acceptance_id'])
    before={path:(project/path).read_bytes() for path in old['bundle_sha256']}
    monkeypatch.setattr('scene_factory.project.run_blender',lambda *a,**kw:pytest.fail('Rollback must not invoke Blender'))
    result=rollback(project,first['working_revision']['revision_id'],'元の状態に戻して')
    after=resume_context(project)
    assert after['accepted']['acceptance_id']==first['accepted']['acceptance_id']
    assert after['working_revision']['revision_id']==first['working_revision']['revision_id']
    assert len(after['build_attempts'])==len(second['build_attempts'])
    assert all((project/path).read_bytes()==content for path,content in before.items())
    assert history(project)['events'][-1]['action']=='rollback'
    assert after['working_intent']['intent_id']!=after['latest_intent']['intent_id']


def test_failed_rollback_preserves_current_reference(tmp_path,backend):
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    second=start(project,height_edit(first),'synthetic',OPTS,True)
    (project/'builds'/first['accepted']['build_id']/'scene.blend').write_bytes(b'tampered')
    state_bytes=(project/'state.json').read_bytes()
    with pytest.raises(ValueError): rollback(project,first['working_revision']['revision_id'])
    assert (project/'state.json').read_bytes()==state_bytes
    assert check_accepted(project)['acceptance_id']==second['accepted']['acceptance_id']


def test_atomic_acceptance_failure_preserves_old_and_resume_can_publish(tmp_path,backend,monkeypatch):
    import scene_factory.publication as publication
    project=tmp_path/'example'; first=start(project,proposal(),'synthetic',OPTS)
    previous=first['accepted']['acceptance_id']; commit=publication.commit_state
    def fail_new_acceptance(path,state):
        if state['accepted']!=previous: raise OSError('injected accepted publication IO failure')
        return commit(path,state)
    with monkeypatch.context() as m:
        m.setattr(publication,'commit_state',fail_new_acceptance)
        with pytest.raises(OSError,match='publication'):
            start(project,height_edit(first),'synthetic',OPTS,True)
    assert read_state(project)['accepted']==previous
    assert check_accepted(project)['acceptance_id']==previous
    context=resume_context(project)
    assert context['active_workflow']['status']=='publication_pending'
    count=len(context['build_attempts'])
    result=resume(project,'synthetic',OPTS,True)
    assert result['accepted']['acceptance_id']!=previous
    assert len(result['build_attempts'])==count


def test_separate_process_can_resume_without_chat(tmp_path,backend):
    project=tmp_path/'example'; result=start(project,proposal(),'synthetic',OPTS)
    code='import sys; from pathlib import Path; from scene_factory.workflow import resume_context; c=resume_context(Path(sys.argv[1])); print(c["accepted"]["acceptance_id"])'
    process=subprocess.run([sys.executable,'-c',code,str(project)],capture_output=True,text=True,timeout=10)
    assert process.returncode==0,process.stderr
    assert process.stdout.strip()==result['accepted']['acceptance_id']
