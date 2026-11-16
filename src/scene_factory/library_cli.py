"""Explicit acquisition commands. Build/compile never call a live Provider."""
from pathlib import Path
from .library import Catalog,material_record,mat_ref,builtins
from .providers import PolyHavenProvider,LocalAssetProvider,Resolution,default_providers
from .spec import read_json

def add_parsers(commands):
    for name in ('assets','materials'):
        root=commands.add_parser(name);root.set_defaults(project='.')
        sub=root.add_subparsers(dest='library_action',required=True)
        actions=('list','search','fetch','local','show') if name=='assets' else ('list','from-asset','add','show')
        for action in actions:
            p=sub.add_parser(action);p.add_argument('--library')
            if action in ('show','from-asset'):p.add_argument('--ref',required=True)
            if name=='assets' and action in ('search','fetch'):p.add_argument('--provider',default='polyhaven')
            if action=='search':p.add_argument('--query',default='');p.add_argument('--type',choices=('textures','models','hdris','all'),default='all');p.add_argument('--category')
            if action=='fetch':p.add_argument('--id',required=True);p.add_argument('--variant',default='1k')
            if action in ('local','add'):p.add_argument('--file',required=True)
            if action=='from-asset':p.add_argument('--id',required=True);p.add_argument('--category',default='surface');p.add_argument('--scale',type=float,default=2)

def execute(args,providers=None):
    c=Catalog(args.library);action=args.library_action;providers=providers or default_providers()
    if args.command=='assets':
        if action=='list':return c.list_assets()
        if action=='show':return c.get_asset(read_json(args.ref))
        if action=='search':
            adapter=providers.get(args.provider);return {'credit':getattr(adapter,'credit',adapter.provider_id),'results':adapter.search(args.query,{'all':None,'textures':'texture','models':'model','hdris':'hdri'}[args.type],args.category)}
        if action=='fetch':return c.ingest(providers.get(args.provider),args.id,args.variant)
        definition=read_json(args.file);resolution=Resolution(**definition)
        if resolution.provider_id!='local':raise ValueError('local manifest provider_id must be local')
        return c.ingest(LocalAssetProvider({resolution.provider_asset_id:resolution}),resolution.provider_asset_id,resolution.variant)
    if action=='list':return [{'record':r,'ref':mat_ref(r)} for r in c.list_materials()]
    if action=='show':return c.get_material(read_json(args.ref))
    if action=='add':return c.put_material(read_json(args.file))
    ref=read_json(args.ref);r=c.get_asset(ref)
    if r['asset_type']!='texture':raise ValueError('PBR texture asset required')
    textures={f['role']:{'asset':ref,'file':f['path'],'color_space':'sRGB' if f['role']=='base_color' else 'Non-Color'} for f in r['files']}
    record=material_record(args.id,args.category,textures=textures,source=ref,scale=[args.scale,args.scale]);record['license']=r['license']
    return {'ref':c.put_material(record),'record':record}
