"""Closed-solid damage on supported polygonal components, Blender runtime only."""
import random
import bpy,bmesh
from mathutils import Matrix,Vector,Euler
from scene_factory.blender.generators import cuboid_vertices,FACES


def solid_volume(mesh):
    bm=bmesh.new();bm.from_mesh(mesh)
    try:
        if not bm.faces or any(not e.is_manifold or not e.is_contiguous for e in bm.edges):raise ValueError('damage: open/inconsistent mesh')
        if any(f.calc_area()<1e-12 for f in bm.faces):raise ValueError('damage: degenerate face')
        volume=bm.calc_volume(signed=True)
        if volume<=1e-12:raise ValueError('damage: zero volume / inward normals')
        reject_self_intersections(mesh)
        return volume
    finally:bm.free()


def bounds(obj,world=True):
    pts=[obj.matrix_world@v.co if world else v.co for v in obj.data.vertices]
    return [[min(p[i] for p in pts) for i in range(3)],[max(p[i] for p in pts) for i in range(3)]]


def cutter(low,high,seed=0,irregularity=0):
    size=[high[i]-low[i] for i in range(3)];verts=cuboid_vertices(size);rng=random.Random(seed)
    verts=[(v[0]+(low[0]+high[0])/2,v[1]+(low[1]+high[1])/2,v[2]+low[2]) for v in verts]
    mesh=bpy.data.meshes.new('damage.cutter');mesh.from_pydata(verts,[],FACES);mesh.update()
    if irregularity:
        bm=bmesh.new()
        for p in verts:bm.verts.new([p[i]+rng.uniform(-1,1)*size[i]*irregularity for i in range(3)])
        bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
    obj=bpy.data.objects.new('damage.cutter',mesh);bpy.context.scene.collection.objects.link(obj);return obj


def boolean_mesh(source,cut,operation):
    """Evaluate on a private mesh, never on a shared source datablock."""
    obj=bpy.data.objects.new('damage.boolean',source.data.copy());bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world=source.matrix_world.copy();mod=obj.modifiers.new('damage.boolean','BOOLEAN');mod.operation=operation;mod.solver='EXACT';mod.object=cut
    try:
        graph=bpy.context.evaluated_depsgraph_get();evaluated=obj.evaluated_get(graph)
        mesh=bpy.data.meshes.new_from_object(evaluated,depsgraph=graph)
        return mesh
    finally:
        data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
        if data.users==0:bpy.data.meshes.remove(data)


def remove_object(obj):
    data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
    if data and data.users==0:bpy.data.meshes.remove(data)


def pose(objects,op,pivot_world):
    rotation=Euler([__import__('math').radians(v) for v in op['rotation_degrees']],'XYZ').to_matrix().to_4x4()
    shift=Matrix.Translation(op['displacement']);pivot=Vector(pivot_world)
    delta=shift @ Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
    originals=[(o,o.matrix_world.copy()) for o in objects]
    for obj,matrix in originals:
        obj.parent=None;obj.matrix_parent_inverse=Matrix.Identity(4);obj.matrix_world=delta@matrix
    bpy.context.view_layer.update()
    if op['support']['ground']:
        lowest=min(bounds(o)[0][2] for o in objects)
        for obj in objects:obj.matrix_world=Matrix.Translation((0,0,op.get('floor_elevation',0)-lowest))@obj.matrix_world
    bpy.context.view_layer.update()


def reject_self_intersections(mesh):
    """BVH broad phase followed by nonadjacent triangle edge/face tests."""
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import intersect_ray_tri
    mesh.calc_loop_triangles();triangles=list(mesh.loop_triangles);vertices=[v.co.copy() for v in mesh.vertices]
    tree=BVHTree.FromPolygons(vertices,[list(t.vertices) for t in triangles],all_triangles=True)
    for i,j in tree.overlap(tree):
        if i>=j:continue
        a,b=triangles[i],triangles[j]
        if a.polygon_index==b.polygon_index or set(a.vertices).intersection(b.vertices):continue
        pa=[vertices[k] for k in a.vertices];pb=[vertices[k] for k in b.vertices]
        if {tuple(round(x,8) for x in p) for p in pa}=={tuple(round(x,8) for x in p) for p in pb}:raise ValueError('damage: duplicate coincident triangles')
        for edges,face in [(pa,pb),(pb,pa)]:
            for k in range(3):
                start=edges[k];end=edges[(k+1)%3];length=(end-start).length
                if length<=1e-9:continue
                direction=(end-start)/length;hit=intersect_ray_tri(*face,direction,start,True)
                if hit is not None and 1e-7<(hit-start).dot(direction)<length-1e-7:
                    # An edge touching another triangulation's boundary is not
                    # an interior crossing (Boolean caps contain such T joins).
                    u=face[1]-face[0];v=face[2]-face[0];q=hit-face[0]
                    uu=u.dot(u);uv=u.dot(v);vv=v.dot(v);den=uu*vv-uv*uv
                    if den<=1e-20:continue
                    b=(vv*q.dot(u)-uv*q.dot(v))/den;c=(uu*q.dot(v)-uv*q.dot(u))/den
                    if min(b,c,1-b-c)>1e-6:raise ValueError('damage: nonadjacent triangle self intersection')


def convex_intersection(a,b):
    """Intersect two convex world-space solids by their supporting half-spaces.

    Returns None for nonconvex inputs. This avoids coplanar Boolean topology
    artifacts without weakening saved-mesh validation or using AABB volume.
    """
    import math
    all_points=[[o.matrix_world@v.co for v in o.data.vertices] for o in [a,b]]
    scale=max(max(p[i] for p in points)-min(p[i] for p in points) for points in all_points for i in range(3));eps=max(1e-7,scale*2e-6)
    planes=[]
    for obj,points in zip([a,b],all_points):
        normals=obj.matrix_world.to_3x3().inverted().transposed();object_planes=[]
        for face in obj.data.polygons:
            normal=(normals@face.normal).normalized();distance=normal.dot(points[face.vertices[0]])
            if any(normal.dot(p)-distance>eps for p in points):return None
            object_planes.append((normal,distance))
        planes.append(object_planes)
    faces=[[all_points[0][k] for k in f.vertices] for f in a.data.polygons]
    def unique(points):
        result=[]
        for p in points:
            if not any((p-q).length<=eps for q in result):result.append(p)
        return result
    for normal,distance in planes[1]:
        clipped=[];cap=[]
        for polygon in faces:
            output=[]
            for start,end in zip(polygon,polygon[1:]+polygon[:1]):
                ds=normal.dot(start)-distance;de=normal.dot(end)-distance
                if ds<=eps:output.append(start)
                if (ds>eps)!=(de>eps):
                    point=start+(end-start)*(ds/(ds-de));output.append(point);cap.append(point)
            output=unique(output)
            if len(output)>=3:clipped.append(output)
        cap=unique(cap)
        if len(cap)>=3:
            center=sum(cap,Vector())/len(cap);u=(cap[0]-center).normalized();v=normal.cross(u)
            cap.sort(key=lambda p:math.atan2((p-center).dot(v),(p-center).dot(u)));clipped.append(cap)
        faces=clipped
        if not faces:return 0.,0.
    points=[p for f in faces for p in f];reference=sum(points,Vector())/len(points);volume=0.
    for f in faces:
        for i in range(1,len(f)-1):volume+=(f[0]-reference).dot((f[i]-reference).cross(f[i+1]-reference))/6
    depth=min(max(p[i] for p in points)-min(p[i] for p in points) for i in range(3))
    return max(0.,volume),max(0.,depth)


def hull_object(source):
    """Temporary convex enclosure from actual vertices, not an AABB proxy."""
    bm=bmesh.new()
    for v in source.data.vertices:bm.verts.new(v.co)
    bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    mesh=bpy.data.meshes.new('damage.measure.hull');bm.to_mesh(mesh);bm.free();mesh.update()
    obj=bpy.data.objects.new('damage.measure.hull',mesh);bpy.context.scene.collection.objects.link(obj);obj.matrix_world=source.matrix_world.copy()
    return obj
