"""Immutable provider-neutral asset/material catalogs with atomic cache publication."""
import copy,hashlib,json,os,shutil,tempfile,time
from urllib.parse import urlsplit,parse_qsl
from pathlib import Path
from datetime import datetime,timezone
from .contract_utils import canonical_digest,check_digest
from .library_contracts import (asset_ref,material_ref,validate_material,validate_license,license_record,relative,PARAMETERS)
from .storage import write_json,digest,project_lock
from .spec import read_json,identifier
from .format_adapters import FORMATS


def reject_credentials(value):
    forbidden={'authorization','password','api_key','access_token','refresh_token','client_secret','cookie'}
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).lower() in forbidden:raise ValueError('credentials must not be stored in catalog metadata')
            reject_credentials(item)
    elif isinstance(value,list):
        for item in value:reject_credentials(item)
    elif isinstance(value,str) and '://' in value:
        parsed=urlsplit(value)
        if parsed.username or parsed.password or any(k.lower() in forbidden for k,v in parse_qsl(parsed.query)):
            raise ValueError('credential-bearing resource URI rejected')


def default_library():return Path(os.environ.get('SCENE_FACTORY_LIBRARY','artifacts/asset-library')).expanduser().resolve()
def ref_for(record):return {k:record[k] for k in ('asset_id','provider_id','version','variant','content_hash')}
def mat_ref(record):return {'material_id':record['material_id'],'version':record['version'],'content_hash':canonical_digest(record)}


def material_record(mid,category,parameters=None,textures=None,source=None,scale=None,license_info=None):
    return {'schema_version':1,'material_id':mid,'version':'1.0.0','display_name':mid,'category':category,
        'parameters':{**copy.deepcopy(PARAMETERS),**({'base_color':[1.,1.,1.,1.]} if textures else {}),**(parameters or {})},'texture_references':textures or {},'texture_scale':scale or [2,2],
        'provider_id':source['provider_id'] if source else 'local','source_asset_id':source['asset_id'] if source else None,
        'license':license_info or license_record('UNKNOWN',False) if source else license_record(),'provenance':{'source_asset':source,'author':'Scene Factory procedural material' if not source else 'See source asset'},
        'validation_status':'validated','surface_state':{}}


def builtins():
    colors={'concrete':([.48,.46,.43,1],.82,0,0),'painted_wall':([.78,.77,.72,1],.65,0,0),
      'wood':([.3,.12,.045,1],.4,0,0),'metal':([.55,.58,.61,1],.25,1,0),'glass':([.95,.98,1,1],.06,0,1),
      'ceramic_tile':([.57,.6,.62,1],.28,0,0),'asphalt':([.055,.06,.065,1],.95,0,0),'plaster':([.72,.7,.65,1],.88,0,0)}
    return {name:material_record(name,name,{'base_color':c,'roughness':r,'metallic':m,'transmission':t}) for name,(c,r,m,t) in colors.items()}

class Catalog:
    def __init__(self,root=None):self.root=Path(root or default_library()).resolve()
    def _index(self):return read_json(self.root/'index.json') if (self.root/'index.json').exists() else {'schema_version':1,'assets':{},'materials':{}}
    def _get(self,kind,ref):
        entry=self._index()[kind].get(canonical_digest(ref))
        if not entry:raise ValueError('unknown '+kind+' ID/version/variant/hash')
        p=self.root/relative(entry['path'])
        if not p.is_file() or digest(p)!=entry['sha256']:raise ValueError('catalog record corruption')
        return read_json(p)
    def get_asset(self,ref,verify=True):
        asset_ref(ref);r=self._get('assets',ref)
        if ref_for(r)!=ref:raise ValueError('AssetRef mismatch')
        validate_license(r['license'])
        if r['validation_status']!='validated' or r['license']['verification_status']=='unknown':raise ValueError('asset/license unverified')
        if verify:
            self.verify_asset(r)
            if r['format']=='pbr':
                from .intent import image_metadata
                for f in r['files']:
                    fmt,meta=image_metadata(self.root/r['local_cache_path']/f['path']);f['image_metadata']={'format':fmt,**meta}
        return r
    def verify_asset(self,r):
        base=self.root/relative(r['local_cache_path'])
        for f in r['files']:
            p=base/relative(f['path'])
            if not p.is_file() or p.stat().st_size!=f['size'] or digest(p)!=f['sha256']:raise ValueError('cache corruption/missing dependency: '+f['path'])
        if canonical_digest([{k:f[k] for k in ('path','sha256','size')} for f in r['files']])!=r['content_hash']:raise ValueError('asset content hash mismatch')
        if r['format']=='pbr':
            from .intent import image_metadata
            for f in r['files']:
                fmt,meta=image_metadata(base/f['path'])
                if 'image_metadata' in f and f['image_metadata']!={'format':fmt,**meta}:raise ValueError('texture image metadata mismatch')
        if r['format'] in FORMATS:
            adapter=FORMATS[r['format']];actual=adapter['inspector'](base,r['entrypoint'])
            if actual!=r['source_metadata'][adapter['metadata_key']]:raise ValueError('import metadata mismatch')
        return r
    def _publish(self,kind,ref,record,index):
        key=canonical_digest(ref);path=f'records/{kind}/{key}.json';p=self.root/path
        if p.exists():
            if read_json(p)!=record:raise ValueError('immutable catalog collision')
        else:write_json(p,record)
        index[kind][key]={'path':path,'sha256':digest(p)}
        write_json(self.root/'index.json',index)
    def ingest(self,provider,asset_id,variant='1k'):
        started=time.monotonic();resolution=provider.validate(provider.resolve(asset_id,variant));validate_license(resolution.license)
        reject_credentials({'metadata':resolution.source_metadata,'source_uri':resolution.source_uri,'files':resolution.files})
        if resolution.provider_id!=provider.provider_id:raise ValueError('provider identity mismatch')
        resolution_seconds=time.monotonic()-started
        self.root.mkdir(parents=True,exist_ok=True)
        with project_lock(self.root):
            index=self._index()
            for entry in index['assets'].values():
                old=read_json(self.root/entry['path'])
                if (old['provider_id'],old['provider_asset_id'],old['version'],old['variant'])==(provider.provider_id,asset_id,resolution.version,variant):
                    result=self.get_asset(ref_for(old));return {'record':result,'ref':ref_for(result),'cache_hit':True,'seconds':time.monotonic()-started,'download_bytes':0,'download_seconds':0.,'resolution_seconds':resolution_seconds}
            temp=Path(tempfile.mkdtemp(prefix='.staging-',dir=self.root))
            try:
                transfer_started=time.monotonic();files=[];seen=set()
                for f in resolution.files:
                    path=relative(f['path'])
                    if path in seen:raise ValueError('duplicate dependency path')
                    seen.add(path);target=temp/path;target.parent.mkdir(parents=True,exist_ok=True)
                    provider.materialize(f,target)
                    if not target.is_file() or target.stat().st_size!=f['size'] or not 0<f['size']<=256*1024*1024:raise ValueError('incomplete download/file size mismatch')
                    checksum=f.get('provider_checksum')
                    if checksum:
                        if checksum['algorithm'] not in ('md5','sha256'):raise ValueError('unsupported provider checksum')
                        if hashlib.new(checksum['algorithm'],target.read_bytes()).hexdigest()!=checksum['value']:raise ValueError('provider checksum mismatch')
                    files.append({'path':path,'uri':f['uri'],'size':f['size'],'sha256':digest(target),'provider_checksum':checksum,'role':f['role']})
                download_seconds=time.monotonic()-transfer_started
                files.sort(key=lambda f:f['path']);content=canonical_digest([{k:f[k] for k in ('path','sha256','size')} for f in files]);metadata=copy.deepcopy(resolution.source_metadata)
                bounds=None
                if resolution.format in FORMATS:
                    adapter=FORMATS[resolution.format];inspection=adapter['inspector'](temp,resolution.entrypoint);metadata[adapter['metadata_key']]=inspection;bounds=inspection['bounding_box']
                elif resolution.format=='pbr':
                    from .intent import image_metadata
                    for f in files:image_metadata(temp/f['path'])
                aid=provider.provider_id+'.'+hashlib.sha256(asset_id.encode()).hexdigest()[:24]
                record={'schema_version':1,'asset_id':aid,'provider_id':provider.provider_id,'provider_asset_id':asset_id,'version':resolution.version,'asset_type':resolution.asset_type,
                    'source_uri':resolution.source_uri,'source_metadata':metadata,'format':resolution.format,'variant':variant,'local_cache_path':'objects/'+content,'content_hash':content,
                    'dependencies':[f['path'] for f in files if f['path']!=resolution.entrypoint],'license':resolution.license,'attribution':resolution.attribution,
                    'units':resolution.units,'up_axis':resolution.up_axis,'bounding_box':bounds,'validation_status':'validated' if resolution.license['verification_status']!='unknown' else 'unverified',
                    'validation_stages':{'files':'passed','format':'passed' if resolution.format in (*FORMATS,'pbr') else 'not_run','import':'not_run'},
                    'files':files,'entrypoint':resolution.entrypoint,'retrieved_at':datetime.now(timezone.utc).isoformat()}
                if record['units'] not in ('m','cm') or record['up_axis'] not in ('Y','Z'):raise ValueError('unsupported asset units/up axis metadata')
                destination=self.root/record['local_cache_path'];destination.parent.mkdir(exist_ok=True)
                if destination.exists():
                    for f in files:
                        if digest(destination/f['path'])!=f['sha256']:raise ValueError('existing immutable cache corrupted')
                else:os.replace(temp,destination)
                self._publish('assets',ref_for(record),record,index)
                return {'record':record,'ref':ref_for(record),'cache_hit':False,'seconds':time.monotonic()-started,'download_bytes':sum(f['size'] for f in files),'download_seconds':download_seconds,'resolution_seconds':resolution_seconds}
            finally:
                if temp.exists():shutil.rmtree(temp)
    def put_material(self,record):
        validate_material(record)
        source=record['provenance'].get('source_asset')
        if source:
            asset=self.get_asset(source)
            if record['license']!=asset['license']:raise ValueError('material must retain source asset license/terms')
        for t in record['texture_references'].values():
            a=self.get_asset(t['asset'])
            if t['file'] not in {f['path'] for f in a['files']}:raise ValueError('texture dependency missing')
        self.root.mkdir(parents=True,exist_ok=True);ref=mat_ref(record)
        with project_lock(self.root):self._publish('materials',ref,record,self._index())
        return ref
    def get_material(self,ref):
        material_ref(ref)
        for record in builtins().values():
            if mat_ref(record)==ref:return validate_material(record)
        record=self._get('materials',ref)
        if mat_ref(record)!=ref:raise ValueError('MaterialRef hash mismatch')
        validate_material(record)
        source=record['provenance'].get('source_asset')
        if source and self.get_asset(source)['license']!=record['license']:raise ValueError('source license/terms mismatch')
        return record
    def material_from_asset(self,ref,mid,category='surface',scale=None):
        asset=self.get_asset(ref)
        if asset['asset_type']!='texture':raise ValueError('texture asset required')
        from .library_contracts import CHANNELS
        textures={f['role']:{'asset':ref,'file':f['path'],'color_space':'sRGB' if f['role']=='base_color' else 'Non-Color'}
                  for f in asset['files'] if f['role'] in CHANNELS}
        if not textures:raise ValueError('asset contains no supported texture channels')
        record=material_record(mid,category,textures=textures,source=ref,scale=scale,license_info=asset['license'])
        return {'ref':self.put_material(record),'record':record}
    def list_assets(self):return [read_json(self.root/e['path']) for e in self._index()['assets'].values()]
    def list_materials(self):return list(builtins().values())+[read_json(self.root/e['path']) for e in self._index()['materials'].values()]
