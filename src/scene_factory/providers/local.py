"""Explicitly licensed local resources. No HTTP/download assumption in the catalog."""
from pathlib import Path
import shutil
from .base import Provider,Resolution

class LocalAssetProvider(Provider):
    provider_id='local'
    capabilities=frozenset(('search','get_metadata','list_variants','resolve','validate','materialize'))
    def __init__(self,entries=None):self.entries=entries or {}
    def search(self,query='',asset_type=None,category=None):
        return [{'provider_id':self.provider_id,'provider_asset_id':k,'name':v.source_metadata.get('name',k),'source_uri':v.source_uri,'credit':v.attribution}
                for k,v in self.entries.items() if query.lower() in (k+' '+str(v.source_metadata)).lower() and (asset_type is None or v.asset_type==asset_type)]
    def get_metadata(self,asset_id):return self.resolve(asset_id,'original').source_metadata
    def list_variants(self,asset_id):return [self.entries[asset_id].variant]
    def resolve(self,asset_id,variant):
        if asset_id not in self.entries:raise ValueError('local Asset Not Found')
        r=self.entries[asset_id]
        if variant!=r.variant:raise ValueError('local variant mismatch')
        return r
    def materialize(self,file,destination):
        # Local file resolution/copy, not an HTTP operation or advertised download capability.
        shutil.copyfile(Path(file['uri']),destination)

class FakeProvider(LocalAssetProvider):
    """Offline contract fixture, never a substitute for live Poly Haven evidence."""
    provider_id='fake'
