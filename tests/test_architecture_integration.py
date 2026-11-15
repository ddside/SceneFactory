"""Real Blender geometry/reopen/preview/Revision tests. No mocked bpy."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import pytest
from scene_factory.architecture_layout import building_scene,enlarge_window
from scene_factory.compiler import compile_scene
from scene_factory.config import DEFAULTS
from scene_factory.project import build_at
from scene_factory.registry import Registry,file_hash
from scene_factory.runner import run_blender
from scene_factory.storage import write_json,digest
from scene_factory.workflow import start,resume_context
from scene_factory.workflow_store import diff_revisions

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def runtime():
    exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not exe: pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    p=ROOT/'artifacts/test-runs';p.mkdir(parents=True,exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='phase3a-',dir=p)),exe

@pytest.mark.parametrize('rooms',[1,2,3])
def test_actual_build_reopen_architectural_evidence_and_metrics(runtime,rooms):
    p,exe=runtime; s=building_scene(8 if rooms==1 else 12,6 if rooms==1 else 8,3,rooms)
    write_json(p/'scene.json',s); c=compile_scene(s,source_sha256=file_hash(p/'scene.json'))['build_plan'];write_json(p/'plan.json',c)
    request={'action':'build','spec_path':str(p/'scene.json'),'plan_path':str(p/'plan.json'),'plan_digest':c['plan_digest']}
    t=time.monotonic(); built=run_blender(exe,request,p,180)
    checked=run_blender(exe,{**request,'action':'validate','blend_path':str(p/'scene.blend')},p/'reopen',180)
    assert built['structure_sha256']==checked['structure_sha256']
    assert checked['domain_results'][0]['kind']=='architecture'
    artifacts=checked['artifact_manifest']['artifacts']; assert len(artifacts)==len(c['expected_artifacts'])
    metrics={'elapsed_seconds_build_and_reopen':time.monotonic()-t,'mesh_count':sum(a['type']=='Mesh' for a in artifacts),
             'vertex_count':sum(a['vertex_count'] for a in artifacts),'face_count':sum(a['face_count'] for a in artifacts)}
    assert metrics['vertex_count']<5000 and metrics['face_count']<5000
    write_json(p/'architecture-metrics.json',metrics)


def test_actual_workflow_interior_preview_edit_and_old_acceptance_rules(runtime):
    p,exe=runtime; project=p/'project'; options={**DEFAULTS,'resolution':96,'samples':1}
    proposal=json.loads((ROOT/'examples/architecture/three-rooms-request.json').read_text())
    first=start(project,proposal,exe,options)
    assert first['accepted'] is None and first['active_workflow']['status']=='awaiting_review'
    assert first['quality_runs'][-1]['stages']['domain']['state']=='passed'
    assert first['quality_runs'][-1]['stages']['visual']['state']=='not_run'
    assert {v['view'] for v in first['build_attempts'][-1]['previews']}=={'overview','top','interior'}
    a=first['build_attempts'][-1]; build,_=build_at(project,a['build_id']); sha=digest(build/'scene.blend')
    spec=enlarge_window(first['scene_spec'],'building.main.window.room02',1.8,1.4)
    after=start(project,{'raw_request':'2番目の部屋の窓を大きくしてください','scene_spec':spec,'change_summary':'窓2を1.8×1.4mに変更。対応する開口と北壁のみ同期。'},exe,options,True)
    changes=diff_revisions(project,first['working_revision']['revision_id'],after['working_revision']['revision_id'])
    assert set(changes['changed_nodes'])=={'building.main.wall.north','building.main.opening.window.room02','building.main.window.room02'}
    b,_=build_at(project,after['build_attempts'][-1]['build_id'])
    old=json.loads((build/'plan.json').read_text());new=json.loads((b/'plan.json').read_text())
    assert {n['node_id']:n['node_seed'] for n in old['nodes']}=={n['node_id']:n['node_seed'] for n in new['nodes']}
    assert digest(build/'scene.blend')==sha
    assert after['accepted'] is None  # Real image review is done separately by Codex, not forged by pytest.
    assert resume_context(project)['working_revision']['revision_id']==after['working_revision']['revision_id']


@pytest.mark.parametrize('mutation',['blocked_aperture','flipped_normals','wall_thickness','blocked_doorway'])
def test_actual_geometry_corruption_is_rejected(runtime,mutation):
    p,exe=runtime; spec=building_scene();write_json(p/'scene.json',spec)
    plan=compile_scene(spec)['build_plan'];write_json(p/'plan.json',plan)
    # Test script deliberately mutates actual bpy geometry and invokes the genuine validator.
    script=p/'tamper.py'
    script.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[sys.argv.index('--')+1])
import bpy
from scene_factory.blender.engine import generate_plan
from scene_factory.blender.validation import validate_scene
from scene_factory.registry import Registry
plan=json.loads(Path(sys.argv[-2]).read_text()); mode=sys.argv[-1]; r=Registry()
generate_plan(plan,r); validate_scene(plan,r)
nid='building.main.wall.corridor' if mode=='blocked_doorway' else 'building.main.wall.north'
node=next(n for n in plan['nodes'] if n['node_id']==nid)
obj=bpy.data.objects[node['expected_artifacts'][0]['artifact_id']]
if mode=='wall_thickness':
    for v in obj.data.vertices: v.co.y*=2
elif mode=='flipped_normals':
    import bmesh
    bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.reverse_faces(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
else:
    # Fill an aperture with a real cube, joined into the tracked wall object.
    o=node['parameters']; slot=1; x=o['o1_offset']; w=o['o1_width']; h=o['o1_height']; z=o['o1_sill']
    bpy.ops.mesh.primitive_cube_add(size=1); filler=bpy.context.object
    for v in filler.data.vertices: v.co.x=v.co.x*w+x;v.co.y*=o['thickness'];v.co.z=(v.co.z+.5)*h+z
    filler.matrix_world=obj.matrix_world
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);filler.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.join()
obj.data.update();bpy.context.view_layer.update()
try: validate_scene(plan,r)
except ValueError as exc:
    print('EXPECTED_GEOMETRIC_REJECTION',str(exc));sys.exit(0)
raise AssertionError('corrupt actual mesh accepted')
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(p/'plan.json'),mutation],capture_output=True,text=True,timeout=180)
    (p/'tamper.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0 and 'EXPECTED_GEOMETRIC_REJECTION' in result.stdout,result.stdout+result.stderr
