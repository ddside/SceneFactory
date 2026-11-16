"""Real bpy PBR/import/revision tests; synthetic PNGs are contract fixtures only."""
import copy,json,os,subprocess,tempfile
from pathlib import Path
import pytest
from scene_factory.library import Catalog,material_record
from scene_factory.providers import FakeProvider,LocalAssetProvider,Resolution
from scene_factory.library_contracts import license_record
from scene_factory.architecture_layout import building_scene
from scene_factory.appearance_layout import apply_building_materials,add_asset_instances
from scene_factory.workflow import start
from scene_factory.workflow_store import diff_revisions
from scene_factory.publication import check_accepted
from scene_factory.project import build_at,run_build,init_project
from scene_factory.storage import write_json,digest
from scene_factory.config import DEFAULTS
from test_library import png,fixture_provider

ROOT=Path(__file__).resolve().parents[1]
OPTIONS={**DEFAULTS,'resolution':64,'samples':1,'timeout':180}

@pytest.fixture(scope='module')
def pbr_runtime():
    exe=os.environ.get('SCENE_FACTORY_TEST_BLENDER')
    if not exe:pytest.skip('SCENE_FACTORY_TEST_BLENDER required')
    output=ROOT/'artifacts/test-runs';output.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='phase3b-',dir=output));c=Catalog(root/'library')
    source=root/'sources';source.mkdir();files=[]
    for channel in ('base_color','roughness','normal','height'):
        p=source/(channel+'.png');p.write_bytes(png());files.append({'path':p.name,'uri':str(p),'size':p.stat().st_size,'provider_checksum':None,'role':channel})
    r=Resolution('fake','pbr-test-fixture','1','texture','urn:test-only',{},'pbr','original',files,license_record(),'Synthetic PNG graph fixture')
    ref=c.ingest(FakeProvider({'pbr-test-fixture':r}),'pbr-test-fixture','original')['ref']
    material=c.material_from_asset(ref,'test-pbr')['ref']
    local=c.ingest(fixture_provider(source/'model',LocalAssetProvider),'same-name','original')
    with pytest.MonkeyPatch.context() as m:
        m.setenv('SCENE_FACTORY_LIBRARY',str(c.root))
        yield root,exe,c,material,local


def proposal(spec,profile='appearance'):
    return {'raw_request':'Test-only bpy material workflow','scene_spec':spec,'change_summary':'PBR contract test','requested_quality_profile':profile,'generation_budget':{'max_seconds':600}}


def inspect(root,exe,project,build_id,mutation='none'):
    build,_=build_at(project,build_id);script=root/('inspect-'+mutation+'.py');out=root/('inspect-'+mutation+'.json')
    script.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[sys.argv.index('--')+1])
import bpy
from scene_factory.registry import Registry
from scene_factory.blender.validation import validate_scene
root=Path(sys.argv[-3]);plan=json.loads((root/'plan.json').read_text());mode=sys.argv[-2];output=Path(sys.argv[-1])
bpy.ops.wm.open_mainfile(filepath=str(root/'scene.blend'),load_ui=False,use_scripts=False)
objs=[o for o in bpy.context.scene.objects if o.get('appearance_bound')]
obj=next((o for o in objs if o.data.materials[0].node_tree.nodes.get('m0.normal')),objs[0] if objs else None)
if mode!='none':
    mat=obj.data.materials[0];tree=mat.node_tree
    if mode=='roughness':tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.123
    elif mode=='color_space':tree.nodes['m0.normal'].image.colorspace_settings.name='sRGB'
    elif mode=='uv_scale':tree.nodes['m0.mapping'].inputs['Scale'].default_value[0]*=2
    elif mode=='normal_link':tree.links.remove(tree.nodes['m0.normal_map'].inputs['Color'].links[0])
    elif mode=='missing_image':tree.nodes['m0.normal'].image=None
    elif mode=='uv_coordinates':obj.data.uv_layers['SceneFactoryUV'].data[0].uv[0]+=.5
    elif mode=='glass':
        glass=next(o for o in objs if o.get('local_role')=='glass');glass.data.materials[0].node_tree.nodes['Principled BSDF'].inputs['Transmission Weight'].default_value=0
    try:validate_scene(plan,Registry(),resource_root=root)
    except ValueError as exc:output.write_text(json.dumps({'rejected':str(exc)}));sys.exit(0)
    raise AssertionError('corrupted appearance accepted')
checked=validate_scene(plan,Registry(),resource_root=root)
glass=next((o for o in objs if o.get('local_role')=='glass'),None)
result={'meshes':len([o for o in bpy.context.scene.objects if o.type=='MESH']),
        'mesh_datablocks':len({o.data.name for o in bpy.context.scene.objects if o.type=='MESH'}),
        'material_slots':sum(len(o.data.materials) for o in bpy.context.scene.objects if o.type=='MESH')}
if glass:
 bsdf=glass.data.materials[0].node_tree.nodes['Principled BSDF'];result['glass']=[bsdf.inputs['Transmission Weight'].default_value,bsdf.inputs['IOR'].default_value]
if obj:
 result['uv_name']=obj.data.uv_layers.active.name
 result['uv_x_span']=max(u.uv.x for u in obj.data.uv_layers.active.data)-min(u.uv.x for u in obj.data.uv_layers.active.data)
 result['mapping_scale']=list(obj.data.materials[0].node_tree.nodes['m0.mapping'].inputs['Scale'].default_value)
output.write_text(json.dumps(result))
''')
    result=subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(ROOT/'src'),str(build),mutation,str(out)],capture_output=True,text=True,timeout=180)
    script.with_suffix('.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    return json.loads(out.read_text())

@pytest.fixture(scope='module')
def built_pbr(pbr_runtime):
    root,exe,c,material,local=pbr_runtime;project=root/'pbr'
    s=apply_building_materials(building_scene(8,6,3,1),material,material)
    context=start(project,proposal(s),exe,OPTIONS)
    return project,context


def test_actual_pbr_glass_uv_reopen_preview_required(pbr_runtime,built_pbr):
    root,exe,c,material,local=pbr_runtime;project,context=built_pbr
    assert context['accepted'] is None and context['quality_runs'][-1]['stages']['domain']['state']=='passed'
    assert context['quality_runs'][-1]['stages']['visual']['state']=='not_run'
    a=context['build_attempts'][-1];assert len(a['previews'])==3
    result=inspect(root,exe,project,a['build_id']);assert result['glass']==pytest.approx([1,1.5]);assert result['uv_name']=='SceneFactoryUV'
    b,_=build_at(project,a['build_id']);inventory=json.loads((b/'artifact-manifest.json').read_text())
    assert any('appearance' in a for a in inventory['artifacts'])
    assert (b/'resources.json').is_file()


def test_actual_local_multi_mesh_hierarchy_and_shared_instances(pbr_runtime):
    root,exe,c,material,local=pbr_runtime;project=root/'assets';init_project(project,2)
    s={'schema_version':2,'scene_id':'instances','seed':42,'units':'m','nodes':[]}
    s=add_asset_instances(s,local['ref'],local['record']['bounding_box'],[(0,0),(4,0)],1)
    write_json(project/'scene.json',s);result=run_build(project,exe,OPTIONS)
    inspected=inspect(root,exe,project,result['build_id']);assert inspected['meshes']==4 and inspected['mesh_datablocks']==2
    assert inspected['material_slots']==4
    b,_=build_at(project,result['build_id']);manifest=json.loads((b/'artifact-manifest.json').read_text())
    assert sum('asset' in a for a in manifest['artifacts'])==6
    assert sum(a['type']=='Object' for a in manifest['artifacts'])==4


def test_actual_metric_uv_does_not_stretch_with_width(pbr_runtime):
    root,exe,c,material,local=pbr_runtime;spans=[]
    for width in (2,4):
        project=root/('scale-'+str(width));init_project(project,2)
        s={'schema_version':2,'scene_id':'scale','seed':1,'units':'m','nodes':[{'node_id':'ground','skill':{'skill_id':'ground','version':'1.0.0'},'parameters':{'width':width,'depth':2},'transform':{}}],
           'appearance':{'schema_version':1,'materials':{'base':material},'bindings':[{'node_id':'ground','role':'geometry','material':'base','uv':{'meters_per_repeat':[2,2],'rotation_degrees':90 if width==4 else 0}}]}}
        write_json(project/'scene.json',s);build=run_build(project,exe,OPTIONS);report=inspect(root,exe,project,build['build_id']);spans.append(report['uv_x_span']);assert report['mapping_scale']==pytest.approx([.5,.5,1])
    assert spans==pytest.approx([2,4])


def test_actual_material_edit_geometry_stability_and_missing_cache_keeps_accepted(pbr_runtime):
    root,exe,c,material,local=pbr_runtime;project=root/'revision'
    a=start(project,proposal(apply_building_materials(building_scene(),material,material,material),'structural'),exe,OPTIONS)
    old=check_accepted(project);b1,_=build_at(project,old['build_id']);s=copy.deepcopy(a['scene_spec'])
    dark=c.put_material(material_record('dark-tile','tile',{'base_color':[.05,.05,.05,1]}));s['appearance']['materials']['tile']=dark
    b=start(project,{'raw_request':'廊下の床だけ暗いタイルに','scene_spec':s,'change_summary':'Material only'},exe,OPTIONS,True)
    current=check_accepted(project);b2,_=build_at(project,current['build_id'])
    d=diff_revisions(project,a['working_revision']['revision_id'],b['working_revision']['revision_id']);assert not d['changed_nodes'] and set(d['root_changes'])=={'appearance'}
    assert json.loads((b1/'build.json').read_text())['structure_sha256']==json.loads((b2/'build.json').read_text())['structure_sha256']
    # A real PBR-bound ground top at z=0 duplicates the floor top and must fail.
    from scene_factory.architecture_layout import node
    bad_overlap=copy.deepcopy(s);bad_overlap['nodes'].append(node('ground.overlap','ground',{'width':18,'depth':14,'thickness':.2},location=(0,0,-.2)))
    bad_overlap['appearance']['bindings'].append({'node_id':'ground.overlap','role':'geometry','material':'wood','uv':{'meters_per_repeat':[2,2],'rotation_degrees':0}})
    overlap=start(project,{'raw_request':'coplanar fault injection','scene_spec':bad_overlap,'change_summary':'test'},exe,OPTIONS,True)
    assert 'coplanar' in overlap['build_attempts'][-1]['error']
    assert check_accepted(project)['acceptance_id']==current['acceptance_id']
    original=c.root/local['record']['local_cache_path']/'hierarchy.gltf';data=original.read_bytes();original.unlink()
    try:
        bad=add_asset_instances(s,local['ref'],local['record']['bounding_box'],[(0,-5)],1)
        failed=start(project,{'raw_request':'cache failure test','scene_spec':bad,'change_summary':'test missing resource'},exe,OPTIONS,True)
        assert failed['accepted']['acceptance_id']==current['acceptance_id']
        assert failed['active_workflow']['status']=='needs_input'
        assert check_accepted(project)['acceptance_id']==current['acceptance_id']
    finally:original.write_bytes(data)

@pytest.mark.parametrize('mutation',['roughness','color_space','uv_scale','normal_link','missing_image','uv_coordinates','glass'])
def test_actual_appearance_corruption_rejected(pbr_runtime,built_pbr,mutation):
    root,exe,c,material,local=pbr_runtime;project,context=built_pbr
    result=inspect(root,exe,project,context['build_attempts'][-1]['build_id'],mutation)
    assert result['rejected']
