"""Opt-in live API tests. Run separately; never count a network skip as success."""
import hashlib,json,os,socket,time,urllib.error
from pathlib import Path
import tempfile
import pytest
from scene_factory.providers import PolyHavenProvider
from scene_factory.library import Catalog
from scene_factory.project import init_project,run_build,operate
from scene_factory.resources import verify_resources
from scene_factory.storage import write_json
from scene_factory.config import DEFAULTS

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.environ.get('SCENE_FACTORY_TEST_POLYHAVEN')!='1',reason='explicit live Poly Haven opt-in required')

@pytest.fixture(scope='module')
def live():
    provider=PolyHavenProvider();catalog=Catalog();selection=json.loads((ROOT/'examples/appearance/polyhaven-selection.json').read_text())
    directory=ROOT/'artifacts/phase3b-live-test';directory.mkdir(exist_ok=True)
    return provider,catalog,selection,directory


def test_ph1_live_search_metadata_and_variants(live):
    p,c,s,d=live;metrics={}
    for query,kind,key in [('concrete','textures','concrete'),('wood','textures','wood'),('rock','models','rock')]:
        started=time.monotonic();results=p.search(query,kind);metrics[query]=time.monotonic()-started
        assert s[key]['provider_asset_id'] in {r['provider_asset_id'] for r in results}
        metadata=p.get_metadata(s[key]['provider_asset_id']);assert metadata['name']
        assert any(v['resolution']=='1k' for v in p.list_variants(s[key]['provider_asset_id']))
        write_json(d/('search-'+query+'.json'),results)
    write_json(d/'search-performance.json',metrics)


def test_ph2_ph5_live_acquisition_and_cache(live):
    p,c,s,d=live;results={}
    for key,selected in s.items():
        first=c.ingest(p,selected['provider_asset_id'],'1k');second=c.ingest(p,selected['provider_asset_id'],'1k')
        assert first['ref']==selected['asset_ref']
        assert second['cache_hit'] and second['download_bytes']==0
        record=c.get_asset(first['ref'])
        for file in record['files']:
            data=(c.root/record['local_cache_path']/file['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest()==file['sha256']
            if file['provider_checksum']:assert hashlib.md5(data).hexdigest()==file['provider_checksum']['value']
        if key!='rock':assert c.material_from_asset(first['ref'],'ph.'+key,key,scale=[2,2])['ref']==selected['material_ref']
        results[key]={'first':first,'cache_reuse':second}
    write_json(d/'acquisition.json',results)


def test_ph3_ph4_ph6_real_assets_build_and_preview_without_provider(live,monkeypatch):
    p,c,s,d=live;exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    assert exe,'live Blender E2E requires SCENE_FACTORY_TEST_BLENDER'
    # Pin all inputs first; no request is allowed in the build/preview phase.
    for key,selected in s.items():
        c.get_asset(selected['asset_ref'])
        if key!='rock':c.get_material(selected['material_ref'])
    def offline(*args,**kwargs):raise AssertionError('network attempted during offline build')
    monkeypatch.setattr(PolyHavenProvider,'_request',offline);monkeypatch.setattr(socket,'create_connection',offline)
    project=Path(tempfile.mkdtemp(prefix='offline-',dir=d));project.rmdir();init_project(project,2)
    source=json.loads((ROOT/'examples/appearance/scene-c-request.json').read_text())['scene_spec'];write_json(project/'scene.json',source)
    options={**DEFAULTS,'resolution':64,'samples':1,'timeout':300}
    built=run_build(project,exe,options);path=Path(built['directory']);plan=json.loads((path/'plan.json').read_text());verify_resources(path,plan['resources'])
    result=operate(project,'preview',exe,{**options,'denoise':True,'view_direction':[1,-1.4,1.6],'hide_groups':['cover','south_wall']})
    assert result['ok'] and result['artifact_count']>40 and (Path(result['directory'])/'preview.png').is_file()
    write_json(d/'offline-e2e.json',{'build':built['build_id'],'project':str(project),'preview':result['directory'],'performance':result['performance']})


def test_ph7_live_invalid_id_and_api_failure_leave_accepted_unchanged(live,monkeypatch):
    p,c,s,d=live;project=ROOT/'artifacts/phase3b-scene-b';state=project/'state.json'
    assert state.is_file(),'manual accepted scene required before this live acceptance check'
    before=state.read_bytes();assert json.loads(before).get('accepted')
    with pytest.raises(urllib.error.HTTPError) as missing:
        PolyHavenProvider().get_metadata('scene_factory_deliberately_missing_asset_987654321')
    assert missing.value.code==404
    def outage(*a,**k):raise TimeoutError('injected API outage')
    monkeypatch.setattr(p,'opener',outage)
    with pytest.raises(TimeoutError):p.get_metadata('uncached-outage-probe')
    assert json.loads(state.read_bytes())['accepted']==json.loads(before)['accepted']
