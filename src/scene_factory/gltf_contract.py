"""Restricted glTF 2.0 preflight and hierarchy metadata; no Blender imports."""
import base64,json,struct,math
from pathlib import Path
from .library_contracts import relative
from .transforms import identity,multiply

R=[[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]]
RI=[[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]]

def point(m,v):return [sum(m[i][j]*v[j] for j in range(3))+m[i][3] for i in range(3)]

def local_matrix(n):
    if 'matrix' in n:
        if len(n['matrix'])!=16:raise ValueError('glTF matrix length')
        return [[n['matrix'][j*4+i] for j in range(4)] for i in range(4)]
    x,y,z,w=n.get('rotation',[0,0,0,1]);s=n.get('scale',[1,1,1]);t=n.get('translation',[0,0,0])
    if not math.isclose(x*x+y*y+z*z+w*w,1,abs_tol=1e-5):raise ValueError('glTF nonunit quaternion')
    m=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),t[0]],
       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),t[1]],
       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),t[2]],[0,0,0,1]]
    for i in range(3):
        for j in range(3):m[i][j]*=s[j]
    return m


def inspect_gltf(root,entrypoint):
    root=Path(root);doc=json.loads((root/relative(entrypoint)).read_text())
    if doc.get('asset',{}).get('version')!='2.0' or doc.get('extensionsRequired') or doc.get('skins') or doc.get('animations') or doc.get('cameras'):
        raise ValueError('unsupported glTF version/extensions/animation/skin/camera')
    buffers=[];dependencies=[]
    for b in doc.get('buffers',[]):
        uri=b.get('uri','')
        if uri.startswith('data:application/octet-stream;base64,'):data=base64.b64decode(uri.split(',',1)[1],validate=True)
        else:dependencies.append(relative(uri));data=(root/uri).read_bytes()
        if len(data)!=b['byteLength']:raise ValueError('glTF incomplete buffer')
        buffers.append(data)
    for image in doc.get('images',[]):
        if 'uri' in image:
            uri=image['uri']
            if not uri.startswith('data:image/'):dependencies.append(relative(uri));assert (root/uri).is_file(),'missing glTF texture'
    def positions(index):
        a=doc['accessors'][index]
        if a.get('sparse') or a['componentType']!=5126 or a['type']!='VEC3':raise ValueError('unsupported glTF POSITION accessor')
        v=doc['bufferViews'][a['bufferView']];start=v.get('byteOffset',0)+a.get('byteOffset',0);stride=v.get('byteStride',12)
        if a['count']>2000000 or stride<12 or start+(a['count']-1)*stride+12>v.get('byteOffset',0)+v['byteLength']:raise ValueError('invalid glTF accessor range')
        out=[struct.unpack_from('<fff',buffers[v['buffer']],start+i*stride) for i in range(a['count'])]
        if not all(math.isfinite(x) for p in out for x in p):raise ValueError('nonfinite glTF vertices')
        return out
    meshes={}
    for i,m in enumerate(doc.get('meshes',[])):
        points=[]
        for p in m['primitives']:
            if p.get('mode',4)!=4 or p.get('targets'):raise ValueError('only static triangular glTF supported')
            points.extend(positions(p['attributes']['POSITION']))
        meshes[i]=points
        if sum(len(v) for v in meshes.values())>2000000:raise ValueError('glTF total vertex budget exceeded')
    nodes=doc.get('nodes',[]);scene=doc.get('scenes',[{}])[doc.get('scene',0)];parts=[];visited=set();allpoints=[]
    def visit(i,parent,world):
        if i in visited:raise ValueError('glTF hierarchy cycle/shared node unsupported')
        visited.add(i);n=nodes[i];local=multiply(multiply(R,local_matrix(n)),RI);matrix=multiply(world,local)
        if any(not math.isfinite(x) for row in local for x in row):raise ValueError('nonfinite glTF matrix')
        mesh=n.get('mesh');verts=[point(R,p) for p in meshes[mesh]] if mesh is not None else []
        if len(allpoints)+len(verts)>4000000:raise ValueError('glTF instance vertex budget exceeded')
        if verts:allpoints.extend(point(matrix,p) for p in verts)
        parts.append({'role':'part%04d'%i,'source_index':i,'parent_role':parent,'type':'Mesh' if mesh is not None else 'Object',
            'local_matrix':local,'bounds':[[min(p[a] for p in verts) for a in range(3)],[max(p[a] for p in verts) for a in range(3)]] if verts else None,
            'material_count':len({p.get('material',-1) for p in doc['meshes'][mesh]['primitives']}) if mesh is not None else 0})
        for child in n.get('children',[]):visit(child,'part%04d'%i,matrix)
    for i in scene.get('nodes',[]):visit(i,'frame',identity())
    if not allpoints or len(parts)>500:raise ValueError('empty/oversized glTF hierarchy')
    bounds=[[min(p[a] for p in allpoints) for a in range(3)],[max(p[a] for p in allpoints) for a in range(3)]]
    return {'parts':parts,'bounding_box':bounds,'dependencies':sorted(set(dependencies))}
