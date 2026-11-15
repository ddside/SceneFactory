import json
import struct
import zlib

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.project import init_project, operate, state, verify_preview, verify_png
from scene_factory.runner import RunnerError
from scene_factory.storage import digest, write_json


def png_bytes(resolution=64):
    def chunk(kind,payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',resolution,resolution,8,6,0,0,0))+
        chunk(b'IDAT',zlib.compress((b'\0'+b'\x80\x80\x80\xff'*resolution)*resolution))+chunk(b'IEND',b''))


@pytest.fixture
def preview_project(tmp_path,monkeypatch):
    project=tmp_path/'example'; init_project(project)
    build=project/'builds'/'previous'; build.mkdir(parents=True)
    (build/'scene.json').write_bytes((project/'scene.json').read_bytes())
    for name in ('scene.blend','result.json','validation.json'): (build/name).write_bytes(b'unit fixture')
    write_json(build/'build.json',{'status':'validated','build_id':'previous','structure_sha256':'a'*64,
        'sha256':{n:digest(build/n) for n in ('scene.json','scene.blend','result.json','validation.json')}})
    write_json(project/'state.json',{'latest':None,'last_successful_build':'previous'})
    def renderer(executable,request,directory,timeout):
        (directory/'preview.png').write_bytes(png_bytes(request['resolution']))
        return {'ok':True,'structure_sha256':'a'*64,'render':{'selected':'cpu'}}
    monkeypatch.setattr('scene_factory.project.run_blender',renderer)
    operate(project,'preview','unit fixture',{**DEFAULTS,'resolution':64})
    return project,build


def test_normal_reference_update_keeps_old_original(preview_project):
    project,build=preview_project
    old=verify_preview(project,build); old_bytes=(project/old['path']).read_bytes()
    snapshot=(build/'preview.png').read_bytes()
    operate(project,'preview','unit fixture',{**DEFAULTS,'resolution':128})
    current=verify_preview(project,build)
    assert current['path']!=old['path'] and current['resolution']==128
    assert (project/old['path']).read_bytes()==old_bytes
    assert (build/'preview.png').read_bytes()==snapshot  # immutable legacy convenience snapshot


def test_atomic_publish_io_failure_preserves_reference(preview_project,monkeypatch):
    import scene_factory.storage as storage
    project,build=preview_project
    published=(build/'preview.json').read_bytes(); previous=verify_preview(project,build)
    snapshot=(build/'preview.png').read_bytes()
    replace=storage.os.replace
    def failing_replace(source,destination):
        if str(destination)==str(build/'preview.json'): raise OSError('injected atomic publication failure')
        return replace(source,destination)
    monkeypatch.setattr(storage.os,'replace',failing_replace)
    with pytest.raises(OSError,match='publication'):
        operate(project,'preview','unit fixture',{**DEFAULTS,'resolution':128})
    assert (build/'preview.json').read_bytes()==published
    assert verify_preview(project,build)==previous
    assert (build/'preview.png').read_bytes()==snapshot
    assert state(project)['latest']['status']=='failed'
    assert state(project)['last_successful_build']=='previous'


@pytest.mark.parametrize('mode',['render_failure','corrupt_png'])
def test_preview_failures_preserve_reference(preview_project,monkeypatch,mode):
    project,build=preview_project; before=(build/'preview.json').read_bytes()
    def failed(executable,request,directory,timeout):
        if mode=='render_failure': raise RunnerError('intentional render failure')
        (directory/'preview.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        return {'structure_sha256':'a'*64,'render':{'selected':'cpu'}}
    monkeypatch.setattr('scene_factory.project.run_blender',failed)
    with pytest.raises((ValueError,RunnerError)):
        operate(project,'preview','unit fixture',{**DEFAULTS,'resolution':64})
    assert (build/'preview.json').read_bytes()==before
    verify_preview(project,build)


@pytest.mark.parametrize('mode',['header_only','truncated','crc','pixels'])
def test_png_corruption_is_rejected(tmp_path,mode):
    data=png_bytes()
    if mode=='header_only': data=data[:24]
    elif mode=='truncated': data=data[:-4]
    elif mode=='crc': data=data[:40]+bytes([data[40]^1])+data[41:]
    else:
        def chunk(k,p): return struct.pack('>I',len(p))+k+p+struct.pack('>I',zlib.crc32(k+p)&0xffffffff)
        data=data[:33]+chunk(b'IDAT',zlib.compress(b'no complete image'))+chunk(b'IEND',b'')
    p=tmp_path/'bad.png'; p.write_bytes(data)
    with pytest.raises(ValueError): verify_png(p,64)
