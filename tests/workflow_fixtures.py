"""Synthetic unit fixtures only. These are NOT evidence of Blender/visual success."""
import copy
from pathlib import Path
import struct
import zlib

from scene_factory.artifacts import structure_digest
from scene_factory.contract_utils import canonical_digest
from scene_factory.spec import read_json
from scene_factory.storage import write_json

ROOT=Path(__file__).resolve().parents[1]


def proposal(profile='structural'):
    value=read_json(ROOT/'examples/workflows/natural-request.json')
    value['requested_quality_profile']=profile
    value['generation_budget']['max_seconds']=300
    return value


def png_bytes(size):
    def chunk(k,v): return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+
            chunk(b'IDAT',zlib.compress((b'\0'+b'\x80\x80\x80\xff'*size)*size))+chunk(b'IEND',b''))


def fake_blender(executable,request,directory,timeout):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    plan=read_json(request['plan_path']); nodes={n['node_id']:n for n in plan['nodes']}
    artifacts=[]; objects=[]; mapping={}
    for expected in plan['expected_artifacts']:
        node=nodes[expected['producer_node_id']]; p=node['parameters']; mesh=expected['type']=='Mesh'
        if mesh:
            w=p.get('width',2*p.get('radius',1)); d=p.get('depth',2*p.get('radius',1)); h=p.get('height',p.get('thickness',1))
            corners=[(x,y,z,1) for x in (-w/2,w/2) for y in (-d/2,d/2) for z in (0,h)]
            world=[[sum(m[i][j]*v[j] for j in range(4)) for i in range(3)] for m in [node['world_matrix']] for v in corners]
            bounds=[[min(v[i] for v in world) for i in range(3)],[max(v[i] for v in world) for i in range(3)]]
        else: bounds=[[node['world_matrix'][i][3] for i in range(3)]]*2
        artifacts.append({**copy.deepcopy(expected),'reference':{'object':expected['artifact_id'],'mesh':'synthetic' if mesh else None},
            'geometry_digest':canonical_digest([node['skill'],p]) if mesh else None,
            'vertex_count':8 if mesh else 0,'face_count':6 if mesh else 0,'bounds':bounds,
            'local_matrix':node['local_matrix'],'world_matrix':node['world_matrix']})
        mapping.setdefault(expected['source_node_id'],[]).append(expected['artifact_id'])
        if mesh: objects.append({'artifact_id':expected['artifact_id'],'stable_id':node['node_id'],'generator':node['skill']['skill_id']})
    manifest={'schema_version':1,'plan_digest':plan['plan_digest'],'artifact_count':len(artifacts),'artifacts':artifacts,
              'node_artifacts':{k:sorted(v) for k,v in mapping.items()}}
    if request['action']=='build': (directory/'scene.blend').write_bytes(b'SYNTHETIC UNIT FIXTURE, NOT A BLEND FILE')
    if request['action']=='preview': (directory/'preview.png').write_bytes(png_bytes(request['resolution']))
    result={'ok':True,'action':request['action'],'blender':'4.5.15','blender_hash':'unit-fixture','blender_python':'3.11',
        'structure_sha256':structure_digest(manifest),'artifact_count':len(artifacts),'artifact_manifest':manifest,
        'objects':objects,'object_count':len(objects),'reopened':True,'plan_digest':plan['plan_digest'],
        'render':{'selected':'cpu','evidence':'synthetic fixture only'}}
    write_json(directory/'result.json',result)
    return result


def visual_fixture(attempt,passed=True):
    from scene_factory.quality_profiles import VISUAL_CHECKS
    return {'attempt_id':attempt['attempt_id'],'reviewer':'unit-test-fixture','method':'image_viewer','viewed':True,
        'images':[{'path':p['path'],'sha256':p['sha256']} for p in attempt['previews']],
        'checks':{name:{'state':'passed' if passed else 'failed','reason':'Synthetic fixture to test review contracts, not an actual inspection'} for name in VISUAL_CHECKS},
        'notes':'SYNTHETIC UNIT TEST RECORD. Not evidence of an actual Codex image review.'}
