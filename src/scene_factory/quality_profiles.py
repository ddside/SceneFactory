"""Profile-scoped acceptance and explicit, image-bound Codex review attestations."""
import copy
import math

from .contract_utils import canonical_digest
from .intent import effective_constraints, relative_path, validate_intent
from .quality import STAGES, STATES
from .spec import SpecError, fields
from .storage import digest

REQUIRED={'structural':['specification','execution','structure'],
          'preview_reviewed':['specification','execution','structure','visual'],
          'basic_scene':['specification','execution','structure','visual','domain']}
VISUAL_CHECKS=('requested_objects_visible','layout_reasonable','main_structure_visible',
               'no_obvious_intersection_or_floating','reference_consistent','request_conformance')


def profile(name):
    if name not in REQUIRED: raise ValueError('Unknown quality profile')
    return {'schema_version':1,'profile_id':name,'version':'1.0.0','required_stages':copy.deepcopy(REQUIRED[name]),
            'request_conformance_required':True,
            'scope':{'structural':'Structure and declared hard constraints only; images unreviewed',
                     'preview_reviewed':'Structure, declared hard constraints and recorded visual review',
                     'basic_scene':'Preview-reviewed scene and basic declared spatial constraints; no physics/photorealism guarantee'}[name]}


def validate_visual_review(value,project,attempt,intent):
    fields(value,'VisualReview',('attempt_id','reviewer','method','viewed','images','checks','notes'))
    if value['attempt_id']!=attempt['attempt_id'] or value['viewed'] is not True:
        raise SpecError('VisualReview: actual inspection of this attempt must be attested')
    if not isinstance(value['reviewer'],str) or not value['reviewer'].strip() or value['method']!='image_viewer':
        raise SpecError('VisualReview: named reviewer and image_viewer method required')
    if not isinstance(value['notes'],str) or not value['notes'].strip(): raise SpecError('VisualReview.notes required')
    expected={p['path']:p['sha256'] for p in attempt['previews']}
    if not expected or not isinstance(value['images'],list): raise SpecError('VisualReview: previews required')
    actual={}
    for image in value['images']:
        fields(image,'VisualReview.image',('path','sha256'))
        if not isinstance(image['path'],str) or image['path'] in actual: raise SpecError('VisualReview: duplicate/invalid image')
        actual[image['path']]=image['sha256']
    if actual!=expected: raise SpecError('VisualReview: exact preview paths/hashes must match the attempt')
    for path,sha in expected.items():
        file=relative_path(project,path)
        if not file.is_file() or digest(file)!=sha: raise SpecError('VisualReview: image missing/modified')
    fields(value['checks'],'VisualReview.checks',VISUAL_CHECKS)
    for key,check in value['checks'].items():
        fields(check,'VisualReview.check',('state','reason'))
        allowed=('passed','failed','not_applicable') if key=='reference_consistent' and not intent['reference_files'] else ('passed','failed')
        if check['state'] not in allowed or not isinstance(check['reason'],str) or not check['reason'].strip():
            raise SpecError(f'VisualReview.{key}: invalid state/reason')
    return copy.deepcopy(value)


def constraint_checks(intent,spec,plan,artifacts):
    selected,overridden,conflicts=effective_constraints(intent)
    authored={n['node_id']:n for n in spec['nodes']}; resolved={n['node_id']:n for n in plan['nodes']}
    checks=[]
    for constraint in selected:
        if 'target_node_id' in constraint:
            ids=[constraint['target_node_id']] if constraint['target_node_id'] in authored else []
        else:
            skill=constraint['target_role'][6:]
            ids=sorted(nid for nid,n in authored.items() if n['skill']['skill_id']==skill)
        kind=constraint['type']; expected=constraint['expected_value']; tolerance=constraint['tolerance']
        values=[]; failed=[]
        if kind=='node_count':
            values=[len(ids)]; errors=[abs(len(ids)-expected)]
        elif kind=='exists':
            values=[bool(ids)]; errors=[0 if bool(ids)==expected else 1]
        elif not ids:
            values=[None]; errors=[None]
        else:
            errors=[]
            for nid in ids:
                node=resolved[nid]
                if kind=='parameter_equals': actual=node['parameters'].get(constraint['property'])
                elif kind=='location_equals': actual=[node['world_matrix'][i][3] for i in range(3)]
                else:
                    parts=[a for a in artifacts['artifacts'] if a['source_node_id']==nid and a['type']=='Mesh']
                    actual=min((a['bounds'][0][2] for a in parts),default=None)
                values.append(actual)
                if actual is None: error=None
                elif kind=='location_equals': error=max(abs(a-b) for a,b in zip(actual,expected))
                else: error=abs(actual-expected)
                errors.append(error)
                if error is None or error>tolerance: failed.append(nid)
        passed=all(error is not None and error<=tolerance for error in errors)
        checks.append({'constraint_id':constraint['constraint_id'],'type':kind,'strength':constraint['strength'],
            'target_node_ids':ids,'property':constraint.get('property'),'expected_value':expected,'actual':values,
            'error':max((x for x in errors if x is not None),default=None),
            'tolerance':tolerance,'state':'passed' if passed else 'failed','failed_node_ids':failed})
    return checks,overridden,conflicts


def evaluate(intent,spec,plan,artifacts,base_report,revision_id,attempt_id,quality_id,created_at,
             profile_snapshot,visual=None,visual_id=None):
    validate_intent(intent)
    if profile_snapshot!=profile(profile_snapshot.get('profile_id')): raise SpecError('Quality profile snapshot/version mismatch')
    stages=copy.deepcopy(base_report['stages'])
    stages['visual']={'state':'not_run','reason':'No recorded actual image review for this attempt','evidence':[]}
    checks,overridden,conflicts=constraint_checks(intent,spec,plan,artifacts)
    hard=[c for c in checks if c['strength']=='hard' and c['state']!='passed']
    blockers=[q['text'] for key in ('unresolved_questions','unsupported_requests') for q in intent[key] if q['blocking']]
    blockers += [f"Reference {r['reference_id']} not inspected" for r in intent['reference_files'] if r['inspection']['state']!='viewed']
    if conflicts: blockers.append('Conflicting hard constraints')
    findings=[]
    for check in hard:
        targets=check['failed_node_ids'] or check['target_node_ids'] or [None]
        for target in targets:
            findings.append({'kind':'constraint','constraint_id':check['constraint_id'],'type':check['type'],
                'node_id':target,'property':check['property'],'expected_value':check['expected_value'],
                'actual':check['actual'],'error':check['error'],'reason':'Declared hard constraint not satisfied'})
    for reason in blockers: findings.append({'kind':'blocker','node_id':None,'reason':reason})
    if hard or blockers:
        stages['specification']={'state':'failed','reason':'Request conformance failed; schema success is insufficient',
                                  'evidence':['constraint_checks']}
    if 'domain' in profile_snapshot['required_stages']:
        stages['domain']={'state':'failed' if hard or blockers else 'passed',
                          'reason':'Basic declared dimensions/count/placement constraints evaluated; no physical validation',
                          'evidence':['constraint_checks']}
    if visual is not None:
        passed=all(c['state'] in ('passed','not_applicable') for c in visual['checks'].values())
        stages['visual']={'state':'passed' if passed else 'failed','reason':visual['notes'],'evidence':[visual_id]}
        if not passed: findings.append({'kind':'visual','node_id':None,'reason':visual['notes']})
    eligible=not hard and not blockers and all(stages[s]['state']=='passed' for s in profile_snapshot['required_stages'])
    score=sum(1 for c in hard)+len(blockers)+sum(c['state']=='failed' for c in stages.values())
    result={'schema_version':2,'quality_run_id':quality_id,'revision_id':revision_id,'attempt_id':attempt_id,
        'created_at':created_at,'profile':profile_snapshot,'profile_digest':canonical_digest(profile_snapshot),
        'acceptance':'eligible' if eligible else 'not_eligible','stages':stages,'constraint_checks':checks,
        'overridden_inferred_constraints':overridden,'conflicting_constraints':conflicts,'findings':findings,
        'visual_review_id':visual_id,'failure_score':score}
    return validate_quality_report(result)


def validate_quality_report(value):
    fields(value,'QualityReport2',('schema_version','quality_run_id','revision_id','attempt_id','created_at','profile',
        'profile_digest','acceptance','stages','constraint_checks','overridden_inferred_constraints',
        'conflicting_constraints','findings','visual_review_id','failure_score'))
    if type(value['schema_version']) is not int or value['schema_version']!=2: raise SpecError('QualityReport2: version 2 required')
    p=value['profile']
    if p!=profile(p.get('profile_id')) or canonical_digest(p)!=value['profile_digest']: raise SpecError('QualityReport2: profile mismatch')
    if not isinstance(value['stages'],dict) or set(value['stages'])!=set(STAGES): raise SpecError('QualityReport2: stage set mismatch')
    for entry in value['stages'].values():
        fields(entry,'quality stage',('state','reason','evidence'))
        if entry['state'] not in STATES or not isinstance(entry['reason'],str) or not isinstance(entry['evidence'],list):
            raise SpecError('QualityReport2: invalid stage state/reason/evidence')
    hard_failed=any(c['strength']=='hard' and c['state']!='passed' for c in value['constraint_checks'])
    eligible=(not hard_failed and not value['conflicting_constraints'] and not any(f['kind']=='blocker' for f in value['findings'])
              and all(value['stages'][s]['state']=='passed' for s in p['required_stages']))
    if value['acceptance']!=('eligible' if eligible else 'not_eligible'): raise SpecError('QualityReport2: false acceptance eligibility')
    if value['stages']['visual']['state']=='passed' and not value['visual_review_id']: raise SpecError('QualityReport2: visual evidence required')
    return value


def propose_repair(quality,spec,artifacts):
    """Conservative deterministic fixes, not a natural-language interpreter."""
    revised=copy.deepcopy(spec); nodes={n['node_id']:n for n in revised['nodes']}; reasons=[]
    for f in quality['findings']:
        if f['kind']!='constraint' or f['node_id'] not in nodes: return None
        node=nodes[f['node_id']]
        if f['type']=='parameter_equals' and f['property'] in node['parameters']:
            node['parameters'][f['property']]=f['expected_value']
        elif f['type']=='location_equals' and node['parent_id'] is None:
            node['transform']['location']=copy.deepcopy(f['expected_value'])
        elif f['type']=='grounded' and node['parent_id'] is None:
            parts=[a for a in artifacts['artifacts'] if a['source_node_id']==f['node_id'] and a['type']=='Mesh']
            if not parts: return None
            current=min(a['bounds'][0][2] for a in parts)
            node['transform']['location'][2]+=f['expected_value']-current
        else: return None
        reasons.append(f"{f['node_id']}: {f['type']} -> {f['expected_value']}")
    if not reasons or revised==spec: return None
    return {'scene_spec':revised,'change_summary':'; '.join(reasons)}
