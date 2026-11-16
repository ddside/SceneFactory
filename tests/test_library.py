"""Offline provider/catalog/policy tests. Fake assets do not prove Poly Haven E2E."""
import copy,io,json,hashlib,struct,zlib,shutil
from pathlib import Path
import pytest
from scene_factory.providers import FakeProvider,LocalAssetProvider,PolyHavenProvider,Providers,Resolution
from scene_factory.library import Catalog,material_record,builtins,mat_ref
from scene_factory.library_contracts import license_record,validate_material,appearance
from scene_factory.gltf_contract import inspect_gltf
from scene_factory.resources import resolve_resources,stage_resources,verify_resources
from scene_factory.compiler import compile_scene
from scene_factory.registry import Registry

SOURCE=Path(__file__).resolve().parents[1]/'src/scene_factory/fixtures/source/hierarchy.gltf'
ALL=tuple(s for s,v in Registry().manifests)


def fixture_provider(tmp_path,provider_type=FakeProvider,license=None,format='gltf'):
    tmp_path.mkdir(parents=True,exist_ok=True);target=tmp_path/'hierarchy.gltf';shutil.copyfile(SOURCE,target)
    r=Resolution(provider_type.provider_id,'same-name','v1','model','urn:test:asset',{'hierarchy':['root','red','blue'],'layers':[],'references':[],'payloads':[]},format,'original',
      [{'path':'hierarchy.gltf','uri':str(target),'size':target.stat().st_size,'provider_checksum':None,'role':'model'}],license or license_record(),'Test-only fixture','m','Y','hierarchy.gltf')
    return provider_type({'same-name':r})


def png():
    def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x90\x70\x50'*2)*2))+chunk(b'IEND',b'')


def texture_provider(tmp_path,license=None):
    p=tmp_path/'color.png';p.write_bytes(png());r=Resolution('fake','texture','1','texture','urn:fixture',{},'pbr','original',
      [{'path':'color.png','uri':str(p),'size':p.stat().st_size,'provider_checksum':None,'role':'base_color'}],license or license_record(),'test')
    return FakeProvider({'texture':r})


def test_mp1_provider_registration_and_capabilities(tmp_path):
    fake=fixture_provider(tmp_path);providers=Providers(LocalAssetProvider());providers.register(fake)
    assert providers.get('fake').search('same')[0]['provider_asset_id']=='same-name'
    assert fake.get_metadata('same-name')['hierarchy'] and fake.list_variants('same-name')==['original']
    assert fake.supports('resolve') and not fake.supports('http') and not fake.supports('download')
    with pytest.raises(ValueError):providers.get('unknown')
    with pytest.raises(ValueError):providers.register(fake)


def test_mp2_mp3_provider_neutral_catalog_and_namespace(tmp_path):
    c=Catalog(tmp_path/'catalog');refs=[]
    for provider in (FakeProvider,LocalAssetProvider):
        p=fixture_provider(tmp_path/provider.provider_id,provider);result=c.ingest(p,'same-name','original');refs.append(result['ref'])
        assert c.get_asset(result['ref'])['source_metadata']['gltf']['parts'][1]['type']=='Mesh'
    assert refs[0]['asset_id']!=refs[1]['asset_id']
    assert len(c.list_assets())==2


def test_mp4_non_cc0_and_unknown_licenses_are_not_rewritten(tmp_path):
    license=license_record('CC-BY-4.0');c=Catalog(tmp_path/'catalog');r=c.ingest(texture_provider(tmp_path,license),'texture','original')
    m=c.material_from_asset(r['ref'],'by-material');assert m['record']['license']==license
    r2=c.ingest(fixture_provider(tmp_path/'unknown',license=license_record('UNKNOWN',False)),'same-name','original')
    assert r2['record']['license']['license_id']=='UNKNOWN'
    with pytest.raises(ValueError,match='unverified'):c.get_asset(r2['ref'])


def test_mp5_hierarchy_metadata_retained(tmp_path):
    r=Catalog(tmp_path/'c').ingest(fixture_provider(tmp_path/'s'),'same-name','original')['record']
    parts=r['source_metadata']['gltf']['parts']
    assert len(parts)==3 and sum(p['type']=='Mesh' for p in parts)==2
    assert [p['parent_role'] for p in parts]==['frame','part0000','part0000']
    assert r['bounding_box']==[[0.,-1.,0.],[3.,0.,1.]]


def test_mp6_usd_metadata_is_representable_but_has_no_import_adapter(tmp_path):
    c=Catalog(tmp_path/'c');provider=fixture_provider(tmp_path/'s',format='usda')
    provider.entries['same-name'].source_metadata.update(layers=[{'uri':'omniverse://example.invalid/World.usda','format':'usda'}],
        references=[{'asset_uri':'omniverse://example.invalid/prop.usd','prim_path':'/Root'}],
        payloads=[{'uri':'urn:test:payload','load':'deferred'}],material_bindings=[{'prim':'/Root','material':'urn:test:material'}],
        prototypes=[{'name':'prototype0','instances':['a','b']}])
    result=c.ingest(provider,'same-name','original');r=c.get_asset(result['ref'])
    assert r['format']=='usda' and r['source_metadata']['layers'][0]['uri'].startswith('omniverse:') and r['source_metadata']['payloads'][0]['load']=='deferred'
    assert r['validation_stages']['format']=='not_run'
    s={'schema_version':2,'scene_id':'future','seed':1,'units':'m','nodes':[{'node_id':'asset','skill':{'skill_id':'asset_instance','version':'1.0.0'},'asset_ref':result['ref'],'parameters':{},'transform':{}}]}
    with pytest.raises(ValueError,match='import adapter'):compile_scene(s,resources=resolve_resources(s,c),allow_candidates=ALL)


def test_cache_hit_offline_freeze_and_corruption(tmp_path,monkeypatch):
    c=Catalog(tmp_path/'c');p=fixture_provider(tmp_path/'source');a=c.ingest(p,'same-name','original')
    monkeypatch.setattr(p,'materialize',lambda *a:pytest.fail('duplicate transfer'))
    b=c.ingest(p,'same-name','original');assert b['cache_hit'] and b['download_bytes']==0
    s={'nodes':[{'asset_ref':a['ref']}]};bundle=resolve_resources(s,c);stage_resources(tmp_path/'build',bundle,c)
    shutil.rmtree(c.root);verify_resources(tmp_path/'build',bundle)
    file=tmp_path/'build/resources'/a['record']['local_cache_path']/'hierarchy.gltf';file.write_bytes(b'broken')
    with pytest.raises(ValueError,match='corruption'):verify_resources(tmp_path/'build',bundle)

@pytest.mark.parametrize('case',['size','checksum','missing','transfer','license','axis','duplicate','format'])
def test_acquisition_failures_are_not_published(tmp_path,case):
    c=Catalog(tmp_path/'c');p=fixture_provider(tmp_path/'s');r=p.entries['same-name']
    if case=='size':r.files[0]['size']+=1
    elif case=='checksum':r.files[0]['provider_checksum']={'algorithm':'sha256','value':'0'*64}
    elif case=='missing':Path(r.files[0]['uri']).unlink()
    elif case=='transfer':p.materialize=lambda *a:(_ for _ in ()).throw(OSError('injected download failure'))
    elif case=='license':r.license={'license_id':'CC0'}
    elif case=='axis':r.up_axis='unknown'
    elif case=='duplicate':r.files.append(copy.deepcopy(r.files[0]))
    elif case=='format':Path(r.files[0]['uri']).write_text('{}');r.files[0]['size']=2
    with pytest.raises((ValueError,OSError,AssertionError,KeyError)):c.ingest(p,'same-name','original')
    assert not c.list_assets() and not list(c.root.glob('.staging-*'))

@pytest.mark.parametrize('case',['material_id','roughness','metallic','transmission','ior','normal','bump','scale','color','state','provider','license','channel','space'])
def test_scene_e_material_rejections(case):
    m=material_record('test','surface')
    if case=='material_id':m['material_id']='bad/id'
    elif case in ('roughness','metallic','transmission'):m['parameters'][case]=2
    elif case=='ior':m['parameters']['ior']=0
    elif case=='normal':m['parameters']['normal_strength']=-1
    elif case=='bump':m['parameters']['bump_distance']=1
    elif case=='scale':m['texture_scale']=[0,1]
    elif case=='color':m['parameters']['base_color'][0]=float('nan')
    elif case=='state':m['surface_state']={'damage':1}
    elif case=='provider':m['provider_id']='unknown'
    elif case=='license':m['license']['verification_status']='unknown'
    elif case=='channel':m['texture_references']={'mystery':{}}
    else:m['texture_references']={'normal':{'asset':{'asset_id':'a','provider_id':'p','version':'1','variant':'v','content_hash':'0'*64},'file':'normal.png','color_space':'sRGB'}}
    with pytest.raises(ValueError):validate_material(m)


def test_eight_builtins_and_immutable_material_versions(tmp_path):
    c=Catalog(tmp_path);assert len(builtins())==8
    for m in builtins().values():assert c.get_material(mat_ref(m))==m
    a=material_record('custom','paint');ra=c.put_material(a);b=copy.deepcopy(a);b['parameters']['roughness']=.2;rb=c.put_material(b)
    assert ra!=rb and c.get_material(ra)==a and c.get_material(rb)==b

@pytest.mark.parametrize('case',['missing_asset','version','hash','uv','uv_rotation','missing_material','missing_texture'])
def test_scene_e_reference_rejections(tmp_path,case):
    c=Catalog(tmp_path/'c');r=c.ingest(texture_provider(tmp_path),'texture','original');m=c.material_from_asset(r['ref'],'material')
    ref=copy.deepcopy(r['ref'])
    if case=='missing_asset':ref['asset_id']='missing'
    elif case=='version':ref['version']='different'
    elif case=='hash':ref['content_hash']='0'*64
    if case in ('missing_asset','version','hash'):
        with pytest.raises(ValueError):c.get_asset(ref)
    elif case=='missing_texture':
        bad=copy.deepcopy(m['record']);bad['texture_references']['base_color']['file']='missing.png'
        with pytest.raises(ValueError):c.put_material(bad)
    else:
        a={'schema_version':1,'materials':{'base':m['ref']},'bindings':[{'node_id':'wall','role':'geometry','material':'base','uv':{'meters_per_repeat':[2,2],'rotation_degrees':0}}]}
        if case=='uv':a['bindings'][0]['uv']['meters_per_repeat']=[-1,2]
        elif case=='uv_rotation':a['bindings'][0]['uv']['rotation_degrees']=float('inf')
        else:a['bindings'][0]['material']='missing'
        with pytest.raises(ValueError):appearance(a)


def test_polyhaven_response_normalization_user_agent_and_dependencies(tmp_path):
    calls=[]
    info={'type':2,'name':'Test model','files_hash':'version','authors':{}}
    files={'gltf':{'1k':{'gltf':{'url':'https://dl.polyhaven.org/test.gltf','size':10,'md5':'a'*32,'include':{'textures/t.png':{'url':'https://dl.polyhaven.org/t.png','size':20,'md5':'b'*32}}}}}}
    def opener(request,timeout):
        calls.append(request);value=info if '/info/' in request.full_url else files
        return io.BytesIO(json.dumps(value).encode())
    p=PolyHavenProvider(opener=opener);r=p.resolve('real-from-test-response','1k')
    assert len(r.files)==2 and r.format=='gltf' and r.up_axis=='Y' and r.license['license_id']=='CC0-1.0'
    assert all('SceneFactory' in r.headers['User-agent'] for r in calls)
    assert 'Attribution' not in r.license or r.license['attribution_required'] is False
    assert 'User-Agent' in r.license['provider_terms']

@pytest.mark.parametrize('exception',[TimeoutError('timeout'),OSError('HTTP failure'),ValueError('malformed API')])
def test_polyhaven_failure_is_not_success(exception):
    def fail(*a,**k):raise exception
    p=PolyHavenProvider(opener=fail)
    with pytest.raises(type(exception)):p.get_metadata('not-found')

@pytest.mark.parametrize('uri',['../escape.bin','https://remote/model.bin','/absolute.bin','..%2fescape.bin'])
def test_gltf_does_not_resolve_unlisted_remote_or_escaped_dependencies(tmp_path,uri):
    doc=json.loads(SOURCE.read_text());doc['buffers'][0]['uri']=uri;p=tmp_path/'a.gltf';p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):inspect_gltf(tmp_path,'a.gltf')


def test_material_only_revision_changes_no_geometry_ids_or_seeds(tmp_path):
    from scene_factory.architecture_layout import building_scene
    from scene_factory.appearance_layout import apply_building_materials
    from scene_factory.workflow_store import diff_specs
    c=Catalog(tmp_path);ref=c.put_material(material_record('surface','paint'))
    a=apply_building_materials(building_scene(),ref,ref,ref);b=copy.deepcopy(a)
    dark=material_record('surface.dark','tile',{'base_color':[.1,.1,.1,1]});darkref=c.put_material(dark)
    b['appearance']['materials']['tile']=darkref
    diff=diff_specs(a,b);assert not diff['changed_nodes'] and set(diff['root_changes'])=={'appearance'}
    pa=compile_scene(a,resources=resolve_resources(a,c),allow_candidates=ALL)['build_plan']
    pb=compile_scene(b,resources=resolve_resources(b,c),allow_candidates=ALL)['build_plan']
    assert {n['node_id']:n['node_seed'] for n in pa['nodes']}=={n['node_id']:n['node_seed'] for n in pb['nodes']}
    assert pa['expected_artifacts']==pb['expected_artifacts']

@pytest.mark.parametrize('case',['node','role','duplicate','no_base','overlap'])
def test_binding_errors_fail_pure_compile(tmp_path,case):
    c=Catalog(tmp_path);ref=c.put_material(material_record('surface','paint'))
    s={'schema_version':2,'scene_id':'binding','seed':1,'units':'m','nodes':[{'node_id':'ground','skill':{'skill_id':'ground','version':'1.0.0'},'parameters':{},'transform':{}}],
      'appearance':{'schema_version':1,'materials':{'surface':ref},'bindings':[{'node_id':'ground','role':'geometry','material':'surface','uv':{'meters_per_repeat':[1,1],'rotation_degrees':0}}]}}
    b=s['appearance']['bindings'][0]
    if case=='node':b['node_id']='missing'
    elif case=='role':b['role']='missing'
    elif case=='duplicate':s['appearance']['bindings'].append(copy.deepcopy(b))
    elif case=='no_base':b['region']={'xmin':0,'xmax':1,'ymin':0,'ymax':1}
    else:
        r=copy.deepcopy(b);r['region']={'xmin':0,'xmax':1,'ymin':0,'ymax':1};r2=copy.deepcopy(r);r2['region']['xmin']=.5;s['appearance']['bindings']+=[r,r2]
    with pytest.raises(ValueError):compile_scene(s,resources=resolve_resources(s,c),allow_candidates=ALL)

@pytest.mark.parametrize('case',['metadata','uri'])
def test_credentials_are_not_persisted(tmp_path,case):
    p=fixture_provider(tmp_path/'source');r=p.entries['same-name']
    if case=='metadata':r.source_metadata['api_key']='not-a-real-secret-test-value'
    else:r.source_uri='https://user:password@example.invalid/asset'
    c=Catalog(tmp_path/'catalog')
    with pytest.raises(ValueError,match='credential'):c.ingest(p,'same-name','original')
    assert not (c.root/'index.json').exists()


def test_polyhaven_keyword_search_also_matches_declared_categories():
    def opener(request,timeout):
        return io.BytesIO(json.dumps({'brown_planks_03':{'name':'Brown Planks 03','tags':['planks'],'categories':['wood'],'category':'Wood/Boards'}}).encode())
    p=PolyHavenProvider(opener=opener)
    assert p.search('wood','textures')[0]['provider_asset_id']=='brown_planks_03'


def test_asset_placement_respects_explicit_ground_elevation():
    from scene_factory.appearance_layout import add_asset_instances
    ref={'asset_id':'fake.asset','provider_id':'fake','version':'1','variant':'original','content_hash':'0'*64}
    bounds=[[-1,-1,-.25],[1,1,1]]
    spec=add_asset_instances({'nodes':[]},ref,bounds,[(0,0),(2,0)],.5,ground_z=-.2)
    for n in spec['nodes']:
        assert n['transform']['location'][2]+bounds[0][2]*n['transform']['scale'][2]==pytest.approx(-.2)


def test_cli_accepts_registered_fake_provider_without_catalog_changes(tmp_path):
    from scene_factory.cli import parser
    from scene_factory.library_cli import execute
    provider=fixture_provider(tmp_path/'source');providers=Providers(provider)
    search=parser().parse_args(['assets','search','--provider','fake','--query','same','--type','models','--library',str(tmp_path/'catalog')])
    assert execute(search,providers)['results'][0]['provider_id']=='fake'
    args=parser().parse_args(['assets','fetch','--provider','fake','--id','same-name','--variant','original','--library',str(tmp_path/'catalog')])
    result=execute(args,providers);assert result['ref']['provider_id']=='fake'
