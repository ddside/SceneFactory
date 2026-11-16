"""Resolve refs without provider access, freeze portable build inputs, verify offline."""
import copy,shutil
from pathlib import Path
from .library import Catalog,ref_for,mat_ref
from .library_contracts import appearance,asset_ref,relative,validate_material
from .contract_utils import canonical_digest
from .storage import write_json,digest


def resolve_resources(spec,catalog=None):
    if 'appearance' not in spec and not any('asset_ref' in n for n in spec.get('nodes',[])):return None
    catalog=catalog or Catalog();bundle={'schema_version':1,'assets':{},'materials':{}}
    def asset(ref):
        key=canonical_digest(ref)
        if key not in bundle['assets']:bundle['assets'][key]=catalog.get_asset(ref)
    for n in spec.get('nodes',[]):
        if 'asset_ref' in n:asset(n['asset_ref'])
    if 'appearance' in spec:
        appearance(spec['appearance'])
        for alias,ref in spec['appearance']['materials'].items():
            m=catalog.get_material(ref);bundle['materials'][alias]=m
            for t in m['texture_references'].values():asset(t['asset'])
            if m['provenance'].get('source_asset'):asset(m['provenance']['source_asset'])
    validate_bundle(spec,bundle);return bundle


def validate_bundle(spec,bundle):
    if bundle is None:
        if 'appearance' in spec or any('asset_ref' in n for n in spec.get('nodes',[])):raise ValueError('resource catalog snapshot required for pure compile')
        return
    if set(bundle)!= {'schema_version','assets','materials'} or bundle['schema_version']!=1:raise ValueError('resource snapshot schema')
    needed=set()
    for n in spec.get('nodes',[]):
        if 'asset_ref' in n:needed.add(canonical_digest(n['asset_ref']))
    expected=spec.get('appearance',{}).get('materials',{})
    if set(expected)!=set(bundle['materials']):raise ValueError('material catalog snapshot mismatch')
    for alias,ref in expected.items():
        m=validate_material(bundle['materials'][alias])
        if mat_ref(m)!=ref:raise ValueError('MaterialRef version/hash mismatch')
        needed.update(canonical_digest(t['asset']) for t in m['texture_references'].values())
        if m['provenance'].get('source_asset'):needed.add(canonical_digest(m['provenance']['source_asset']))
    if needed!=set(bundle['assets']):raise ValueError('asset dependency snapshot mismatch')
    for key,r in bundle['assets'].items():
        if canonical_digest(asset_ref(ref_for(r)))!=key:raise ValueError('AssetRef version/hash mismatch')
        if r['license']['verification_status']=='unknown' or r['validation_status']!='validated':raise ValueError('unverified asset license/cache')
        relative(r['local_cache_path'])
        if canonical_digest([{k:f[k] for k in ('path','sha256','size')} for f in r['files']])!=r['content_hash']:raise ValueError('asset content hash mismatch')
    for m in bundle['materials'].values():
        source=m['provenance'].get('source_asset')
        if source and bundle['assets'][canonical_digest(source)]['license']!=m['license']:raise ValueError('source license/terms mismatch')
        for t in m['texture_references'].values():
            r=bundle['assets'][canonical_digest(t['asset'])]
            if t['file'] not in {f['path'] for f in r['files']}:raise ValueError('missing texture dependency')


def resource_files(bundle):
    return ['resources.json']+[str(Path('resources')/r['local_cache_path']/f['path']) for r in bundle['assets'].values() for f in r['files']]


def stage_resources(directory,bundle,catalog=None):
    if bundle is None:return
    catalog=catalog or Catalog();directory=Path(directory)
    for record in bundle['assets'].values():
        catalog.verify_asset(record)
        for f in record['files']:
            relative(f['path']);src=catalog.root/record['local_cache_path']/f['path'];dst=directory/'resources'/record['local_cache_path']/f['path']
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    write_json(directory/'resources.json',bundle)
    verify_resources(directory,bundle)


def verify_resources(directory,bundle):
    if bundle is None:return
    catalog=Catalog(Path(directory)/'resources')
    for r in bundle['assets'].values():catalog.verify_asset(r)
