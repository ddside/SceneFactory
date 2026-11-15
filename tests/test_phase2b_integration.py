"""Real Blender E2E. Automatic CI acceptance is structural-scoped, never fake vision.

Actual Codex image reviews are recorded separately in the Phase 2B manual E2E log.
"""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.project import build_at
from scene_factory.publication import check_accepted,rollback
from scene_factory.spec import read_json
from scene_factory.storage import digest,write_json
from scene_factory.workflow import start,rebuild,resume_context,resume
from scene_factory.workflow_store import history,diff_revisions,read_state,load_record,record_path,commit_state
from workflow_fixtures import proposal

ROOT=Path(__file__).resolve().parents[1]
OPTS={**DEFAULTS,'resolution':64,'samples':1}


@pytest.fixture
def real_runtime():
    exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not exe: pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    root=ROOT/'artifacts/test-runs'; root.mkdir(parents=True,exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='phase2b-',dir=root)),exe


def edit(context,request,spec,constraints=()):
    return {'raw_request':request,'scene_spec':spec,'constraints':list(constraints),'change_summary':request}


def test_real_generation_three_edits_diff_rollback_and_rebuild(real_runtime):
    directory,exe=real_runtime; project=directory/'example'
    first=start(project,proposal(),exe,OPTS)
    initial=first['working_revision']['revision_id']; accepted_first=check_accepted(project)
    initial_files={path:digest(project/path) for path in accepted_first['bundle_sha256']}
    first_build,_=build_at(project,accepted_first['build_id'])
    seeds={n['node_id']:n['node_seed'] for n in read_json(first_build/'plan.json')['nodes']}
    spec=copy.deepcopy(first['scene_spec'])
    next(n for n in spec['nodes'] if n['node_id']=='building.main')['parameters']['height']=5
    con=copy.deepcopy(next(c for c in first['working_intent']['constraints'] if c['constraint_id']=='building.height')); con['expected_value']=5
    height=start(project,edit(first,'建物の高さを5mにして',spec,[con]),exe,OPTS,True)
    assert set(diff_revisions(project,initial,height['working_revision']['revision_id'])['changed_nodes'])=={'building.main'}
    spec=copy.deepcopy(height['scene_spec']); spec['nodes']=[n for n in spec['nodes'] if n['node_id'] not in ('pillar.07','pillar.08')]
    con=copy.deepcopy(next(c for c in height['working_intent']['constraints'] if c['constraint_id']=='pillar.count')); con['expected_value']=6
    six=start(project,edit(height,'柱を6本に減らして',spec,[con]),exe,OPTS,True)
    assert len([n for n in six['scene_spec']['nodes'] if n['skill']['skill_id']=='pillar'])==6
    spec=copy.deepcopy(six['scene_spec']); next(n for n in spec['nodes'] if n['node_id']=='building.main')['transform']['location'][0]+=3
    moved=start(project,edit(six,'建物を右に3m移動して',spec),exe,OPTS,True)
    build,_=build_at(project,moved['accepted']['build_id']); plan=read_json(build/'plan.json')
    assert all(n['node_seed']==seeds[n['node_id']] for n in plan['nodes'])
    assert moved['accepted']['integrity']=='passed'
    assert moved['quality_runs'][-1]['stages']['visual']['state']=='not_run'
    assert moved['accepted']['profile']['profile_id']=='structural'
    rollback(project,initial,'元に戻して')
    restored=resume_context(project)
    assert restored['accepted']['acceptance_id']==accepted_first['acceptance_id']
    assert all(digest(project/path)==sha for path,sha in initial_files.items())
    before=len(restored['build_attempts']); again=rebuild(project,exe,OPTS)
    assert len(again['build_attempts'])==before+1 and again['working_revision']['revision_id']==initial
    assert all(digest(project/path)==sha for path,sha in initial_files.items())


def test_real_automatic_repair_and_attempt_limit(real_runtime):
    directory,exe=real_runtime
    data=proposal(); pillar=next(n for n in data['scene_spec']['nodes'] if n['node_id']=='pillar.01')
    pillar.pop('parent_id',None); pillar['transform']['location'][2]=2
    result=start(directory/'repair',data,exe,OPTS)
    assert len(result['build_attempts'])==2 and result['accepted'] is not None
    assert result['working_revision']['origin']=='repair'
    assert result['quality_runs'][0]['constraint_checks'][-1]['state']=='failed'
    capped=copy.deepcopy(data); capped['generation_budget']['max_attempts']=1
    stopped=start(directory/'capped',capped,exe,OPTS)
    assert len(stopped['build_attempts'])==1 and stopped['accepted'] is None
    assert stopped['active_workflow']['status']=='stopped'


def test_real_render_failure_keeps_old_accepted(real_runtime):
    directory,exe=real_runtime; project=directory/'example'
    first=start(project,proposal(),exe,OPTS); accepted=check_accepted(project)
    spec=copy.deepcopy(first['scene_spec'])
    next(n for n in spec['nodes'] if n['node_id']=='building.main')['transform']['location'][0]=1
    # Deliberate backend fault injection through the real Blender worker.
    failed=start(project,edit(first,'move for failure test',spec),exe,{**OPTS,'device':'unsupported-test-device'},True)
    assert failed['accepted']['acceptance_id']==accepted['acceptance_id']
    assert failed['build_attempts'][-1]['status']=='failed'
    assert failed['build_attempts'][-1]['error']
    assert check_accepted(project)['acceptance_id']==accepted['acceptance_id']


def test_real_preview_required_does_not_autoaccept_and_resumes_in_new_process(real_runtime):
    directory,exe=real_runtime; project=directory/'example'
    result=start(project,proposal('preview_reviewed'),exe,OPTS)
    assert result['accepted'] is None and result['active_workflow']['status']=='awaiting_review'
    assert all((project/p['path']).is_file() for p in result['build_attempts'][-1]['previews'])
    code='import sys; from pathlib import Path; from scene_factory.workflow import resume_context; c=resume_context(Path(sys.argv[1])); print(c["active_workflow"]["status"]); assert c["accepted"] is None'
    read=subprocess.run([sys.executable,'-c',code,str(project)],capture_output=True,text=True,timeout=10)
    assert read.returncode==0 and 'awaiting_review' in read.stdout


def test_real_interrupted_coordinator_restarts_new_attempt(real_runtime):
    directory,exe=real_runtime; project=directory/'example'
    first=start(project,proposal('preview_reviewed'),exe,OPTS)
    state=read_state(project); attempt=first['build_attempts'][-1]; attempt['status']='running'
    write_json(record_path(project,'attempt',attempt['attempt_id']),attempt)
    state['workflow_progress'][state['active_workflow']]['status']='running'; commit_state(project,state)
    resumed=resume(project,exe,OPTS,True)
    assert len(resumed['build_attempts'])==2 and resumed['build_attempts'][0]['status']=='interrupted'
    assert resumed['active_workflow']['started_at']==first['active_workflow']['started_at']
    assert resumed['working_revision']['scene_spec_hash']==first['working_revision']['scene_spec_hash']
