"""Real Blender contracts; tests write only isolated artifact test-run directories."""
import copy
import os
from pathlib import Path
import tempfile

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.compiler import child_id
from scene_factory.project import init_project, latest_build, operate, run_build, state
from scene_factory.registry import Registry
from scene_factory.runner import RunnerError, run_blender
from scene_factory.scene_v2 import example_v2, migrate_file
from scene_factory.spec import example_spec, read_json
from scene_factory.storage import digest, write_json

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def real_context():
    executable=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not executable: pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    root=ROOT/'artifacts'/'test-runs'; root.mkdir(parents=True,exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='phase2a-',dir=root))
    return directory,executable


def build_example(directory,executable):
    project=directory/'example'; init_project(project,2)
    result=run_build(project,executable,DEFAULTS)
    return project,result


def test_v1_v2_shape_and_ids_equivalence(real_context):
    directory,executable=real_context
    v1,v2=directory/'v1',directory/'v2'
    init_project(v1); init_project(v2)
    original=(v1/'scene.json').read_bytes()
    migrated=directory/'migrated.json'; migrate_file(v1/'scene.json',migrated)
    (v2/'scene.json').write_bytes(migrated.read_bytes())
    first=run_build(v1,executable,DEFAULTS); second=run_build(v2,executable,DEFAULTS)
    assert first['structure_sha256']==second['structure_sha256']
    assert (v1/'scene.json').read_bytes()==original
    for project in (v1,v2):
        build,metadata=latest_build(project)
        manifest=read_json(build/'artifact-manifest.json')
        assert manifest['artifact_count']==4 and len(manifest['node_artifacts'])==4
        assert all(a['vertex_count']==8 and a['face_count']==6 for a in manifest['artifacts'])
        assert all(len(ids)==1 for ids in manifest['node_artifacts'].values())


def test_noncuboid_recipe_hierarchy_typed_inputs_preview(real_context):
    directory,executable=real_context
    project=directory/'example'; init_project(project,2)
    source=read_json(project/'scene.json')
    building=next(n for n in source['nodes'] if n['node_id']=='building.main')
    building['parameters']['height']=4.5
    building['transform']={'location':[10,2,1],'rotation_degrees':[0,0,90],'scale':[2,1,1.2]}
    write_json(project/'scene.json',source)
    run_build(project,executable,DEFAULTS)
    build,meta=latest_build(project); plan=read_json(build/'plan.json')
    manifest=read_json(build/'artifact-manifest.json')
    assert manifest['artifact_count']==7
    assert len(manifest['node_artifacts']['building.main'])==5
    cylinder=next(a for a in manifest['artifacts'] if a['source_node_id']=='column.side')
    assert (cylinder['vertex_count'],cylinder['face_count'])==(32,18)
    assert [cylinder['world_matrix'][i][3] for i in range(3)]==pytest.approx([12,10,1])
    roof=next(n for n in plan['nodes'] if n['node_id']==child_id('building.main','roof'))
    assert roof['resolved_transform']['location'][2]==pytest.approx(4.7)
    assert roof['resolved_inputs']['elevation']['value']==4.5
    assert plan['execution_order'].index(child_id('building.main','wall')) < plan['execution_order'].index(roof['node_id'])
    preview=operate(project,'preview',executable,{**DEFAULTS,'resolution':128,'samples':2})
    assert (Path(preview['directory'])/'preview.png').stat().st_size>24
    assert operate(project,'validate',executable,DEFAULTS)['reopened']
    assert read_json(build/'quality.json')['stages']['visual']['state']=='not_run'
    assert read_json(build/'quality.json')['acceptance']=='not_evaluated'
    assert not (build/'preview.png').exists()  # no legacy copy for native v2


def test_reproducibility_and_insertion_stability(real_context):
    directory,executable=real_context
    project,first=build_example(directory,executable)
    first_dir,_=latest_build(project)
    manifest1=read_json(first_dir/'artifact-manifest.json')
    plan1=read_json(first_dir/'plan.json')
    source=read_json(project/'scene.json'); source['nodes'].reverse()
    write_json(project/'scene.json',source)
    second=run_build(project,executable,DEFAULTS)
    assert first['structure_sha256']==second['structure_sha256']
    source['nodes'].append({'node_id':'unrelated','skill':{'skill_id':'pillar','version':'1.0.0'},
                            'transform':{'location':[8,8,0]},'parameters':{}})
    write_json(project/'scene.json',source); run_build(project,executable,DEFAULTS)
    third_dir,_=latest_build(project)
    manifest3=read_json(third_dir/'artifact-manifest.json'); plan3=read_json(third_dir/'plan.json')
    before={a['artifact_id']:a for a in manifest1['artifacts']}
    after={a['artifact_id']:a for a in manifest3['artifacts']}
    for aid,a in before.items():
        assert after[aid]['geometry_digest']==a['geometry_digest'] and after[aid]['world_matrix']==a['world_matrix']
    seeds={n['node_id']:n['node_seed'] for n in plan3['nodes']}
    assert all(seeds[n['node_id']]==n['node_seed'] for n in plan1['nodes'])


@pytest.mark.parametrize('mutation',['missing','unexpected','geometry','parent','rename'])
def test_actual_reopened_artifact_contract(real_context,mutation):
    directory,executable=real_context
    project,result=build_example(directory,executable); build,_=latest_build(project)
    script=directory/'mutate.py'; changed=directory/'changed.blend'
    body={
        'missing':'bpy.data.objects.remove(o,do_unlink=True)',
        'unexpected':'bpy.ops.mesh.primitive_cube_add()',
        'geometry':'o.data.vertices[0].co.x += 1',
        'parent':'o.parent = None',
        'rename':'o.name="arbitrary.001"; o.data.name="other.009"',
    }[mutation]
    script.write_text('import bpy,json,sys\nfrom pathlib import Path\n'
        f'bpy.ops.wm.open_mainfile(filepath={str(build/"scene.blend")!r})\n'
        'o=next(o for o in bpy.context.scene.objects if o.get("source_node_id")=="column.side")\n'
        f'{body}\n'
        f'bpy.ops.wm.save_as_mainfile(filepath={str(changed)!r})\n'
        'Path(sys.argv[-1]).write_text(json.dumps({"ok":True}))\n')
    run_blender(executable,{},directory/'mutate',worker=script)
    request={'action':'validate','spec_path':str(build/'scene.json'),'plan_path':str(build/'plan.json'),
             'plan_digest':read_json(build/'plan.json')['plan_digest'],'blend_path':str(changed)}
    if mutation=='rename':
        checked=run_blender(executable,request,directory/'check')
        assert checked['structure_sha256']==result['structure_sha256']
        assert any(a['reference']['object']=='arbitrary.001' for a in checked['artifact_manifest']['artifacts'])
    else:
        with pytest.raises(RunnerError): run_blender(executable,request,directory/'check')
    latest_build(project)


def test_failed_v2_build_preserves_previous(real_context,monkeypatch):
    import scene_factory.project as module
    directory,executable=real_context
    project,result=build_example(directory,executable); build,metadata=latest_build(project)
    before=dict(metadata['sha256']); script=directory/'failure.py'
    script.write_text('import bpy\nraise RuntimeError("intentional Phase 2A worker failure")\n')
    monkeypatch.setattr(module,'run_blender',lambda executable,request,directory,timeout:
                        run_blender(executable,request,directory,timeout,worker=script))
    with pytest.raises(RunnerError): run_build(project,executable,DEFAULTS)
    assert state(project)['last_successful_build']==result['build_id']
    assert latest_build(project)[1]['sha256']==before
    failed=project/state(project)['latest']['directory']
    assert read_json(failed/'quality.json')['stages']['execution']['state']=='failed'


def test_legacy_planless_build_remains_readable(real_context):
    directory,executable=real_context
    project=directory/'legacy'; init_project(project)
    build=project/'builds'/'legacy'; build.mkdir(parents=True)
    (build/'scene.json').write_bytes((project/'scene.json').read_bytes())
    request={'action':'build','spec_path':str(build/'scene.json')}
    original=run_blender(executable,request,build)
    checked=run_blender(executable,{**request,'action':'validate','blend_path':str(build/'scene.blend')},build/'reopen')
    write_json(build/'validation.json',checked)
    write_json(build/'build.json',{'status':'validated','build_id':'legacy','structure_sha256':original['structure_sha256'],
        'sha256':{name:digest(build/name) for name in ('scene.json','scene.blend','result.json','validation.json')}})
    write_json(project/'state.json',{'latest':None,'last_successful_build':'legacy'})
    before=digest(build/'scene.blend')
    assert latest_build(project)[1]['build_id']=='legacy'
    assert operate(project,'validate',executable,DEFAULTS)['structure_sha256']==original['structure_sha256']
    operate(project,'preview',executable,{**DEFAULTS,'resolution':64,'samples':1})
    assert digest(build/'scene.blend')==before and not (build/'plan.json').exists()
