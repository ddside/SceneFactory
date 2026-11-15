"""One project state, immutable authoring records, append-only operation history."""
import copy
import json
import os
from pathlib import Path
import shutil
import uuid

from .contract_utils import canonical_digest
from .intent import BUDGET, image_metadata, now, text, validate_intent, verify_references
from .scene_v2 import migrate_v1, validate_v2
from .spec import fields, identifier, read_json
from .storage import digest, project_lock, write_json

KINDS={'intent':('intents','intent.json'),'revision':('revisions','revision.json'),'attempt':('attempts','attempt.json'),
       'quality':('quality-runs','quality.json'),'visual':('visual-reviews','review.json'),
       'presentation':('presentations','presentation.json'),'acceptance':('acceptances','acceptance.json'),
       'workflow':('workflows','workflow.json'),'event':('events','event.json')}
INDEX={kind:kind+'_ids' for kind in KINDS}


def uid(kind):
    return kind+'.'+uuid.uuid4().hex


def record_path(project,kind,record_id):
    identifier(record_id,kind+'_id')
    if record_id in ('.','..') or not record_id.startswith(kind+'.'):
        raise ValueError(f'invalid {kind} ID')
    directory,filename=KINDS[kind]
    return Path(project)/directory/record_id/filename


def read_state(project):
    value=read_json(Path(project)/'state.json')
    value.setdefault('workflow_version',1)
    if type(value['workflow_version']) is not int or value['workflow_version']!=1:
        raise ValueError('Unsupported workflow state version')
    for key in INDEX.values(): value.setdefault(key,[])
    for key in ('working_revision','latest_intent','accepted','active_workflow','latest_presentation'): value.setdefault(key,None)
    value.setdefault('record_hashes',{}); value.setdefault('workflow_progress',{})
    return value


def commit_state(project,state):
    write_json(Path(project)/'state.json',state)


def immutable_json(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())


def add_record(project,state,kind,record_id,value):
    path=record_path(project,kind,record_id)
    immutable_json(path,value)
    state[INDEX[kind]].append(record_id)
    if kind!='attempt': state['record_hashes'][str(path.relative_to(project))]=digest(path)
    return value


def load_record(project,kind,record_id,state=None):
    project=Path(project); state=state or read_state(project)
    if record_id not in state[INDEX[kind]]: raise ValueError(f'Unknown/uncommitted {kind}: {record_id}')
    path=record_path(project,kind,record_id)
    if kind!='attempt':
        expected=state['record_hashes'].get(str(path.relative_to(project)))
        if expected is None or not path.is_file() or digest(path)!=expected:
            raise ValueError(f'{kind} record missing/modified: {record_id}')
    return read_json(path)


def event(project,state,action,detail):
    eid=uid('event')
    add_record(project,state,'event',eid,{'schema_version':1,'event_id':eid,'action':action,'detail':detail,'created_at':now()})
    return eid


def load_intent(project,intent_id,state=None):
    intent=load_record(project,'intent',intent_id,state)
    return verify_references(project,intent)


def create_intent_locked(project,state,proposal,parent_intent=None):
    allowed=('raw_request','reference_files','observations','assumptions','constraints','unresolved_questions',
             'requested_quality_profile','generation_budget','unsupported_requests','scene_spec','change_summary','allow_seed_change')
    fields(proposal,'proposal',('raw_request','scene_spec','change_summary'),allowed)
    text(proposal['change_summary'],'change_summary')
    if 'generation_budget' in proposal and not isinstance(proposal['generation_budget'],dict):
        raise ValueError('generation_budget must be an object')
    parent=parent_intent or {}
    iid=uid('intent'); directory=record_path(project,'intent',iid).parent
    directory.mkdir(parents=True,exist_ok=False)
    refs=copy.deepcopy(parent.get('reference_files',[])) if 'reference_files' not in proposal else []
    seen_refs=set()
    for source in proposal.get('reference_files',[]):
        fields(source,'reference input',('reference_id','source_path','inspection'))
        identifier(source['reference_id'],'reference_id')
        if source['reference_id'] in seen_refs: raise ValueError('Duplicate reference_id in proposal')
        seen_refs.add(source['reference_id']); text(source['source_path'],'reference.source_path')
        original=Path(source['source_path']).expanduser().resolve()
        fmt,metadata=image_metadata(original)
        suffix='.png' if fmt=='PNG' else '.jpg'
        target=directory/'references'/(source['reference_id']+suffix)
        target.parent.mkdir(exist_ok=True)
        with original.open('rb') as inp,target.open('xb') as out: shutil.copyfileobj(inp,out)
        refs.append({'reference_id':source['reference_id'],'relative_path':str(target.relative_to(project)),
                     'sha256':digest(target),'format':fmt,'metadata':metadata,'inspection':copy.deepcopy(source['inspection'])})
    constraints={c['constraint_id']:copy.deepcopy(c) for c in parent.get('constraints',[])}
    seen_constraints=set()
    for c in proposal.get('constraints',[]):
        if not isinstance(c,dict) or 'constraint_id' not in c: raise ValueError('constraint_id required')
        identifier(c['constraint_id'],'constraint_id')
        if c['constraint_id'] in seen_constraints: raise ValueError('Duplicate constraint_id in proposal')
        seen_constraints.add(c['constraint_id'])
        constraints[c['constraint_id']]=copy.deepcopy(c)
    budget={**BUDGET,**parent.get('generation_budget',{}),**proposal.get('generation_budget',{})}
    intent={'schema_version':1,'intent_id':iid,'raw_request':proposal['raw_request'],'reference_files':refs,
        'observations':copy.deepcopy(proposal.get('observations',parent.get('observations',[]))),
        'assumptions':copy.deepcopy(proposal.get('assumptions',parent.get('assumptions',[]))),
        'constraints':list(constraints.values()),
        'unresolved_questions':copy.deepcopy(proposal.get('unresolved_questions',parent.get('unresolved_questions',[]))),
        'unsupported_requests':copy.deepcopy(proposal.get('unsupported_requests',parent.get('unsupported_requests',[]))),
        'requested_quality_profile':proposal.get('requested_quality_profile',parent.get('requested_quality_profile','basic_scene')),
        'generation_budget':budget,'created_at':now()}
    validate_intent(intent); verify_references(project,intent)
    add_record(project,state,'intent',iid,intent)
    state['latest_intent']=iid
    return intent


def revision_spec(project,revision_id,state=None):
    revision=load_record(project,'revision',revision_id,state)
    path=record_path(project,'revision',revision_id).parent/'scene.json'
    if not path.is_file() or digest(path)!=revision['scene_spec_hash']:
        raise ValueError('Revision snapshot missing or modified')
    return read_json(path)


def diff_specs(before,after):
    left={n['node_id']:n for n in before['nodes']}; right={n['node_id']:n for n in after['nodes']}
    changed={key:{'before':left[key],'after':right[key]} for key in sorted(left.keys()&right.keys()) if left[key]!=right[key]}
    roots={key:{'before':before.get(key),'after':after.get(key)} for key in set(before)|set(after)
           if key!='nodes' and before.get(key)!=after.get(key)}
    return {'added_nodes':sorted(right.keys()-left.keys()),'removed_nodes':sorted(left.keys()-right.keys()),
            'changed_nodes':changed,'root_changes':roots}


def create_revision_locked(project,state,spec,intent_id,summary,parent_id=None,origin='user',allow_seed_change=False):
    if not isinstance(spec,dict): raise ValueError('scene_spec must be an object')
    spec=migrate_v1(spec) if spec.get('schema_version')==1 else spec
    spec=validate_v2(spec)
    before=revision_spec(project,parent_id,state) if parent_id else {'nodes':[]}
    if parent_id:
        if spec['scene_id']!=before['scene_id']: raise ValueError('An edit must preserve scene_id')
        if spec['seed']!=before['seed'] and not allow_seed_change: raise ValueError('An edit must preserve scene seed unless explicitly requested')
    difference=diff_specs(before,spec)
    changed=sorted(set(difference['added_nodes']+difference['removed_nodes']+list(difference['changed_nodes'])))
    rid=uid('revision'); path=record_path(project,'revision',rid).parent/'scene.json'
    immutable_json(path,spec)
    revision={'schema_version':1,'revision_id':rid,'parent_revision_id':parent_id,'intent_id':intent_id,
        'scene_spec_hash':digest(path),'scene_spec_snapshot':str(path.relative_to(project)),
        'change_summary':summary,'changed_node_ids':changed,'created_at':now(),'status':'recorded','origin':origin}
    add_record(project,state,'revision',rid,revision)
    state['working_revision']=rid
    event(project,state,'revision_created',{'revision_id':rid,'parent_revision_id':parent_id,'origin':origin,'changed_node_ids':changed})
    return revision


def revision_view(project,revision_id,state=None):
    state=state or read_state(project)
    revision=load_record(project,'revision',revision_id,state); revision_spec(project,revision_id,state)
    revision['related_build_attempts']=[aid for aid in state['attempt_ids'] if load_record(project,'attempt',aid,state)['revision_id']==revision_id]
    revision['quality_run_ids']=[qid for qid in state['quality_ids'] if load_record(project,'quality',qid,state)['revision_id']==revision_id]
    if state['accepted']:
        accepted=load_record(project,'acceptance',state['accepted'],state)
        if accepted['revision_id']==revision_id: revision['status']='accepted'
        elif state['working_revision']==revision_id: revision['status']='working'
        elif any(load_record(project,'acceptance',aid,state)['revision_id']==revision_id for aid in state['acceptance_ids']):
            revision['status']='previously_accepted'
    elif state['working_revision']==revision_id: revision['status']='working'
    return revision


def history(project):
    state=read_state(project)
    return {'working_revision':state['working_revision'],'accepted':state['accepted'],
            'revisions':[revision_view(project,rid,state) for rid in state['revision_ids']],
            'events':[load_record(project,'event',eid,state) for eid in state['event_ids']]}


def diff_revisions(project,before_id,after_id):
    return diff_specs(revision_spec(project,before_id),revision_spec(project,after_id))
