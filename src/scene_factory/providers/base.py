"""Small provider contract. Resolved files may be URLs, files, or future URIs."""
from dataclasses import dataclass

@dataclass
class Resolution:
    provider_id: str
    provider_asset_id: str
    version: str
    asset_type: str
    source_uri: str
    source_metadata: dict
    format: str
    variant: str
    files: list
    license: dict
    attribution: str
    units: str='m'
    up_axis: str='Z'
    entrypoint: str|None=None

class Provider:
    provider_id='abstract'
    capabilities=frozenset()
    def supports(self,operation):return operation in self.capabilities
    def search(self,query='',asset_type=None,category=None):raise NotImplementedError('search unsupported')
    def get_metadata(self,asset_id):raise NotImplementedError('metadata unsupported')
    def list_variants(self,asset_id):raise NotImplementedError('variants unsupported')
    def resolve(self,asset_id,variant):raise NotImplementedError('resolve unsupported')
    def download(self,file,destination):raise NotImplementedError('transfer unsupported')
    def materialize(self,file,destination):
        if not self.supports('download'):raise NotImplementedError('file materialization unsupported')
        return self.download(file,destination)
    def validate(self,resolution):return resolution

class Providers:
    def __init__(self,*providers):self.adapters={p.provider_id:p for p in providers}
    def register(self,provider):
        if provider.provider_id in self.adapters:raise ValueError('duplicate Provider ID')
        self.adapters[provider.provider_id]=provider
    def get(self,provider_id):
        if provider_id not in self.adapters:raise ValueError('unknown Provider ID: '+str(provider_id))
        return self.adapters[provider_id]
