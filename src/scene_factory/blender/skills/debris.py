"""Low-poly closed rubble prototypes with material-specific geometry."""
import random,math
import bpy,bmesh
from scene_factory.blender.skills.common import close,validate_material
from scene_factory.blender.damage_geometry import solid_volume
from scene_factory.contract_utils import canonical_digest

COLORS=((.42,.43,.42),(.76,.73,.67),(.25,.12,.05),(.4,.65,.7),(.28,.3,.29))


def generate(node,context):
    p=node['parameters'];appearance=context['plan'].get('appearance') or {};bindings=[{**{k:v for k,v in b.items() if k!='node_id'},'ref':appearance['materials'][b['material']]} for b in appearance.get('bindings',[]) if b['node_id']==node['node_id']];key=canonical_digest([p,bindings]);cache=context.setdefault('mesh_cache',{})
    mesh=cache.get(key)
    if mesh is None:
        r=random.Random(p['shape_seed']);w,d,h=[p[k] for k in ['width','depth','height']];kind=p['kind'];j=p['irregularity']
        if kind==0:
            points=[(sx*w/2*r.uniform(1-j,1),sy*d/2*r.uniform(1-j,1),z*h+r.uniform(-j,j)*h*.2) for sx in [-1,1] for sy in [-1,1] for z in [0,1]]
        else:
            sides=3+p['variant']%3 if kind==3 else 6 if kind==1 else 4 if kind==2 else 5
            points=[]
            for z in [0,1]:
                for i in range(sides):
                    a=2*math.pi*i/sides;factor=r.uniform(1-j,1)
                    points.append((math.cos(a)*w/2*factor,math.sin(a)*d/2*factor,z*h+(r.uniform(-j,j)*h*.15 if kind in [2,4] else 0)))
        # Normalize the prototype envelope; all dimensions remain observable.
        low=[min(v[i] for v in points) for i in range(3)];high=[max(v[i] for v in points) for i in range(3)]
        points=[tuple((v[i]-low[i])/(high[i]-low[i])*[w,d,h][i]-([w/2,d/2,0][i]) for i in range(3)) for v in points]
        bm=bmesh.new()
        for point in points:bm.verts.new(point)
        result=bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
        unused=[v for v in bm.verts if not v.link_faces]
        if unused:bmesh.ops.delete(bm,geom=unused,context='VERTS')
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));mesh=bpy.data.meshes.new('debris.prototype');bm.to_mesh(mesh);bm.free();mesh.update()
        material=bpy.data.materials.new('debris.surface');material.use_nodes=True;material.diffuse_color=(*COLORS[kind],1)
        material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=material.diffuse_color
        material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.8;mesh.materials.append(material);cache[key]=mesh
    obj=bpy.data.objects.new(node['node_id'],mesh);bpy.context.scene.collection.objects.link(obj);obj['debris_kind']=p['kind']
    return {'geometry':obj}


def validate(node,objects,context):
    obj=objects['geometry'];p=node['parameters'];dims=[p[k] for k in ['width','depth','height']]
    close([max(v.co[i] for v in obj.data.vertices)-min(v.co[i] for v in obj.data.vertices) for i in range(3)],dims,'debris dimensions')
    close([min(v.co.z for v in obj.data.vertices)],[0],'debris base')
    kind=p['kind']
    if kind==1 and dims[2]>.2*min(dims[:2]) or kind==3 and dims[2]>.08*min(dims[:2]) or kind==2 and max(dims[:2])<3*min(dims[:2]):raise ValueError('debris dimensions violate material-specific proportions')
    volume=solid_volume(obj.data)
    if not .03*math.prod(dims)<=volume<=math.prod(dims)*1.0001:raise ValueError('debris volume outside solid envelope')
    if len(obj.data.vertices)>24 or len(obj.data.polygons)>44:raise ValueError('debris topology budget exceeded')
    if obj.get('debris_kind')!=p['kind']:raise ValueError('debris semantic type changed')
    validate_material(obj)
