"""Profile-gated publication and rollback of immutable bundles, not regeneration."""
import copy
from pathlib import Path

from .intent import now, relative_path
from .project import build_at
from .quality_profiles import validate_quality_report
from .storage import check_artifacts, digest, project_lock
from .workflow_store import (add_record, commit_state, event, load_intent, load_record, read_state,
                             record_path, revision_spec, uid)


def presentation_data(project,state,revision_id,attempt,quality,status):
    revision=load_record(project,'revision',revision_id,state)
    intent=load_intent(project,revision['intent_id'],state)
    spec=revision_spec(project,revision_id,state)
    accepted_revision=None
    if state['accepted']: accepted_revision=load_record(project,'acceptance',state['accepted'],state)['revision_id']
    return {'schema_version':1,'requested_summary':intent['raw_request'],'revision_id':revision_id,
        'generated_environment':{'scene_id':spec['scene_id'],'logical_node_count':len(spec['nodes']),
            'skills':sorted({n['skill']['skill_id']+'@'+n['skill']['version'] for n in spec['nodes']})},
        'status':status,'profile':quality['profile'],'quality_run_id':quality['quality_run_id'],
        'previews':copy.deepcopy(attempt['previews']),
        'blend_path':f"builds/{attempt['build_id']}/scene.blend" if attempt.get('build_id') else None,
        'accepted_revision_id':revision_id if status=='accepted' else accepted_revision,
        'unsupported_requests':intent['unsupported_requests'],'unresolved_questions':intent['unresolved_questions'],
        'unperformed_checks':[name for name,item in quality['stages'].items() if item['state'] in ('not_run','not_applicable')],
        'findings':quality['findings'],'edit_instructions':'Provide another natural-language request to Codex; keep unrelated IDs and seeds',
        'created_at':now()}


def save_presentation_locked(project,state,revision_id,attempt,quality,status):
    pid=uid('presentation')
    value={'presentation_id':pid,**presentation_data(project,state,revision_id,attempt,quality,status)}
    add_record(project,state,'presentation',pid,value)
    state['latest_presentation']=pid
    return value


def publish_locked(project,state,attempt,quality):
    validate_quality_report(quality)
    if quality['acceptance']!='eligible': raise ValueError('Quality profile is not satisfied; cannot accept')
    if state['working_revision']!=quality['revision_id'] or attempt['revision_id']!=quality['revision_id']:
        raise ValueError('Stale revision cannot be published as current accepted result')
    if state['active_workflow']!=attempt['workflow_id']: raise ValueError('Stale workflow cannot publish')
    build,metadata=build_at(project,attempt['build_id'])
    if digest(build/'scene.json')!=load_record(project,'revision',quality['revision_id'],state)['scene_spec_hash']:
        raise ValueError('Attempt build does not match immutable revision snapshot')
    presentation=save_presentation_locked(project,state,quality['revision_id'],attempt,quality,'accepted')
    paths={str((build/name).relative_to(project)):sha for name,sha in metadata['sha256'].items()}
    paths[str((build/'build.json').relative_to(project))]=digest(build/'build.json')
    revision=load_record(project,'revision',quality['revision_id'],state)
    intent=load_intent(project,revision['intent_id'],state)
    for kind,rid in (('revision',revision['revision_id']),('intent',intent['intent_id']),
                     ('quality',quality['quality_run_id']),('presentation',presentation['presentation_id'])):
        path=record_path(project,kind,rid); paths[str(path.relative_to(project))]=digest(path)
    paths[revision['scene_spec_snapshot']]=revision['scene_spec_hash']
    for ref in intent['reference_files']: paths[ref['relative_path']]=ref['sha256']
    if quality['visual_review_id']:
        path=record_path(project,'visual',quality['visual_review_id']); paths[str(path.relative_to(project))]=digest(path)
    for preview in attempt['previews']: paths[preview['path']]=preview['sha256']
    check_artifacts(project,paths)
    accepted_id=uid('acceptance')
    accepted={'schema_version':1,'acceptance_id':accepted_id,'revision_id':quality['revision_id'],
        'attempt_id':attempt['attempt_id'],'build_id':attempt['build_id'],'quality_run_id':quality['quality_run_id'],
        'presentation_id':presentation['presentation_id'],'profile':quality['profile'],
        'bundle_sha256':paths,'accepted_at':now()}
    add_record(project,state,'acceptance',accepted_id,accepted)
    state['accepted']=accepted_id
    state['workflow_progress'][attempt['workflow_id']].update(status='accepted',stop_reason=None)
    state['latest']={'action':'accept','status':'accepted','revision_id':quality['revision_id'],'error':None,'at':now()}
    event(project,state,'accepted',{'acceptance_id':accepted_id,'revision_id':quality['revision_id'],
                                   'quality_run_id':quality['quality_run_id']})
    # No filesystem writes after this single authoritative publication point.
    commit_state(project,state)
    return accepted


def check_accepted(project,acceptance_id=None,state=None):
    project=Path(project).resolve(); state=state or read_state(project)
    acceptance_id=acceptance_id or state['accepted']
    if not acceptance_id: raise ValueError('No accepted revision')
    record=load_record(project,'acceptance',acceptance_id,state)
    for path in record['bundle_sha256']: relative_path(project,path)
    check_artifacts(project,record['bundle_sha256'])
    quality=load_record(project,'quality',record['quality_run_id'],state)
    validate_quality_report(quality)
    if (quality['acceptance']!='eligible' or quality['revision_id']!=record['revision_id']
        or quality['attempt_id']!=record['attempt_id'] or quality['profile']!=record['profile']):
        raise ValueError('Accepted bundle / quality association mismatch')
    revision_spec(project,record['revision_id'],state)
    return record


def rollback(project,revision_id,reason='Return to a previously accepted revision'):
    project=Path(project).resolve()
    with project_lock(project):
        state=read_state(project)
        candidates=[load_record(project,'acceptance',aid,state) for aid in reversed(state['acceptance_ids'])]
        target=next((a for a in candidates if a['revision_id']==revision_id),None)
        if target is None: raise ValueError('Rollback requires a previously accepted revision; rebuild is a separate operation')
        check_accepted(project,target['acceptance_id'],state)
        previous=state['accepted']
        original=load_record(project,'presentation',target['presentation_id'],state)
        pid=uid('presentation')
        display={**original,'presentation_id':pid,'status':'rolled_back','requested_summary':reason,'created_at':now()}
        add_record(project,state,'presentation',pid,display)
        state.update(accepted=target['acceptance_id'],working_revision=revision_id,
                     last_successful_build=target['build_id'],active_workflow=None,latest_presentation=pid)
        state['latest']={'action':'rollback','status':'succeeded','revision_id':revision_id,'error':None,'at':now()}
        event(project,state,'rollback',{'from_acceptance':previous,'to_acceptance':target['acceptance_id'],
                                       'revision_id':revision_id,'reason':reason})
        commit_state(project,state)
        return display
