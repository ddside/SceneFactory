"""Provider-neutral immutable resource contracts, shared with Blender Python 3.11."""
from pathlib import PurePosixPath
from .spec import fields,identifier,number,SpecError
from .contract_utils import canonical_digest,check_digest,check_version,normalize_transform

CHANNELS=('base_color','roughness','metallic','normal','height')
PARAMETERS={'base_color':[.6,.6,.6,1], 'roughness':.6,'metallic':0.,'transmission':0.,'ior':1.5,'normal_strength':1.,'bump_distance':.02}


def relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or '%' in value or PurePosixPath(value).is_absolute() or any(x in ('..','.') for x in value.split('/')):
        raise SpecError('resource path must be a safe relative POSIX path')
    return value


def license_record(identifier_='CC0-1.0',verified=True,provider_terms=''):
    return {'license_id':identifier_,'license_url':'https://creativecommons.org/publicdomain/zero/1.0/' if identifier_=='CC0-1.0' else 'urn:license:'+identifier_,
      'commercial_use':'allowed' if verified else 'unknown','redistribution':'allowed' if verified else 'unknown',
      'attribution_required':identifier_!='CC0-1.0','provider_terms':provider_terms,'authentication_requirements':'none',
      'access_restrictions':[],'verification_status':'verified' if verified else 'unknown'}


def validate_license(v):
    fields(v,'license',('license_id','license_url','commercial_use','redistribution','attribution_required','provider_terms','authentication_requirements','access_restrictions','verification_status'))
    for k in ('license_id','license_url','provider_terms','authentication_requirements'):
        if not isinstance(v[k],str) or (k!='provider_terms' and not v[k]): raise SpecError('invalid license '+k)
    if type(v['attribution_required']) is not bool or v['verification_status'] not in ('verified','user_declared','unknown'):
        raise SpecError('invalid license verification/attribution')
    for k in ('commercial_use','redistribution'):
        if v[k] not in ('allowed','restricted','unknown'): raise SpecError('invalid license conditions')
    if not isinstance(v['access_restrictions'],list) or not all(isinstance(x,str) for x in v['access_restrictions']): raise SpecError('invalid license restrictions')
    return v


def asset_ref(v):
    fields(v,'AssetRef',('asset_id','provider_id','version','variant','content_hash'))
    for k in ('asset_id','provider_id','variant'): identifier(v[k],'AssetRef.'+k)
    if not isinstance(v['version'],str) or not v['version']: raise SpecError('asset version required')
    check_digest(v['content_hash'],'AssetRef hash');return v


def material_ref(v):
    fields(v,'MaterialRef',('material_id','version','content_hash'));identifier(v['material_id'],'material_id');check_version(v['version'],'material version');check_digest(v['content_hash'],'material hash');return v


def validate_material(v):
    fields(v,'MaterialRecord',('schema_version','material_id','version','display_name','category','parameters','texture_references','texture_scale','provider_id','source_asset_id','license','provenance','validation_status','surface_state'))
    if v['schema_version']!=1: raise SpecError('material schema version')
    identifier(v['provider_id'],'material provider');identifier(v['material_id'],'material_id');check_version(v['version'],'material version');validate_license(v['license'])
    if v['validation_status']!='validated' or v['license']['verification_status']=='unknown': raise SpecError('material/license is unverified')
    if v['source_asset_id'] is None and v['provider_id']!='local':raise SpecError('material provider without source provenance')
    if v['surface_state']!={}: raise SpecError('surface state layering not implemented')
    p=v['parameters'];fields(p,'PBR',tuple(PARAMETERS))
    if not isinstance(p['base_color'],list) or len(p['base_color'])!=4: raise SpecError('PBR base_color requires RGBA')
    for x in p['base_color']: number(x,'color',0,1)
    for k in ('roughness','metallic','transmission'): number(p[k],k,0,1)
    number(p['ior'],'ior',1,3);number(p['normal_strength'],'normal_strength',0,2);number(p['bump_distance'],'bump_distance',0,.1)
    uv_scale(v['texture_scale'])
    if not isinstance(v['texture_references'],dict): raise SpecError('texture references must be an object')
    for channel,t in v['texture_references'].items():
        if channel not in CHANNELS: raise SpecError('unsupported texture channel')
        fields(t,'TextureRef',('asset','file','color_space'));asset_ref(t['asset']);relative(t['file'])
        if t['color_space']!=('sRGB' if channel=='base_color' else 'Non-Color'): raise SpecError('incorrect texture color space')
    return v


def uv_scale(v):
    if not isinstance(v,list) or len(v)!=2: raise SpecError('texture scale requires two meter values')
    for x in v: number(x,'texture meters per repeat',.01,100)
    return v


def appearance(v):
    fields(v,'Appearance',('schema_version','materials','bindings'))
    if v['schema_version']!=1 or not isinstance(v['materials'],dict) or not isinstance(v['bindings'],list): raise SpecError('invalid appearance schema')
    for alias,ref in v['materials'].items():identifier(alias,'material alias');material_ref(ref)
    for b in v['bindings']:
        fields(b,'MaterialBinding',('node_id','role','material','uv'),('region',))
        identifier(b['node_id'],'binding node');identifier(b['role'],'binding role')
        if b['material'] not in v['materials']: raise SpecError('unknown Material ID alias')
        fields(b['uv'],'UV',('meters_per_repeat','rotation_degrees'));uv_scale(b['uv']['meters_per_repeat']);number(b['uv']['rotation_degrees'],'UV rotation',-360,360)
        if 'region' in b:
            r=b['region'];fields(r,'material region',('xmin','xmax','ymin','ymax'))
            for x in r.values():number(x,'region',-1000,1000)
            if r['xmin']>=r['xmax'] or r['ymin']>=r['ymax']:raise SpecError('invalid material region')
    return v
