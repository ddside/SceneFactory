"""Real Blender interior build/reopen tests; visual acceptance remains a human/Codex action."""
import copy,json,os,shutil,subprocess,tempfile
from pathlib import Path
import pytest
from scene_factory.registry import PACKAGE,Registry
from scene_factory.interior_layout import interior_scene,apply_materials,edit_office,item
from scene_factory.compiler import child_id
from scene_factory.resources import resolve_resources
from scene_factory.project import init_project,run_build,operate,build_at
from scene_factory.storage import write_json
from scene_factory.config import DEFAULTS

ROOT=Path(__file__).resolve().parents[1]
OPTIONS={**DEFAULTS,'resolution':64,'samples':1,'timeout':180}

@pytest.fixture(scope='module')
def runtime():
    exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not exe:pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    outputs=ROOT/'artifacts/test-runs';outputs.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='phase3c-',dir=outputs));shutil.copytree(PACKAGE/'fixtures/library',root/'library')
    with pytest.MonkeyPatch.context() as m:
        m.setenv('SCENE_FACTORY_LIBRARY',str(root/'library'))
        yield root,exe


def with_local_asset(s):
    rid='building.main.room.01';nid=rid+'.furniture.local-sculpture'
    item(s,nid,'asset_instance',rid,(3.07,3.7,1.1),support=dict(kind='on_top',node_id=child_id(rid+'.furniture.cabinet','top')))
    s['nodes'][-1]['asset_ref']=copy.deepcopy(Registry().manifests[('asset_instance','1.0.0')]['test_scenes'][0]['nodes'][0]['asset_ref'])
    s['nodes'][-1]['transform']['scale']=[.1]*3
    return s

@pytest.fixture(scope='module')
def built(runtime):
    root,exe=runtime;results={}
    for kind in ['living','office','retail']:
        s=interior_scene(kind)
        if kind=='living':s=with_local_asset(s)
        s=apply_materials(s,resolve_resources(s));project=root/kind;init_project(project,2);write_json(project/'scene.json',s)
        result=run_build(project,exe,OPTIONS);build,_=build_at(project,result['build_id'])
        validated=operate(project,'validate',exe,OPTIONS,build_id=result['build_id'])
        results[kind]=(project,result,build,validated)
    return results

@pytest.mark.parametrize('kind',['living','office','retail'])
def test_actual_interior_mesh_pbr_and_reopened_domain(runtime,built,kind):
    project,result,build,validated=built[kind]
    data=json.loads((build/'validation.json').read_text());domain=next(r for r in data['domain_results'] if r['kind']=='interior')
    assert domain['state']=='passed' and domain['furniture_count']>0
    assert any(r['kind']=='appearance' and r['state']=='passed' for r in data['domain_results'])
    assert validated['ok']
    plan=json.loads((build/'plan.json').read_text());manifest=json.loads((build/'artifact-manifest.json').read_text())
    assert any(a['lineage'] and a['type']=='Mesh' for a in manifest['artifacts'])
    if kind=='living':assert any('asset' in a for a in manifest['artifacts'])
    else:assert any(i['source']['skill_id']=='filing_cabinet' for i in domain['items'])
    assert plan['interior_metadata']['furniture_count']==domain['furniture_count']


def test_actual_shared_meshes_and_ceiling_preview_metadata(runtime,built):
    root,exe=runtime;build=built['office'][2];script=root/'inspect.py';out=root/'inspection.json'
    script.write_text('''import bpy,json,sys
from pathlib import Path
bpy.ops.wm.open_mainfile(filepath=sys.argv[-2],load_ui=False,use_scripts=False)
parts=[o for o in bpy.context.scene.objects if o.get('generator')=='furniture_part']
lights=[o for o in parts if o.get('preview_group')=='cover']
Path(sys.argv[-1]).write_text(json.dumps(dict(parts=len(parts),meshes=len({o.data.name for o in parts}),lights=len(lights),hidden=any(o.hide_render for o in parts))))
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(build/'scene.blend'),str(out)],capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(out.read_text());assert data['meshes']<data['parts']/2 and data['lights']==6 and not data['hidden']


def test_actual_four_workstation_edit_keeps_unrelated_geometry(runtime,built):
    root,exe=runtime;project,result,build,_=built['office'];original=json.loads((project/'scene.json').read_text())
    edited=edit_office(original);write_json(project/'scene.json',edited)
    after=run_build(project,exe,OPTIONS);target,_=build_at(project,after['build_id']);operate(project,'validate',exe,OPTIONS,build_id=after['build_id'])
    a,b=[json.loads((p/'artifact-manifest.json').read_text()) for p in [build,target]]
    aa,bb=[{x['artifact_id']:x for x in m['artifacts']} for m in [a,b]]
    assert all(aa[k]['geometry_digest']==bb[k]['geometry_digest'] for k in aa.keys() & bb.keys())
    assert (build/'scene.blend').is_file() and build!=target

@pytest.mark.parametrize('mutation',['normals','state','material'])
def test_actual_corrupted_furniture_is_rejected_after_save_reopen(runtime,built,mutation):
    root,exe=runtime;build=built['living'][2];script=root/('corrupt-'+mutation+'.py');out=root/(mutation+'.json')
    script.write_text('''import bpy,bmesh,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[-4])
from scene_factory.registry import Registry
from scene_factory.blender.validation import validate_scene
from scene_factory.blender.interior import validate
root=Path(sys.argv[-3]);mode=sys.argv[-2];out=Path(sys.argv[-1]);plan=json.loads((root/'plan.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(root/'scene.blend'),load_ui=False,use_scripts=False)
obj=next(o for o in bpy.context.scene.objects if o.get('generator')=='furniture_part')
if mode=='normals':
 bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.reverse_faces(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
elif mode=='state':obj['component_state']='fallen'
else:obj.data.materials.clear()
p=out.with_suffix('.blend');bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(p))
bpy.ops.wm.open_mainfile(filepath=str(p),load_ui=False,use_scripts=False)
try:validate_scene(plan,Registry(),domain_validators=(validate,),resource_root=root)
except ValueError as exc:out.write_text(json.dumps(dict(rejected=str(exc))))
else:raise AssertionError('corrupted furniture passed')
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(build),mutation,str(out)],capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(out.read_text())['rejected']
