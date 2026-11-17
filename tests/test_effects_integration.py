"""Real Blender effects, replay, immutable baseline reuse and corruption checks."""
import copy,json,os,subprocess,tempfile
from pathlib import Path
import pytest
from scene_factory.effect_layout import prepare_materials,with_effects,debris,surface,region,acceptance_scene
from scene_factory.interior_layout import interior_scene,apply_materials
from scene_factory.project import init_project,run_build,operate,build_at
from scene_factory.storage import write_json
from scene_factory.config import DEFAULTS
from scene_factory.workflow import start

ROOT=Path(__file__).resolve().parents[1]
OPTIONS={**DEFAULTS,'resolution':64,'samples':1,'timeout':900}

@pytest.fixture(scope='module')
def runtime():
    exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not exe:pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    base=ROOT/'artifacts/test-runs';base.mkdir(exist_ok=True,parents=True)
    return Path(tempfile.mkdtemp(prefix='phase3e-',dir=base)),exe


def scene(count=16):
    s=prepare_materials(apply_materials(interior_scene('living')));rid='building.main.room.01';area=region(rid,[-3,1,0],[0,3.5,1])
    e=debris('chips','earthquake',rid+'.furniture.shelf',area,count=count,distribution='uniform')
    f=surface('water','flood',rid+'.furniture.cabinet',['building.main.wall.north'],region(rid,[-3.8,-3.8,0],[3.8,3.8,3]),kind='waterline')
    return with_effects(s,[e,f])


def build(runtime,name,spec):
    root,exe=runtime;project=root/name;init_project(project,2);write_json(project/'scene.json',spec)
    r=run_build(project,exe,OPTIONS);d,_=build_at(project,r['build_id'])
    return project,d,json.loads((d/'artifact-manifest.json').read_text()),json.loads((d/'result.json').read_text())

@pytest.fixture(scope='module')
def small(runtime):return build(runtime,'small',scene())


def test_reopen_region_material_sharing_and_cache_edit(runtime,small):
    project,d,manifest,result=small;_,exe=runtime
    checked=operate(project,'validate',exe,OPTIONS)
    domain=next(x for x in checked['domain_results'] if x['kind']=='effects')
    assert domain['state']=='passed' and domain['reproducible']
    assert result['performance']['unique_mesh_count']<result['performance']['mesh_count']
    first={a['artifact_id']:a for a in manifest['artifacts']}
    s=scene(8);s['effects']['items'][0]['parameters']['distribution']='clustered';write_json(project/'scene.json',s)
    r=run_build(project,exe,OPTIONS);new,_=build_at(project,r['build_id']);second=json.loads((new/'artifact-manifest.json').read_text())
    assert json.loads((new/'result.json').read_text())['base_reused'] is True
    assert all(first[a['artifact_id']]['geometry_digest']==a['geometry_digest'] for a in second['artifacts'])
    assert all(first[a['artifact_id']].get('appearance')==a.get('appearance') for a in second['artifacts'])
    assert build_at(project,d.name)[0]==d

@pytest.mark.parametrize('fraction,state',[(.01,'passed'),(.15,'passed'),(.6,'failed')])
def test_contact_policy_no_unnecessary_repair(runtime,fraction,state):
    root,exe=runtime;s=acceptance_scene('F');s['effects']['items']=s['effects']['items'][:1]
    s['effects']['items'][0]['parameters']['settle_fraction']=fraction
    c=start(root/('contact-'+str(fraction)),dict(raw_request='Test-only disaster contact policy',scene_spec=s,change_summary='Measured contact policy',requested_quality_profile='disaster_interior',generation_budget=dict(max_seconds=1800,max_attempts=2)),exe,OPTIONS)
    assert len(c['build_attempts'])==1
    assert c['quality_runs'][-1]['stages']['domain']['state']==state
    assert c['presentation']['status']==('candidate_not_accepted' if state=='failed' else 'awaiting_visual_review')
    assert c['accepted'] is None
    if state=='failed':assert c['active_workflow']['status']=='needs_repair'

@pytest.mark.parametrize('mode',['zero','normals','buried','outside','duplicate','layers','side_effect','seed','double'])
def test_saved_corruption_and_double_application_rejected(runtime,small,mode):
    root,exe=runtime;d=small[1];script=root/('corrupt-'+mode+'.py');out=root/(mode+'.json')
    script.write_text('''import bpy,bmesh,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[-4])
from scene_factory.blender.effect_runtime import validate_saved,apply_effects
from scene_factory.registry import Registry
root=Path(sys.argv[-3]);mode=sys.argv[-2];out=Path(sys.argv[-1]);plan=json.loads((root/'plan.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(root/'scene.blend'),load_ui=False,use_scripts=False)
obj=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('effect_origin'))
if mode in ['zero','normals']:
 obj.data=obj.data.copy();bm=bmesh.new();bm.from_mesh(obj.data)
 if mode=='zero':
  for v in bm.verts:v.co.z=0
 else:bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
 bm.to_mesh(obj.data);bm.free()
elif mode=='buried':obj.location.z-=1
elif mode=='outside':obj.location.x+=100
elif mode=='duplicate':
 other=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('effect_origin') and o!=obj);other.matrix_world=obj.matrix_world.copy();other.data=obj.data
elif mode=='layers':
 target=next(o for o in bpy.context.scene.objects if o.get('effect_layers'));target.material_slots[0].material.node_tree.nodes['effect.water.water_height'].inputs[1].default_value=2
elif mode=='side_effect':
 target=next(o for o in bpy.context.scene.objects if o.type=='MESH' and not o.get('effect_origin'));target.data=target.data.copy();target.data.vertices[0].co.z+=.1
elif mode=='seed':obj['node_seed']='forged-seed'
bpy.context.view_layer.update()
if mode!='double':
 path=out.with_suffix('.blend');bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(path));bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False,use_scripts=False)
try:
 if mode=='double':apply_effects(plan,Registry(),root,None)
 else:validate_saved(plan,Registry(),root)
except ValueError as e:out.write_text(json.dumps(dict(rejected=str(e))))
else:raise AssertionError(mode+' accepted')
''')
    r=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(d),mode,str(out)],capture_output=True,text=True,timeout=900)
    script.with_suffix('.log').write_text(r.stdout+r.stderr)
    assert r.returncode==0,r.stdout+r.stderr
    assert json.loads(out.read_text())['rejected']


def test_failed_effect_build_preserves_previous_validated(runtime,small):
    root,exe=runtime;project=small[0]
    from scene_factory.project import state
    previous=state(project)['last_successful_build']
    bad=scene();bad['effects']['items'][0]['parameters']['fragment_count']=100000;write_json(project/'scene.json',bad)
    with pytest.raises(ValueError):run_build(project,exe,OPTIONS)
    assert state(project)['last_successful_build']==previous


def test_baseline_snapshot_hash_is_protected(runtime,small):
    import shutil
    root,_=runtime;source,d,_,_=small;copy_project=root/'cache-corruption'
    shutil.copytree(source,copy_project)
    target=copy_project/'builds'/d.name/'base-state.json'
    target.write_text(target.read_text()+' ')
    with pytest.raises(ValueError):build_at(copy_project,d.name)
    assert build_at(source,d.name)[0]==d
