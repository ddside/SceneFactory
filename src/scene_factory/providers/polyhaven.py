"""Poly Haven API response interpretation stays entirely in this adapter.

API attribution: assets from Poly Haven (https://polyhaven.com).
"""
import json
import urllib.request
import urllib.parse
from .base import Provider,Resolution
from ..library_contracts import license_record

class PolyHavenProvider(Provider):
    provider_id='polyhaven'
    capabilities=frozenset(('search','get_metadata','list_variants','resolve','download','validate','materialize'))
    credit='Assets from Poly Haven — https://polyhaven.com'
    def __init__(self,timeout=30,opener=None):self.timeout=timeout;self.opener=opener or urllib.request.urlopen;self._metadata={};self._files={}
    def _request(self,url):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('api.polyhaven.com','dl.polyhaven.org'):raise ValueError('untrusted Poly Haven URL')
        return self.opener(urllib.request.Request(url,headers={'User-Agent':'SceneFactory/0.5.0 (Poly Haven integration)'}),timeout=self.timeout)
    def _json(self,path):
        with self._request('https://api.polyhaven.com/'+path) as r:return json.loads(r.read(16*1024*1024))
    def search(self,query='',asset_type=None,category=None):
        args={'type':{'texture':'textures','model':'models','hdri':'hdris'}.get(asset_type,asset_type) or 'all'}
        if category:args['category']=category
        data=self._json('assets?'+urllib.parse.urlencode(args));self._metadata.update(data)
        return [{'provider_id':self.provider_id,'provider_asset_id':k,'name':v['name'],'source_uri':'https://polyhaven.com/a/'+k,'credit':self.credit} for k,v in data.items() if query.lower() in (k+' '+v['name']+' '+str(v.get('tags',[]))+' '+str(v.get('categories',[]))+' '+str(v.get('category',''))).lower()]
    def get_metadata(self,asset_id):
        if asset_id not in self._metadata:self._metadata[asset_id]=self._json('info/'+urllib.parse.quote(asset_id,safe=''))
        return self._metadata[asset_id]
    def list_variants(self,asset_id):
        if asset_id not in self._files:self._files[asset_id]=self._json('files/'+urllib.parse.quote(asset_id,safe=''))
        data=self._files[asset_id];return [{'map':m,'resolution':res,'format':fmt} for m,variants in data.items() if isinstance(variants,dict) for res,formats in variants.items() if isinstance(formats,dict) for fmt,item in formats.items() if isinstance(item,dict) and 'url' in item]
    def resolve(self,asset_id,variant='1k'):
        metadata=self.get_metadata(asset_id);self.list_variants(asset_id);data=self._files[asset_id]
        files=[];typ={0:'hdri',1:'texture',2:'model'}[metadata['type']];entrypoint=None
        def add(path,item,role):files.append({'path':path,'uri':item['url'],'size':item['size'],'provider_checksum':{'algorithm':'md5','value':item['md5']} if item.get('md5') else None,'role':role})
        if typ=='texture':
            for channel,key in [('base_color','Diffuse'),('roughness','Rough'),('normal','nor_gl'),('height','Displacement')]:
                if key not in data:continue
                options=data[key].get(variant,{})
                if not options:raise ValueError('resolution/map unavailable')
                fmt='png' if channel=='normal' and 'png' in options else 'jpg'
                if fmt not in options:raise ValueError('unsupported PBR texture format')
                add(channel+'.'+fmt,options[fmt],channel)
            if not {'base_color','roughness','normal'}.issubset({f['role'] for f in files}):raise ValueError('required PBR map missing')
            fmt='pbr';axis='Z'
        elif typ=='model':
            item=data.get('gltf',{}).get(variant,{}).get('gltf')
            if not item:raise ValueError('glTF variant unavailable; no silent format fallback')
            entrypoint='model.gltf';add(entrypoint,item,'model')
            for path,dependency in item.get('include',{}).items():add(path,dependency,'dependency')
            fmt='gltf';axis='Y'
        else:
            item=data.get('hdri',{}).get(variant,{}).get('hdr')
            if not item:raise ValueError('HDR variant unavailable')
            entrypoint='world.hdr';add(entrypoint,item,'hdri');fmt='hdr';axis='Z'
        # Metadata API dimensions are millimeters; record only as provenance.
        return Resolution(self.provider_id,asset_id,metadata.get('files_hash') or str(metadata.get('date_published')),typ,'https://polyhaven.com/a/'+asset_id,
            {k:v for k,v in metadata.items() if k in ('name','authors','dimensions','categories','tags','files_hash','date_published')},fmt,variant,files,
            license_record(provider_terms='https://github.com/Poly-Haven/Public-API/blob/master/ToS.md; unique User-Agent and live-API source credit required'),self.credit,'m',axis,entrypoint)
    def download(self,file,destination):
        with self._request(file['uri']) as response,open(destination,'wb') as stream:
            actual=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                actual+=len(chunk)
                if actual>min(file['size']+1,256*1024*1024):raise ValueError('download exceeds declared size/budget')
                stream.write(chunk)
