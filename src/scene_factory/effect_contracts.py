"""Independent disaster-effect intent. Pure validation and stable sample streams."""
import copy,hashlib,random,math
from .spec import fields,identifier,number,SpecError

KINDS=('concrete','plaster','wood','glass','generic')
SURFACES=('soot','scorch','char','discoloration','waterline','mud','wet','fine_crack')
DISASTERS={'earthquake':{'debris','scatter','crack_geometry','surface'},'fire':{'debris','scatter','surface','crack_geometry'},'flood':{'debris','scatter','surface'}}


def vector(value,label):
    if not isinstance(value,list) or len(value)!=3:raise SpecError(label+': finite 3-vector required')
    for x in value:number(x,label,-10000,10000)


def validate(value):
    fields(value,'effects',('schema_version','controller_node_id','items'))
    if type(value['schema_version']) is not int or value['schema_version']!=1:raise SpecError('effects: version 1 required')
    identifier(value['controller_node_id'],'effects.controller')
    if not isinstance(value['items'],list) or not 1<=len(value['items'])<=32:raise SpecError('effects: 1..32 items required')
    ids=set();total=0
    for e in value['items']:
        fields(e,'effect',('effect_id','disaster_type','effect_type','target_node_id','region','severity','seed','material','parameters'),('source_operation_id',))
        for k in ['effect_id','target_node_id','material']:identifier(e[k],'effect.'+k)
        if e['effect_id'] in ids:raise SpecError('effects: duplicate effect ID / double application')
        ids.add(e['effect_id'])
        if e['disaster_type'] not in DISASTERS or e['effect_type'] not in DISASTERS[e['disaster_type']]:raise SpecError('effects: disaster/effect mismatch')
        number(e['severity'],'effect.severity',.01,1)
        if type(e['seed']) is not int or not 0<=e['seed']<=4294967295:raise SpecError('effect.seed: uint32 required')
        if 'source_operation_id' in e:identifier(e['source_operation_id'],'effect.source_operation_id')
        r=e['region'];fields(r,'effect.region',('room_id','minimum','maximum'));identifier(r['room_id'],'effect.region.room_id')
        for k in ['minimum','maximum']:vector(r[k],'effect.region.'+k)
        if any(r['maximum'][i]-r['minimum'][i]<.001 for i in range(3)):raise SpecError('effects: empty/invalid region')
        p=e['parameters']
        if e['effect_type']=='surface':
            fields(p,'surface.parameters',('surface_type','layer','targets','band_width','height','direction'))
            if p['surface_type'] not in SURFACES:raise SpecError('effects: unknown surface type')
            if e['disaster_type']=='earthquake' and p['surface_type'] not in ('fine_crack','mud','discoloration'):raise SpecError('effects: earthquake surface mismatch')
            if e['disaster_type']=='fire' and p['surface_type'] not in ('soot','scorch','char','discoloration'):raise SpecError('effects: fire surface mismatch')
            if e['disaster_type']=='flood' and p['surface_type'] not in ('waterline','mud','wet','discoloration'):raise SpecError('effects: flood surface mismatch')
            if type(p['layer']) is not int or not 0<=p['layer']<=31:raise SpecError('effect layer: integer 0..31')
            if not isinstance(p['targets'],list) or not p['targets'] or len(set(p['targets']))!=len(p['targets']):raise SpecError('surface targets required and unique')
            for nid in p['targets']:identifier(nid,'surface target')
            number(p['band_width'],'surface band_width',.001,1);number(p['height'],'surface height',0,5);vector(p['direction'],'surface direction')
            if p['surface_type']=='fine_crack' and math.sqrt(sum(v*v for v in p['direction']))<1e-6:raise SpecError('effects: fine crack direction required')
        elif e['effect_type']=='crack_geometry':
            fields(p,'crack.parameters',('target_component_id','target_role','minimum','maximum','displacement'))
            for key in ['minimum','maximum','displacement']:vector(p[key],'crack.'+key)
            for k in ['target_component_id','target_role']:identifier(p[k],'crack.'+k)
            if any(p['maximum'][i]-p['minimum'][i]<.003 for i in range(3)):raise SpecError('effects: geometry crack needs nonzero width/depth')
        else:
            fields(p,'distribution.parameters',('fragment_count','density','size_min','size_max','material_type','distribution','extent','direction','irregularity','variants','volume_budget','existing_ids','scatter_skill'),('settle_fraction',))
            if type(p['fragment_count']) is not int or not 0<=p['fragment_count']<=200:raise SpecError('effects: fragment_count 0..200')
            number(p['density'],'effect.density',.01,1)
            if p['material_type'] not in KINDS or p['distribution'] not in ('uniform','clustered','source_based','directional'):raise SpecError('effects: unknown material/distribution')
            for k in ['size_min','size_max','extent','direction']:vector(p[k],'effect.'+k)
            for i in range(3):
                number(p['size_min'][i],'effect size minimum',.003,2);number(p['size_max'][i],'effect size maximum',p['size_min'][i],2)
                number(p['extent'][i],'effect extent',.001,20)
            if p['distribution']=='directional' and math.hypot(*p['direction'][:2])<1e-6:raise SpecError('effects: directional scatter needs nonzero direction')
            number(p['irregularity'],'effect.irregularity',0,.35);number(p['volume_budget'],'effect.volume_budget',.000001,3)
            if type(p['variants']) is not int or not 1<=p['variants']<=8:raise SpecError('effects: 1..8 shape variants')
            if p['scatter_skill'] not in ('product_package','storage_box','monitor'):raise SpecError('effects: unsupported scatter skill')
            if not isinstance(p['existing_ids'],list) or len(set(p['existing_ids']))!=len(p['existing_ids']):raise SpecError('effects: existing_ids must be unique')
            for nid in p['existing_ids']:identifier(nid,'scatter existing id')
            number(p.get('settle_fraction',0),'effect.settle_fraction',0,.8)
            total+=count(e)+len(p['existing_ids'])
    if total>600:raise SpecError('effects: total fragment/scatter budget exceeded (600)')
    return copy.deepcopy(value)


def count(effect):return int(math.floor(effect['parameters']['fragment_count']*effect['parameters']['density']+.5))


def rng(scene_seed,effect,index,stream):
    digest=hashlib.sha256(f'{scene_seed}:{effect["seed"]}:{effect["effect_id"]}:{index}:{stream}'.encode()).digest()
    return random.Random(int.from_bytes(digest,'big'))


def sample(scene_seed,effect,index,anchor,margin):
    """Bounded deterministic generation, not a collision-repair loop."""
    p=effect['parameters'];r=rng(scene_seed,effect,index,'placement');lo=effect['region']['minimum'];hi=effect['region']['maximum']
    bounds=[(lo[i]+margin,hi[i]-margin) for i in range(2)]
    if any(a>b for a,b in bounds):raise SpecError('effects: fragment cannot fit region')
    if p['distribution']=='uniform':xy=[r.uniform(a,b) for a,b in bounds]
    else:
        center=[(a+b)/2 for a,b in bounds] if p['distribution']=='clustered' else [min(b,max(a,anchor[i])) for i,(a,b) in enumerate(bounds)]
        xy=[center[i]+sum(r.uniform(-1,1) for _ in range(4))/4*p['extent'][i]/2 for i in range(2)]
        if p['distribution']=='directional':
            length=math.hypot(*p['direction'][:2]);t=r.random()
            xy=[xy[i]+p['direction'][i]/length*t*p['extent'][i]/2 for i in range(2)]
        xy=[min(b,max(a,xy[i])) for i,(a,b) in enumerate(bounds)]
    return [round(x,8) for x in xy]
