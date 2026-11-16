"""Real saved Blender geometry, copy-on-write, contacts and corruption tests."""
import copy,json,os,subprocess,tempfile
from pathlib import Path
import pytest
from scene_factory.damage_layout import acceptance_scene,normal_office,intersection_scene,with_damage,operation
from scene_factory.architecture_layout import node
from scene_factory.project import init_project,run_build,operate,build_at
from scene_factory.storage import write_json
from scene_factory.config import DEFAULTS
from scene_factory.workflow import start,resume_context,repair

ROOT=Path(__file__).resolve().parents[1]
OPTIONS={**DEFAULTS,'resolution':64,'samples':1,'timeout':600}

@pytest.fixture(scope='module')
def runtime():
    executable=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not executable:pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    base=ROOT/'artifacts/test-runs';base.mkdir(exist_ok=True,parents=True)
    return Path(tempfile.mkdtemp(prefix='phase3d-',dir=base)),executable


def build(runtime,name,spec):
    root,exe=runtime;project=root/name;init_project(project,2);write_json(project/'scene.json',spec)
    result=run_build(project,exe,OPTIONS);directory,_=build_at(project,result['build_id'])
    checked=operate(project,'validate',exe,OPTIONS,build_id=result['build_id'])
    return project,directory,json.loads((directory/'plan.json').read_text()),json.loads((directory/'artifact-manifest.json').read_text()),checked

@pytest.fixture(scope='module')
def scenes(runtime):
    result={'normal':build(runtime,'normal',normal_office())}
    for name in ['A','B','C','D']:result[name]=build(runtime,name,acceptance_scene(name))
    return result

@pytest.mark.parametrize('label',['A','B','C','D'])
def test_real_damage_preserves_untouched_geometry_and_reopens(scenes,label):
    _,directory,plan,manifest,checked=scenes[label];baseline={a['artifact_id']:a for a in scenes['normal'][3]['artifacts']}
    actual={a['artifact_id']:a for a in manifest['artifacts']};changed={aid for op in plan['damage']['operations'] if op['damage_type'] in ['component_fracture','structural_damage','partial_collapse'] for aid in op['artifact_ids']}
    assert all(a['geometry_digest']==actual[aid]['geometry_digest'] for aid,a in baseline.items() if aid not in changed)
    assert all(baseline[aid]['geometry_digest']!=actual[aid]['geometry_digest'] for aid in changed)
    for fragment in plan['damage']['fragments']:
        a=actual[fragment['artifact_id']];assert a['damage']['original_artifact_id'] in baseline and a['lineage'][-1]==a['producer_node_id']
    damage=next(r for r in checked['domain_results'] if r['kind']=='damage');assert damage['state']=='passed'
    if label=='D':
        assert any(p['state']=='blocked' for p in damage['passages'])
        assert damage['warnings']>0 and all(f['state']!='FAIL' for f in damage['findings'])


def test_exact_intersection_pass_warning_fail_and_shared_pose_meshes(runtime):
    _,_,plan,manifest,checked=build(runtime,'F',intersection_scene())
    result=next(r for r in checked['domain_results'] if r['kind']=='damage')
    assert result['state']=='failed';assert {'PASS','WARNING','FAIL'}.issubset({f['state'] for f in result['findings']})
    original={op['artifact_ids'][0] for op in plan['damage']['operations']}
    assert all(a['damage']['state']=='displaced' for a in manifest['artifacts'] if a['artifact_id'] in original)


def test_broad_phase_overlap_is_not_mesh_penetration(runtime):
    s=dict(schema_version=2,scene_id='obb-separated',seed=42,units='m',nodes=[node('a','furniture_part',dict(width=2,depth=.1,height=1),angle=45),node('b','furniture_part',dict(width=2,depth=.1,height=1),location=(-.15,.15,0),angle=45)])
    s=with_damage(s,[operation('move','a','rigid_displacement',displacement=(.001,0,0))])
    *_,checked=build(runtime,'obb-separated',s);damage=next(r for r in checked['domain_results'] if r['kind']=='damage')
    assert damage['candidate_pairs']>0 and damage['state']=='passed' and not damage['findings']

@pytest.mark.parametrize('fractions',[(.01,.01,.01),(.15,.15,.15)])
def test_pass_and_warning_do_not_trigger_repair(runtime,fractions):
    root,exe=runtime;project=root/('workflow-'+str(fractions[0]));s=intersection_scene(fractions)
    c=start(project,dict(raw_request='Test-only contact policy workflow',scene_spec=s,change_summary='Contact test',requested_quality_profile='damaged_interior',generation_budget=dict(max_seconds=1800)),exe,OPTIONS)
    assert len(c['build_attempts'])==1 and c['build_attempts'][0]['error'] is None
    assert c['presentation']['status']=='awaiting_visual_review'
    assert c['quality_runs'][-1]['stages']['domain']['state']=='passed'


def test_fail_enters_bounded_repair_and_cannot_be_accepted(runtime):
    root,exe=runtime;project=root/'workflow-fail';s=intersection_scene()
    c=start(project,dict(raw_request='Test-only severe penetration',scene_spec=s,change_summary='FAIL test',requested_quality_profile='damaged_interior',generation_budget=dict(max_seconds=1800,max_attempts=2,no_improvement_limit=2)),exe,OPTIONS)
    assert c['accepted'] is None and c['active_workflow']['status']=='needs_repair'
    # Correct only the FAIL operation. The next failed proposal cannot start
    # another attempt beyond the original workflow's bound.
    revised=copy.deepcopy(s);revised['damage']['operations'][-1]['displacement'][0]=1.01;revised['damage']['operations'][0]['displacement'][0]=1.8
    c=repair(project,dict(scene_spec=revised,change_summary='Test-only unresolved FAIL retry'),exe,OPTIONS)
    assert len(c['build_attempts'])==2 and c['accepted'] is None
    with pytest.raises(ValueError):repair(project,dict(scene_spec=s,change_summary='Forbidden third attempt'),exe,OPTIONS)

@pytest.mark.parametrize('mutation',['open','normals','zero','lineage','sharing'])
def test_saved_damage_corruption_is_rejected(runtime,scenes,mutation):
    root,exe=runtime;build_dir=scenes['B'][1];script=root/('corrupt-'+mutation+'.py');out=root/(mutation+'.json')
    script.write_text('''import bpy,bmesh,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[-4])
from scene_factory.blender.damage_runtime import validate_saved
from scene_factory.registry import Registry
root=Path(sys.argv[-3]);mode=sys.argv[-2];out=Path(sys.argv[-1]);plan=json.loads((root/'plan.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(root/'scene.blend'),load_ui=False,use_scripts=False)
fragment=next(o for o in bpy.context.scene.objects if o.get('damage_lineage'))
if mode=='lineage':fragment['damage_lineage']='forged'
elif mode=='sharing':
 target=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('damage_state')=='fractured')
 other=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o!=target and o.get('generator')=='furniture_part');other.data=target.data
else:
 bm=bmesh.new();bm.from_mesh(fragment.data)
 if mode=='open':bmesh.ops.delete(bm,geom=[next(iter(bm.faces))],context='FACES')
 elif mode=='normals':bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
 else:
  for v in bm.verts:v.co.z=0
 bm.to_mesh(fragment.data);bm.free()
p=out.with_suffix('.blend');bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(p));bpy.ops.wm.open_mainfile(filepath=str(p),load_ui=False,use_scripts=False)
try:validate_saved(plan,Registry(),root)
except ValueError as exc:out.write_text(json.dumps(dict(rejected=str(exc))))
else:raise AssertionError('corrupted damage was accepted')
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(build_dir),mutation,str(out)],capture_output=True,text=True,timeout=600)
    script.with_suffix('.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(out.read_text())['rejected']


def test_floor_beam_door_geometry_and_retained_floor_support(runtime):
    from scene_factory.damage_layout import member_damage_scene
    *_,checked=build(runtime,'members',member_damage_scene())
    damage=next(r for r in checked['domain_results'] if r['kind']=='damage')
    assert damage['state']=='passed' and damage['fragment_count']==2
    assert not any(f.get('semantic')=='floor_burial' and f['state']=='FAIL' for f in damage['findings'])

@pytest.mark.parametrize('mode',['buried','wall_crossing','duplicate'])
def test_major_penetration_is_not_accepted(runtime,mode):
    from scene_factory.architecture_layout import building_scene
    if mode=='duplicate':
        spec=intersection_scene((.99,.01,.01))
    else:
        spec=building_scene(8,8,3,1)
        spec['nodes'].append(node('solid','furniture_part',dict(width=1,depth=1,height=1),location=(0,0,0)))
        delta=(0,0,-.5) if mode=='buried' else (0,3.9,0)
        op=operation('penetrate','solid','rigid_displacement',displacement=delta,ground=False)
        spec=with_damage(spec,[op])
    *_,checked=build(runtime,'major-'+mode,spec)
    damage=next(r for r in checked['domain_results'] if r['kind']=='damage');assert damage['state']=='failed'
    if mode=='wall_crossing':assert any(f.get('wall_crossing_coverage',0)>.5 and f['state']=='FAIL' for f in damage['findings'])


def test_independent_solid_checks_detect_open_inward_zero_and_self_crossing(runtime):
    root,exe=runtime;script=root/'solid_checks.py';output=root/'solid_checks.json'
    script.write_text('''import bpy,bmesh,sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[-2])
from scene_factory.blender.damage_geometry import cutter,solid_volume
results={}
for mode in ['open','inward','zero','crossing']:
 obj=cutter([0,0,0],[1,1,1]);bm=bmesh.new();bm.from_mesh(obj.data)
 if mode=='open':bmesh.ops.delete(bm,geom=[list(bm.faces)[0]],context='FACES')
 elif mode=='inward':bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
 elif mode=='zero':
  for v in bm.verts:v.co.z=0
 else:
  other=cutter([.2,.3,.4],[1.2,1.3,1.4]);bm.from_mesh(other.data)
 bm.to_mesh(obj.data);bm.free()
 try:solid_volume(obj.data)
 except ValueError as exc:results[mode]=str(exc)
 else:raise AssertionError(mode+' was not rejected')
Path(sys.argv[-1]).write_text(json.dumps(results))
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(output)],capture_output=True,text=True,timeout=180)
    script.with_suffix('.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    assert set(json.loads(output.read_text()))=={'open','inward','zero','crossing'}
