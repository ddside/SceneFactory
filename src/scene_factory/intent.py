"""Versioned user intent, reference provenance and bounded generation policy.

Codex supplies interpretation; this module deliberately does not parse language.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path
import struct

from .contract_utils import check_digest
from .spec import SpecError, fields, identifier, number
from .storage import digest
from .png import verify_png

BUDGET = {"max_attempts":3,"max_seconds":300.,"max_nodes":200,"max_resolution":512,
          "max_samples":16,"no_improvement_limit":1}
CONSTRAINT_TYPES = ("parameter_equals","location_equals","node_count","exists","grounded")


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, path):
    if not isinstance(value,str) or not value.strip():
        raise SpecError(f"{path}: nonempty text required")


def relative_path(project, relative):
    text(relative,"relative_path")
    if Path(relative).is_absolute():
        raise SpecError("relative_path: absolute paths not allowed")
    root=Path(project).resolve(); path=(root/relative).resolve()
    if not path.is_relative_to(root):
        raise SpecError("relative_path: path escapes project")
    return path


def image_metadata(path):
    path=Path(path); size=path.stat().st_size
    if not 0<size<=32*1024*1024:
        raise SpecError("reference image: expected 1..32MB")
    data=path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=33:
        width,height=struct.unpack('>II',data[16:24])
        if not 0<width<=8192 or not 0<height<=8192:
            raise SpecError("reference PNG: unsupported dimensions")
        verify_png(path,(width,height))
        return "PNG", {"width":width,"height":height,"byte_size":size,"verification":"PNG CRC and full image stream"}
    if data.startswith(b'\xff\xd8'):
        position=2
        while position+4<=len(data):
            if data[position]!=255: break
            while position<len(data) and data[position]==255: position+=1
            if position>=len(data): break
            marker=data[position]; position+=1
            if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7: continue
            if position+2>len(data): break
            length=struct.unpack('>H',data[position:position+2])[0]
            if length<2 or position+length>len(data): break
            if marker in (0xc0,0xc1,0xc2):
                if length<8: break
                height,width=struct.unpack('>HH',data[position+3:position+7])
                if 0<width<=8192 and 0<height<=8192:
                    return "JPEG", {"width":width,"height":height,"byte_size":size,
                                    "verification":"JPEG dimensions/header only; visual decode is separate"}
            position+=length
    raise SpecError("reference image: only recognized PNG/JPEG supported")


def validate_intent(value):
    required=("schema_version","intent_id","raw_request","reference_files","observations","assumptions","constraints",
              "unresolved_questions","requested_quality_profile","generation_budget","created_at","unsupported_requests")
    fields(value,"SceneIntent",required)
    if type(value['schema_version']) is not int or value['schema_version']!=1:
        raise SpecError("SceneIntent.schema_version: expected 1")
    identifier(value['intent_id'],'intent_id'); text(value['raw_request'],'raw_request')
    try:
        if datetime.fromisoformat(value['created_at']).tzinfo is None: raise ValueError()
    except (ValueError,TypeError): raise SpecError("created_at: timezone-aware ISO timestamp required")
    if value['requested_quality_profile'] not in ('structural','preview_reviewed','basic_scene','architectural','appearance'):
        raise SpecError("requested_quality_profile: unsupported profile")
    budget=value['generation_budget']; fields(budget,'generation_budget',tuple(BUDGET))
    for key,lo,hi in (('max_attempts',1,10),('max_nodes',1,1000),('max_resolution',32,1024),('max_samples',1,64),('no_improvement_limit',1,10)):
        if type(budget[key]) is not int: raise SpecError(f'generation_budget.{key}: integer required')
        number(budget[key],f'generation_budget.{key}',lo,hi)
    number(budget['max_seconds'],'generation_budget.max_seconds',.001,3600)
    refs={}
    if not isinstance(value['reference_files'],list): raise SpecError('reference_files: array required')
    for ref in value['reference_files']:
        fields(ref,'reference',('reference_id','relative_path','sha256','format','metadata','inspection'))
        identifier(ref['reference_id'],'reference_id'); check_digest(ref['sha256'],'reference.sha256')
        if ref['reference_id'] in refs: raise SpecError('reference_id: duplicate reference')
        if ref['format'] not in ('PNG','JPEG'): raise SpecError('reference.format: unsupported format')
        text(ref['relative_path'],'reference.relative_path')
        if Path(ref['relative_path']).is_absolute() or '..' in Path(ref['relative_path']).parts:
            raise SpecError('reference.relative_path: project-relative path required')
        fields(ref['metadata'],'reference.metadata',('width','height','byte_size','verification'))
        for key in ('width','height','byte_size'):
            if type(ref['metadata'][key]) is not int or ref['metadata'][key]<=0: raise SpecError('reference.metadata: invalid dimensions/size')
        fields(ref['inspection'],'reference.inspection',('state','method','notes'))
        if ref['inspection']['state'] not in ('viewed','not_viewed'): raise SpecError('reference.inspection.state: invalid')
        text(ref['inspection']['method'],'inspection.method'); text(ref['inspection']['notes'],'inspection.notes')
        refs[ref['reference_id']]=ref
    for category in ('observations','assumptions'):
        if not isinstance(value[category],list): raise SpecError(f'{category}: array required')
        for entry in value[category]:
            fields(entry,category,('text','reference_ids'),('confidence',) if category=='assumptions' else ())
            text(entry['text'],category+'.text')
            if not isinstance(entry['reference_ids'],list) or any(not isinstance(x,str) or x not in refs for x in entry['reference_ids']):
                raise SpecError(category+': unknown reference ID')
            if category=='observations' and (not entry['reference_ids'] or any(refs[x]['inspection']['state']!='viewed' for x in entry['reference_ids'])):
                raise SpecError('observations: actual viewed reference required')
            if 'confidence' in entry: number(entry['confidence'],'assumption.confidence',0,1)
    if not isinstance(value['constraints'],list): raise SpecError('constraints: array required')
    seen=set()
    for c in value['constraints']:
        fields(c,'constraint',('constraint_id','type','expected_value','strength','source','confidence','tolerance'),
               ('target_node_id','target_role','property'))
        identifier(c['constraint_id'],'constraint_id')
        if c['constraint_id'] in seen: raise SpecError('constraint_id: duplicate')
        seen.add(c['constraint_id'])
        if ('target_node_id' in c)==('target_role' in c): raise SpecError('constraint: select one node or role')
        if 'target_node_id' in c: identifier(c['target_node_id'],'constraint.target_node_id')
        else:
            role=c['target_role']
            if not isinstance(role,str) or not role.startswith('skill:'): raise SpecError('constraint.target_role: use skill:SKILL_ID')
            identifier(role[6:],'constraint.target_role')
        if c['type'] not in CONSTRAINT_TYPES or c['strength'] not in ('hard','soft'): raise SpecError('constraint: unsupported type/strength')
        number(c['confidence'],'constraint.confidence',0,1); number(c['tolerance'],'constraint.tolerance',0,10000)
        fields(c['source'],'constraint.source',('kind','detail'),('reference_id',))
        if c['source']['kind'] not in ('user','reference','assumption'): raise SpecError('constraint.source.kind: invalid')
        text(c['source']['detail'],'constraint.source.detail')
        if c['source']['kind']=='reference':
            reference_id=c['source'].get('reference_id')
            ref=refs.get(reference_id) if isinstance(reference_id,str) else None
            if not ref or ref['inspection']['state']!='viewed': raise SpecError('reference constraint requires viewed reference')
        if c['type']=='parameter_equals':
            if not isinstance(c.get('property'),str) or not c['property'].isidentifier(): raise SpecError('constraint.property: parameter name required')
            number(c['expected_value'],'constraint.expected_value',-10000,10000)
        elif 'property' in c: raise SpecError('constraint.property: only valid for parameter_equals')
        if c['type']=='location_equals':
            if not isinstance(c['expected_value'],list) or len(c['expected_value'])!=3: raise SpecError('location constraint: 3 values required')
            for x in c['expected_value']: number(x,'constraint.expected_value',-10000,10000)
        elif c['type']=='node_count':
            if type(c['expected_value']) is not int or not 0<=c['expected_value']<=1000: raise SpecError('node_count: invalid expected count')
        elif c['type']=='exists' and type(c['expected_value']) is not bool: raise SpecError('exists: boolean expected')
        elif c['type']=='grounded': number(c['expected_value'],'constraint.expected_value',-10000,10000)
    for category in ('unresolved_questions','unsupported_requests'):
        if not isinstance(value[category],list): raise SpecError(category+': array required')
        for q in value[category]:
            fields(q,category,('text','blocking')); text(q['text'],category+'.text')
            if type(q['blocking']) is not bool: raise SpecError(category+'.blocking: boolean required')
    return copy.deepcopy(value)


def verify_references(project,intent):
    validate_intent(intent)
    for ref in intent['reference_files']:
        path=relative_path(project,ref['relative_path'])
        if not path.is_file() or digest(path)!=ref['sha256']:
            raise SpecError(f"reference {ref['reference_id']}: missing or modified file")
        fmt,metadata=image_metadata(path)
        if fmt!=ref['format'] or metadata!=ref['metadata']: raise SpecError('reference metadata mismatch')
    return intent


def effective_constraints(intent):
    """Keep all provenance, but explicit user values override inferred values."""
    grouped={}
    for c in intent['constraints']:
        key=(c['type'],c.get('target_node_id'),c.get('target_role'),c.get('property'))
        grouped.setdefault(key,[]).append(c)
    result,overridden,conflicts=[],[],[]
    for group in grouped.values():
        user=[c for c in group if c['source']['kind']=='user']
        selected=user if user else group
        overridden.extend(c['constraint_id'] for c in group if c not in selected)
        hard=[c for c in selected if c['strength']=='hard']
        def compatible(a,b):
            av,bv=a['expected_value'],b['expected_value']; tolerance=a['tolerance']+b['tolerance']
            if type(av) in (int,float) and type(bv) in (int,float): return abs(av-bv)<=tolerance
            if isinstance(av,list) and isinstance(bv,list): return all(abs(x-y)<=tolerance for x,y in zip(av,bv))
            return av==bv
        if any(not compatible(a,b) for a in hard for b in hard):
            conflicts.append([c['constraint_id'] for c in hard])
        result.extend(selected)
    return result,overridden,conflicts
