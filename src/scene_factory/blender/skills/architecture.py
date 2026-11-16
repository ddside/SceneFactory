"""Modular solids and planar apertures, without Boolean modifiers.

Generation and independent validation are separate entry points. Geometric
validation uses actual topology, signed volume, bounds and ray intersections;
it never calls the mesh construction function.
"""
import math
import bpy
import bmesh
from mathutils import Vector
from scene_factory.architecture_contracts import wall_openings, check_building
from .common import close, validate_material

WALL_COLORS=((.72,.69,.61),(.65,.67,.7),(.75,.63,.5),(.6,.69,.6))


def material(obj,color):
    mat=bpy.data.materials.new(obj.name+'.material'); mat.use_nodes=True; mat.diffuse_color=(*color,1)
    shader=mat.node_tree.nodes['Principled BSDF']; shader.inputs['Base Color'].default_value=mat.diffuse_color
    shader.inputs['Roughness'].default_value=.8; obj.data.materials.append(mat)


def cell_mesh(name,width,height,depth,holes=(),color=(.72,.69,.61)):
    # A conforming 2D cell complex extruded in Y; only boundary faces emitted.
    xs=sorted(set([-width/2,width/2]+[v for o in holes for v in (o[0],o[1])]))
    zs=sorted(set([0,height]+[v for o in holes for v in (o[2],o[3])]))
    solid=set()
    for i in range(len(xs)-1):
        for k in range(len(zs)-1):
            x,z=(xs[i]+xs[i+1])/2,(zs[k]+zs[k+1])/2
            if not any(a<x<b and c<z<d for a,b,c,d in holes): solid.add((i,k))
    vertices=[]; faces=[]; indices={}
    def face(points):
        ids=[]
        for point in points:
            if point not in indices: indices[point]=len(vertices); vertices.append(point)
            ids.append(indices[point])
        faces.append(ids)
    for i,k in sorted(solid):
        a,b,c,d=xs[i],xs[i+1],zs[k],zs[k+1]; lo,hi=-depth/2,depth/2
        face([(a,lo,c),(b,lo,c),(b,lo,d),(a,lo,d)])
        face([(a,hi,c),(a,hi,d),(b,hi,d),(b,hi,c)])
        if (i-1,k) not in solid: face([(a,lo,c),(a,lo,d),(a,hi,d),(a,hi,c)])
        if (i+1,k) not in solid: face([(b,lo,c),(b,hi,c),(b,hi,d),(b,lo,d)])
        if (i,k-1) not in solid: face([(a,lo,c),(a,hi,c),(b,hi,c),(b,lo,c)])
        if (i,k+1) not in solid: face([(a,lo,d),(b,lo,d),(b,hi,d),(a,hi,d)])
    mesh=bpy.data.meshes.new(name); mesh.from_pydata(vertices,[],faces); mesh.update()
    bm=bmesh.new(); bm.from_mesh(mesh); bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.to_mesh(mesh); bm.free()
    obj=bpy.data.objects.new(name,mesh); bpy.context.scene.collection.objects.link(obj); material(obj,color)
    return obj


def generate(node,context):
    p=node['parameters']; skill=node['skill']['skill_id']; name=node['node_id']
    if skill=='arch_wall':
        holes=[(o['offset']-o['width']/2,o['offset']+o['width']/2,o['sill'],o['sill']+o['height']) for o in wall_openings(p)]
        objects={'geometry':cell_mesh(name,p['length'],p['height'],p['thickness'],holes,WALL_COLORS[p['material_slot']])}
    elif skill=='arch_slab':
        obj=cell_mesh(name,p['width'],p['thickness'],p['depth'],color=(.5,.52,.52))
        # cell_mesh axes are X,Y depth,Z height, exactly the slab convention.
        objects={'geometry':obj}
    elif skill in ('arch_door','arch_window'):
        w,h,d,f=p['width'],p['height'],p['depth'],p['frame_thickness']; door=skill=='arch_door'
        sill=0 if door else f; top=h-f
        frame=cell_mesh(name+'.frame',w,h,d,[(-w/2+f,w/2-f,sill,top)],(.26,.29,.31))
        if door:
            leaf=cell_mesh(name+'.leaf',w-2*f,h-f,p['leaf_thickness'],color=(.47,.29,.16))
            angle=math.radians(-p['open_angle']); hinge=-w/2+f
            for v in leaf.data.vertices:
                x,y=v.co.x+(w-2*f)/2,v.co.y
                v.co.x=hinge+x*math.cos(angle)-y*math.sin(angle); v.co.y=x*math.sin(angle)+y*math.cos(angle)
            leaf.data.update(); objects={'frame':frame,'leaf':leaf}
        else:
            glass=cell_mesh(name+'.glass',w-2*f,h-2*f,p['glass_thickness'],color=(.35,.61,.73))
            for v in glass.data.vertices: v.co.z+=f
            glass.data.update(); objects={'frame':frame,'glass':glass}
    else:
        obj=bpy.data.objects.new(name,None); bpy.context.scene.collection.objects.link(obj); objects={'frame':obj}
    for obj in objects.values():
        obj['architectural_role']=skill
        obj['component_id']=node['node_id']
        if skill=='arch_slab':
            obj['preview_hide_interior']=p['purpose'] in (2,3)
            obj['preview_group']='cover' if p['purpose'] in (2,3) else 'floor'
        elif skill=='arch_wall': obj['preview_group']='south_wall' if p['wall_kind']==1 and p['side']==1 else 'wall'
    return objects


def mesh_checks(obj,volume):
    mesh=obj.data; bm=bmesh.new(); bm.from_mesh(mesh)
    try:
        if not all(e.is_manifold and e.is_contiguous for e in bm.edges): raise ValueError('architecture: non-manifold/inconsistent edges')
        if any(f.calc_area()<1e-9 for f in bm.faces): raise ValueError('architecture: degenerate face')
        measured=bm.calc_volume(signed=True)
        close([measured],[volume],'architecture signed solid volume')
    finally: bm.free()
    signatures=[tuple(sorted(tuple(round(v,6) for v in mesh.vertices[i].co) for i in face.vertices)) for face in mesh.polygons]
    if len(set(signatures))!=len(signatures): raise ValueError('architecture: duplicate faces')
    validate_material(obj)


def bounds(obj,low,high,points=None):
    points=points if points is not None else [v.co for v in obj.data.vertices]
    close([min(v[i] for v in points) for i in range(3)],low,'architecture lower bounds')
    close([max(v[i] for v in points) for i in range(3)],high,'architecture upper bounds')


def ray(obj,x,z,depth):
    return obj.ray_cast(Vector((x,-depth-1,z)),Vector((0,1,0)),distance=2*depth+2)[0]


def validate_wall_geometry(obj,p):
    length,h,t=p['length'],p['height'],p['thickness']; holes=wall_openings(p)
    mesh_checks(obj,(length*h-sum(o['width']*o['height'] for o in holes))*t)
    bounds(obj,[-length/2,-t/2,0],[length/2,t/2,h])
    for o in holes:
        # Rays must traverse actual empty space at center and near all four edges.
        for xf,zf in ((0,.5),(-.45,.1),(.45,.1),(-.45,.9),(.45,.9)):
            if ray(obj,o['offset']+xf*o['width'],o['sill']+zf*o['height'],t):
                raise ValueError('architecture: wall aperture blocked by actual geometry')
        # The reveals (jambs/header and window sill) must exist in the mesh.
        origin=Vector((o['offset'],0,o['sill']+o['height']/2))
        for direction,dist in (((1,0,0),o['width']/2),((-1,0,0),o['width']/2),((0,0,1),o['height']/2)):
            hit,point,normal,index=obj.ray_cast(origin,Vector(direction),distance=dist+.01)
            if not hit: raise ValueError('architecture: missing opening reveal')
            close([(point-origin).length],[dist],'opening reveal distance')
        if o['sill']>0:
            hit,point,_,_=obj.ray_cast(origin,Vector((0,0,-1)),distance=o['height']/2+.01)
            if not hit: raise ValueError('architecture: missing window sill')
            close([(point-origin).length],[o['height']/2],'sill distance')
    # Every face must border solid on its inward side, empty space outward.
    def inside(v):
        x,y,z=v
        return (-length/2<x<length/2 and -t/2<y<t/2 and 0<z<h and
                not any(abs(x-o['offset'])<o['width']/2 and o['sill']<z<o['sill']+o['height'] for o in holes))
    for f in obj.data.polygons:
        center=f.center; normal=f.normal
        if not inside(center-normal*1e-4) or inside(center+normal*1e-4):
            raise ValueError('architecture: inward/internal/incorrect wall face')


def validate(node,objects,context):
    p=node['parameters']; skill=node['skill']['skill_id']
    for obj in objects.values():
        if node['kind']!='recipe' and (obj.get('architectural_role')!=skill or obj.get('component_id')!=node['node_id']):
            raise ValueError('architectural component metadata mismatch')
    if skill=='arch_wall':
        validate_wall_geometry(objects['geometry'],p)
        if not objects['geometry'].get('appearance_bound'):
            close(objects['geometry'].data.materials[0].diffuse_color,(*WALL_COLORS[p['material_slot']],1),'wall material slot')
    elif skill=='arch_slab':
        obj=objects['geometry']; w,d,t=p['width'],p['depth'],p['thickness']
        mesh_checks(obj,w*d*t); bounds(obj,[-w/2,-d/2,0],[w/2,d/2,t])
        if obj.get('preview_hide_interior')!=(p['purpose'] in (2,3)): raise ValueError('slab role metadata mismatch')
    elif skill in ('arch_door','arch_window'):
        w,h,d,f=p['width'],p['height'],p['depth'],p['frame_thickness']; door=skill=='arch_door'
        frame=objects['frame']; inner_height=h-f if door else h-2*f
        mesh_checks(frame,(w*h-(w-2*f)*inner_height)*d); bounds(frame,[-w/2,-d/2,0],[w/2,d/2,h])
        if ray(frame,0,h/2,d): raise ValueError('fitting frame blocks central aperture')
        if door:
            leaf=objects['leaf']; thick=p['leaf_thickness']; mesh_checks(leaf,(w-2*f)*(h-f)*thick)
            a=math.radians(p['open_angle']); hinge=-w/2+f
            points=[((v.co.x-hinge)*math.cos(a)-v.co.y*math.sin(a),
                     (v.co.x-hinge)*math.sin(a)+v.co.y*math.cos(a),v.co.z) for v in leaf.data.vertices]
            bounds(leaf,[0,-thick/2,0],[w-2*f,thick/2,h-f],points)
        else:
            glass=objects['glass']; thick=p['glass_thickness']; mesh_checks(glass,(w-2*f)*(h-2*f)*thick)
            bounds(glass,[-w/2+f,-thick/2,f],[w/2-f,thick/2,h-f])
    else:
        if objects['frame'].type!='EMPTY': raise ValueError('architectural frame must be Empty')
        if skill=='arch_building':
            nodes={n['node_id']:n for n in context['plan']['nodes']}; check_building(node,nodes)
            # Verify actual wall meshes leave each declared access aperture empty.
            for space in (n for n in nodes.values() if n['parent_id']==node['node_id'] and n['skill']['skill_id'] in ('arch_room','arch_corridor')):
                port='access' if space['skill']['skill_id']=='arch_room' else 'entrance'
                opening=nodes[space['resolved_inputs'][port]['node_id']]; wall=nodes[opening['parent_id']]
                obj=context['primary_objects'][wall['node_id']]; op=opening['parameters']
                if ray(obj,op['offset'],op['height']/2,wall['parameters']['thickness']):
                    raise ValueError('actual room access blocked by wall mesh')

            return {'kind':'architecture','node_id':node['node_id'],'state':'passed',
                    'checks':['outer_dimensions','wall_thickness_height','actual_apertures_reveals',
                              'slabs','space_containment','corridor_access','component_intersections','typed_relations']}
