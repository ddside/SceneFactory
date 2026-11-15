"""Bounded local generation coordinator; language/vision decisions belong to Codex."""
import copy
from datetime import datetime
from pathlib import Path
import time

from .compiler import compile_scene
from .intent import effective_constraints, now
from .project import (build_at, current_spec_path, init_project, operate, run_build)
from .publication import check_accepted, publish_locked, save_presentation_locked
from .quality_profiles import evaluate, profile, propose_repair, validate_quality_report, validate_visual_review
from .quality import report as base_quality
from .spec import read_json
from .storage import digest, project_lock, write_json, recover_stale_lock
from .workflow_store import (add_record, commit_state, create_intent_locked, create_revision_locked, event,
    load_intent, load_record, read_state, record_path, revision_spec, revision_view, uid)

VIEWS={'overview':[1,-1.4,1.1],'top':[.001,.001,1]}


def _new_workflow_locked(project,state,revision):
    intent=load_intent(project,revision['intent_id'],state)
    wid=uid('workflow')
    value={'schema_version':1,'workflow_id':wid,'root_revision_id':revision['revision_id'],
           'intent_id':intent['intent_id'],'generation_budget':intent['generation_budget'],
           'profile':profile(intent['requested_quality_profile']),'started_at':now()}
    if state['active_workflow']:
        previous=state['workflow_progress'][state['active_workflow']]
        if previous['status'] not in ('accepted','stopped','superseded'):
            previous.update(status='superseded',stop_reason='New user operation')
    add_record(project,state,'workflow',wid,value)
    state['active_workflow']=wid
    state['workflow_progress'][wid]={'status':'ready','stop_reason':None,'last_score':None,'no_improvement_count':0}
    event(project,state,'workflow_started',{'workflow_id':wid,'revision_id':revision['revision_id']})
    return value


def start(project,proposal,executable,options,edit=False):
    project=Path(project).resolve()
    if not isinstance(proposal,dict): raise ValueError('Generation proposal must be a JSON object')
    if not project.exists(): init_project(project,2)
    with project_lock(project):
        state=read_state(project); parent_id=state['working_revision']
        if edit and not parent_id: raise ValueError('No working revision to edit')
        if not edit and parent_id: raise ValueError('Managed project already exists; use edit or rebuild')
        parent_intent=load_intent(project,load_record(project,'revision',parent_id,state)['intent_id'],state) if edit else None
        if 'allow_seed_change' in proposal and type(proposal['allow_seed_change']) is not bool:
            raise ValueError('allow_seed_change must be explicit boolean')
        try:
            intent=create_intent_locked(project,state,proposal,parent_intent)
            revision=create_revision_locked(project,state,proposal['scene_spec'],intent['intent_id'],proposal['change_summary'],
                                            parent_id if edit else None,allow_seed_change=proposal.get('allow_seed_change',False))
        except (ValueError,OSError) as exc:
            # Uncommitted snapshot directories are diagnostic orphans; never adopt
            # half a proposal or replace the accepted pointer during rejection.
            previous=read_state(project)
            try:
                event(project,previous,'proposal_rejected',{'raw_request':proposal.get('raw_request') if isinstance(proposal,dict) else None,'reason':str(exc)})
                previous['latest']={'action':'proposal','status':'failed','error':str(exc),'at':now()}
                commit_state(project,previous)
            except OSError: pass
            raise
        _new_workflow_locked(project,state,revision)
        commit_state(project,state)
    return execute(project,executable,options)


def rebuild(project,executable,options,revision_id=None):
    project=Path(project).resolve()
    with project_lock(project):
        state=read_state(project); rid=revision_id or state['working_revision']
        revision=load_record(project,'revision',rid,state); revision_spec(project,rid,state)
        state['working_revision']=rid
        _new_workflow_locked(project,state,revision)
        event(project,state,'rebuild_requested',{'revision_id':rid,'note':'New attempt, not rollback'})
        commit_state(project,state)
    return execute(project,executable,options)


def _stop_locked(project,state,wid,reason,status='stopped'):
    state['workflow_progress'][wid].update(status=status,stop_reason=reason)
    state['latest']={'action':'workflow','status':status,'error':reason,'at':now()}
    event(project,state,'workflow_stopped',{'workflow_id':wid,'reason':reason,'status':status})
    commit_state(project,state)


def _limits(project,state,workflow):
    attempts=[load_record(project,'attempt',aid,state) for aid in state['attempt_ids']]
    used=sum(a['workflow_id']==workflow['workflow_id'] for a in attempts)
    budget=workflow['generation_budget']
    deadline=datetime.fromisoformat(workflow['started_at']).timestamp()+budget['max_seconds']
    if used>=budget['max_attempts']: return 'Maximum build attempt count reached',deadline
    if time.time()>=deadline: return 'Total time budget exhausted (resume does not reset it)',deadline
    return None,deadline


def _save_attempt(project,attempt):
    write_json(record_path(project,'attempt',attempt['attempt_id']),attempt)


def _failed_quality(workflow,attempt,revision_id,qid,reason,base=None):
    stages=copy.deepcopy((base or base_quality())['stages'])
    stages['specification']={'state':'not_run','reason':'Request conformance could not be evaluated','evidence':[]}
    stages['execution']={'state':'failed','reason':reason,'evidence':['attempt error']}
    from .contract_utils import canonical_digest
    value={'schema_version':2,'quality_run_id':qid,'revision_id':revision_id,'attempt_id':attempt['attempt_id'],
           'created_at':now(),'profile':workflow['profile'],'profile_digest':canonical_digest(workflow['profile']),
           'acceptance':'not_eligible','stages':stages,'constraint_checks':[],
           'overridden_inferred_constraints':[],'conflicting_constraints':[],
           'findings':[{'kind':'execution','node_id':None,'reason':reason}],
           'visual_review_id':None,'failure_score':10}
    return validate_quality_report(value)


def _save_quality_locked(project,state,attempt,quality):
    add_record(project,state,'quality',quality['quality_run_id'],quality)
    attempt['quality_run_ids'].append(quality['quality_run_id'])
    _save_attempt(project,attempt)
    event(project,state,'quality_evaluated',{'quality_run_id':quality['quality_run_id'],
        'attempt_id':attempt['attempt_id'],'acceptance':quality['acceptance']})


def execute(project,executable,options):
    project=Path(project).resolve()
    with project_lock(project):
        while True:
            state=read_state(project); wid=state['active_workflow']
            if not wid: return resume_context(project)
            workflow=load_record(project,'workflow',wid,state); progress=state['workflow_progress'][wid]
            if progress['status'] in ('accepted','awaiting_review','needs_repair','stopped','superseded'):
                return resume_context(project)
            try: intent=load_intent(project,workflow['intent_id'],state)
            except ValueError as exc:
                _stop_locked(project,state,wid,str(exc),'needs_input'); return resume_context(project)
            selected,overridden,conflicts=effective_constraints(intent)
            blocking=[q['text'] for key in ('unresolved_questions','unsupported_requests') for q in intent[key] if q['blocking']]
            blocking += [f"Reference {r['reference_id']} not viewed" for r in intent['reference_files'] if r['inspection']['state']!='viewed']
            if conflicts or blocking:
                _stop_locked(project,state,wid,'; '.join(blocking) if blocking else 'Conflicting hard constraints','needs_input')
                return resume_context(project)
            limit,deadline=_limits(project,state,workflow)
            if limit:
                _stop_locked(project,state,wid,limit); return resume_context(project)
            rid=state['working_revision']; revision=load_record(project,'revision',rid,state)
            spec=revision_spec(project,rid,state)
            try: compiled=compile_scene(spec)
            except ValueError as exc:
                _stop_locked(project,state,wid,f'Compile blocked: {exc}','needs_input'); return resume_context(project)
            budget=workflow['generation_budget']
            if len(compiled['build_plan']['nodes'])>budget['max_nodes']:
                _stop_locked(project,state,wid,'Resolved node resource budget exceeded'); return resume_context(project)
            opts=dict(options)
            opts['resolution']=min(opts['resolution'],budget['max_resolution'])
            opts['samples']=min(opts['samples'],budget['max_samples'])
            opts['_deadline_epoch']=deadline
            aid=uid('attempt')
            attempt={'schema_version':1,'attempt_id':aid,'workflow_id':wid,'revision_id':rid,'intent_id':intent['intent_id'],
                'scene_spec_hash':revision['scene_spec_hash'],'status':'running','started_at':now(),'finished_at':None,
                'build_id':None,'previews':[],'quality_run_ids':[],'error':None}
            add_record(project,state,'attempt',aid,attempt)
            progress['status']='running'
            event(project,state,'attempt_started',{'attempt_id':aid,'revision_id':rid,'workflow_id':wid})
            commit_state(project,state)
            try:
                built=run_build(project,executable,opts,source_path=project/revision['scene_spec_snapshot'],_locked=True)
                attempt['build_id']=built['build_id']; _save_attempt(project,attempt)
                operate(project,'validate',executable,opts,build_id=built['build_id'],check_working_spec=False,_locked=True)
                for name,direction in VIEWS.items():
                    result=operate(project,'preview',executable,{**opts,'view_direction':direction},
                                   build_id=built['build_id'],check_working_spec=False,_locked=True)
                    path=Path(result['directory'])/'preview.png'
                    attempt['previews'].append({'view':name,'path':str(path.relative_to(project)),
                        'sha256':digest(path),'resolution':opts['resolution']})
                    _save_attempt(project,attempt)
                build,_=build_at(project,built['build_id'])
                quality=evaluate(intent,spec,read_json(build/'plan.json'),read_json(build/'artifact-manifest.json'),
                    read_json(build/'quality.json'),rid,aid,uid('quality'),now(),workflow['profile'])
            except Exception as exc:
                attempt['error']=str(exc); attempt['status']='failed'
                latest=read_state(project).get('latest',{})
                if not attempt['build_id'] and latest and latest.get('action')=='build' and latest.get('directory'):
                    attempt['build_id']=Path(latest['directory']).name
                path=project/'builds'/attempt['build_id']/'quality.json' if attempt['build_id'] else None
                base=read_json(path) if path and path.is_file() else None
                quality=_failed_quality(workflow,attempt,rid,uid('quality'),str(exc),base)
            attempt['finished_at']=now()
            state=read_state(project); progress=state['workflow_progress'][wid]
            _save_quality_locked(project,state,attempt,quality)
            if quality['acceptance']=='eligible':
                attempt['status']='quality_passed'; _save_attempt(project,attempt)
                commit_state(project,state)
                _publish_or_record_failure(project,state,attempt,quality)
                return resume_context(project)
            issues=quality['findings']
            if not issues:
                attempt['status']='awaiting_review'; _save_attempt(project,attempt)
                progress.update(status='awaiting_review',stop_reason='Codex must inspect actual preview images and submit review')
                save_presentation_locked(project,state,rid,attempt,quality,'awaiting_visual_review')
                commit_state(project,state)
                return resume_context(project)
            attempt['status']='quality_failed' if not attempt['error'] else 'failed'; _save_attempt(project,attempt)
            score=quality['failure_score']
            if progress['last_score'] is not None and score>=progress['last_score']:
                progress['no_improvement_count']+=1
            else: progress['no_improvement_count']=0
            progress['last_score']=score
            save_presentation_locked(project,state,rid,attempt,quality,'candidate_not_accepted')
            if progress['no_improvement_count']>=budget['no_improvement_limit']:
                _stop_locked(project,state,wid,'No improvement in quality'); return resume_context(project)
            limit,_=_limits(project,state,workflow)
            if limit:
                _stop_locked(project,state,wid,limit); return resume_context(project)
            artifact_path=project/'builds'/attempt['build_id']/'artifact-manifest.json' if attempt['build_id'] else None
            artifact=read_json(artifact_path) if artifact_path and artifact_path.is_file() else None
            repair=propose_repair(quality,spec,artifact) if artifact else None
            if repair is None:
                progress.update(status='needs_repair',stop_reason='No safe deterministic repair; Codex may supply a bounded repair proposal')
                commit_state(project,state); return resume_context(project)
            create_revision_locked(project,state,repair['scene_spec'],intent['intent_id'],repair['change_summary'],rid,'repair')
            event(project,state,'automatic_repair',{'from_revision':rid,'quality_run_id':quality['quality_run_id'],
                                                  'reason':repair['change_summary']})
            progress['status']='ready'
            commit_state(project,state)


def repair(project,proposal,executable,options):
    project=Path(project).resolve()
    with project_lock(project):
        state=read_state(project); wid=state['active_workflow']
        if not wid: raise ValueError('No active workflow to repair')
        workflow=load_record(project,'workflow',wid,state)
        limit,_=_limits(project,state,workflow)
        if limit or state['workflow_progress'][wid]['status'] in ('stopped','accepted','superseded'):
            raise ValueError(limit or 'Workflow stopped; a new user edit or explicit rebuild is required')
        from .spec import fields
        fields(proposal,'repair proposal',('scene_spec','change_summary'))
        current=revision_spec(project,state['working_revision'],state)
        from .scene_v2 import validate_v2
        if validate_v2(proposal['scene_spec'])==current:
            _stop_locked(project,state,wid,'Repair proposed no semantic change'); return resume_context(project)
        create_revision_locked(project,state,proposal['scene_spec'],workflow['intent_id'],proposal['change_summary'],state['working_revision'],'repair')
        state['workflow_progress'][wid]['status']='ready'
        event(project,state,'codex_repair',{'workflow_id':wid,'reason':proposal['change_summary']})
        commit_state(project,state)
    return execute(project,executable,options)


def submit_review(project,review):
    project=Path(project).resolve()
    with project_lock(project):
        state=read_state(project); attempt=load_record(project,'attempt',review.get('attempt_id'),state)
        if attempt['revision_id']!=state['working_revision'] or attempt['workflow_id']!=state['active_workflow']:
            raise ValueError('Stale review cannot publish current working revision')
        workflow=load_record(project,'workflow',attempt['workflow_id'],state)
        if state['workflow_progress'][attempt['workflow_id']]['status'] not in ('awaiting_review','needs_repair'):
            raise ValueError('Workflow is not awaiting a visual review')
        deadline=datetime.fromisoformat(workflow['started_at']).timestamp()+workflow['generation_budget']['max_seconds']
        if time.time()>deadline:
            _stop_locked(project,state,attempt['workflow_id'],'Total workflow time budget exhausted before review')
            return {'accepted':None,'reason':'Total time budget exhausted'}
        intent=load_intent(project,attempt['intent_id'],state)
        validated=validate_visual_review(review,project,attempt,intent)
        vid=uid('visual'); stored={**validated,'visual_review_id':vid,'created_at':now()}
        add_record(project,state,'visual',vid,stored)
        build,_=build_at(project,attempt['build_id'])
        quality=evaluate(intent,revision_spec(project,attempt['revision_id'],state),read_json(build/'plan.json'),
            read_json(build/'artifact-manifest.json'),read_json(build/'quality.json'),attempt['revision_id'],attempt['attempt_id'],
            uid('quality'),now(),workflow['profile'],validated,vid)
        _save_quality_locked(project,state,attempt,quality)
        if quality['acceptance']=='eligible':
            attempt['status']='quality_passed'; _save_attempt(project,attempt); commit_state(project,state)
            accepted=_publish_or_record_failure(project,state,attempt,quality)
            return {'accepted':accepted,'quality':quality}
        attempt['status']='quality_failed'; _save_attempt(project,attempt)
        progress=state['workflow_progress'][attempt['workflow_id']]
        if progress['last_score'] is not None and quality['failure_score']>=progress['last_score']:
            progress['no_improvement_count']+=1
        else: progress['no_improvement_count']=0
        progress['last_score']=quality['failure_score']
        progress.update(status='needs_repair',stop_reason='Visual or request-conformance review failed')
        save_presentation_locked(project,state,attempt['revision_id'],attempt,quality,'candidate_not_accepted')
        limit,_=_limits(project,state,workflow)
        if limit or progress['no_improvement_count']>=workflow['generation_budget']['no_improvement_limit']:
            _stop_locked(project,state,attempt['workflow_id'],limit or 'No improvement in visual quality')
            return {'accepted':None,'quality':quality}
        commit_state(project,state)
        return {'accepted':None,'quality':quality}


def resume_context(project):
    project=Path(project).resolve(); state=read_state(project)
    result={'working_revision':None,'working_intent':None,'latest_intent':None,'accepted':None,'accepted_presentation':None,'active_workflow':None,
            'build_attempts':[],'quality_runs':[],'presentation':None,'latest_operation':state.get('latest')}
    if state['working_revision']:
        result['working_revision']=revision_view(project,state['working_revision'],state)
        result['scene_spec']=revision_spec(project,state['working_revision'],state)
        try: result['working_intent']=load_intent(project,result['working_revision']['intent_id'],state)
        except ValueError as exc: result['working_intent']={'integrity':'failed','error':str(exc)}
    if state['latest_intent']:
        try: result['latest_intent']=load_intent(project,state['latest_intent'],state)
        except ValueError as exc: result['latest_intent']={'intent_id':state['latest_intent'],'integrity':'failed','error':str(exc)}
    if state['active_workflow']:
        wf=load_record(project,'workflow',state['active_workflow'],state)
        result['active_workflow']={**wf,**state['workflow_progress'][wf['workflow_id']]}
    if state['accepted']:
        try:
            result['accepted']={**check_accepted(project,state['accepted'],state),'integrity':'passed'}
            result['accepted_presentation']=load_record(project,'presentation',result['accepted']['presentation_id'],state)
        except ValueError as exc: result['accepted']={'acceptance_id':state['accepted'],'integrity':'failed','error':str(exc)}
    result['build_attempts']=[load_record(project,'attempt',aid,state) for aid in state['attempt_ids']]
    result['quality_runs']=[load_record(project,'quality',qid,state) for qid in state['quality_ids']]
    if state['latest_presentation']: result['presentation']=load_record(project,'presentation',state['latest_presentation'],state)
    return result


def resume(project,executable=None,options=None,execute_pending=False):
    project=Path(project).resolve()
    if not execute_pending: return resume_context(project)
    recover_stale_lock(project)
    with project_lock(project):
        state=read_state(project); wid=state['active_workflow']
        if wid and state['workflow_progress'][wid]['status'] in ('publication_pending','running'):
            candidates=[load_record(project,'quality',qid,state) for qid in reversed(state['quality_ids'])]
            candidate=next((q for q in candidates if q['revision_id']==state['working_revision'] and q['acceptance']=='eligible'),None)
            if candidate:
                attempt=load_record(project,'attempt',candidate['attempt_id'],state)
                if attempt['workflow_id']==wid:
                    _publish_or_record_failure(project,state,attempt,candidate)
                    return resume_context(project)
        if wid and state['workflow_progress'][wid]['status']=='running':
            for aid in state['attempt_ids']:
                attempt=load_record(project,'attempt',aid,state)
                if attempt['workflow_id']==wid and attempt['status']=='running':
                    attempt.update(status='interrupted',finished_at=now(),error='Previous coordinator interrupted; artifacts retained')
                    _save_attempt(project,attempt)
                    event(project,state,'attempt_interrupted',{'attempt_id':aid,'workflow_id':wid})
            state['workflow_progress'][wid].update(status='ready',stop_reason='Restarting from immutable revision with original budget')
            commit_state(project,state)
    if executable is None or options is None: raise ValueError('Blender runtime required to execute pending work')
    return execute(project,executable,options)


def _publish_or_record_failure(project,state,attempt,quality):
    try: return publish_locked(project,state,attempt,quality)
    except OSError as exc:
        fresh=read_state(project)
        fresh['workflow_progress'][attempt['workflow_id']].update(status='publication_pending',stop_reason=str(exc))
        event(project,fresh,'publication_failed',{'quality_run_id':quality['quality_run_id'],'reason':str(exc)})
        commit_state(project,fresh)
        raise


def summary(context):
    attempt=context['build_attempts'][-1] if context['build_attempts'] else None
    quality=context['quality_runs'][-1] if context['quality_runs'] else None
    return {'working_revision':context['working_revision'],'accepted':context['accepted'],
            'active_workflow':context['active_workflow'],'latest_attempt':attempt,'latest_quality':quality,
            'presentation':context['presentation'],
            'next_action':'Inspect actual previews and submit image-bound review if awaiting_review; otherwise inspect stop_reason'}
