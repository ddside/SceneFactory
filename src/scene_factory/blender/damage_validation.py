"""Exact-volume narrow phase for broad-phase damage contacts; warnings are data."""
import math
from collections import deque
import bpy
from mathutils import Matrix
from scene_factory.damage_contracts import classify_intersection
from .damage_geometry import bounds,solid_volume,boolean_mesh,cutter,remove_object,convex_intersection,hull_object


def intersection_measure(a,b,core_a=None,core_b=None):
    convex=convex_intersection(a,b)
    if convex is not None:return dict(lower=convex[0],upper=convex[0],depth=convex[1],method='convex half-space intersection')
    mesh=boolean_mesh(a,b,'INTERSECT')
    try:
        if not mesh.polygons:return dict(lower=0.,upper=0.,depth=0.,method='Exact Boolean')
        points=[a.matrix_world@v.co for v in mesh.vertices]
        depth=min(max(p[i] for p in points)-min(p[i] for p in points) for i in range(3))
        try:volume=solid_volume(mesh)*abs(a.matrix_world.to_3x3().determinant())
        except ValueError:
            # The *measurement* Boolean may contain coplanar slivers while both
            # saved solids are valid. Establish explicit geometric bounds; never
            # infer a FAIL from an enclosure or silently repair the saved mesh.
            ha,hb=hull_object(a),hull_object(b);temporary=[ha,hb]
            try:
                upper=convex_intersection(ha,hb)
                if upper is None:raise ValueError('damage: unable to bound contact geometry: '+a.name+' / '+b.name)
                inner=[]
                for source,core in [(a,core_a),(b,core_b)]:
                    if convex_intersection(source,source) is not None:inner.append(source)
                    elif core:
                        obj=cutter(*core);obj.matrix_world=source.matrix_world.copy();temporary.append(obj);inner.append(obj)
                    else:inner.append(None)
                lower=convex_intersection(*inner) if all(o is not None for o in inner) else (0.,0.)
                return dict(lower=lower[0],upper=upper[0],depth=upper[1],method='convex enclosure / validated furniture core bounds',measurement_warning='coplanar Boolean topology; interval certified instead')
            finally:
                for obj in temporary:remove_object(obj)
        return dict(lower=volume,upper=volume,depth=depth,method='Exact Boolean')
    finally:
        if mesh.users==0:bpy.data.meshes.remove(mesh)


def passage_report(plan,objects):
    """Conservative occupied rectangles, sampled entrance-to-room access.

    This reports placement clearance, never robotic traversal or dynamic safety.
    """
    from scene_factory.interior_contracts import inverse_room
    from scene_factory.compiler import artifact_id
    from mathutils import Vector
    nodes={n['node_id']:n for n in plan['nodes']};reports=[]
    spaces=list(plan.get('interior',{}).get('rooms',[]))
    if plan.get('interior'):
        spaces += [dict(room_id=n['node_id']) for n in plan['nodes'] if n['skill']['skill_id']=='arch_corridor']
    for declaration in spaces:
        rid=declaration['room_id'];room=nodes[rid];inv=Matrix(inverse_room(room));w,d=room['parameters']['width'],room['parameters']['depth'];required=plan['interior']['minimum_passage'];obstacles=[]
        for aid,obj in objects.items():
            if obj.type!='MESH':continue
            skill=nodes[obj['producer_node_id']]['skill']['skill_id']
            if skill.startswith('arch_') and not obj.get('damage_lineage'):continue
            if skill=='ground':continue
            points=[inv@(obj.matrix_world@v.co) for v in obj.data.vertices];low=[min(v[i] for v in points) for i in range(3)];high=[max(v[i] for v in points) for i in range(3)]
            if high[2]>.02 and low[2]<1.8 and all(high[i]>-size/2 and low[i]<size/2 for i,size in enumerate([w,d])):obstacles.append((aid,low,high))
        corridor=room['skill']['skill_id']=='arch_corridor'
        opening=nodes[room['inputs']['entrance' if corridor else 'access']['node_id']];center=(inv@Vector([opening['world_matrix'][i][3] for i in range(3)]))[0];door=opening['parameters']['width']
        goals=[]
        if corridor:
            for n in nodes.values():
                if n['skill']['skill_id']=='arch_room' and n['inputs'].get('corridor',{}).get('node_id')==rid:
                    access=nodes[n['inputs']['access']['node_id']]
                    goals.append((inv@Vector([access['world_matrix'][i][3] for i in range(3)]))[0])
        def reachable(width,all_goals=True):
            step=.15;nx=math.ceil(w/step);ny=math.ceil(d/step);sx=w/nx;sy=d/ny;radius=width/2;pad=math.hypot(sx,sy)/2;free=set()
            if width>door:return False
            for x in range(nx):
                px=-w/2+(x+.5)*sx
                for y in range(ny):
                    py=-d/2+(y+.5)*sy
                    if abs(px)>w/2-radius or py>d/2-radius:continue
                    if py<-d/2+radius and abs(px-center)>(door-width)/2+1e-6:continue
                    if any(lo[0]-radius-pad<px<hi[0]+radius+pad and lo[1]-radius-pad<py<hi[1]+radius+pad for _,lo,hi in obstacles):continue
                    free.add((x,y))
            starts={p for p in free if p[1]==0};seen=set(starts);todo=deque(starts)
            while todo:
                x,y=todo.popleft()
                if not corridor and y*sy>=d*.45:return True
                for p in [(x+1,y),(x-1,y),(x,y+1),(x,y-1)]:
                    if p in free and p not in seen:seen.add(p);todo.append(p)
            if not corridor:return False
            hits=[any(abs(-w/2+(x+.5)*sx-goal)<sx+radius and -d/2+(y+.5)*sy>=d/2-radius-sy for x,y in seen) for goal in goals]
            return bool(hits) and (all(hits) if all_goals else any(hits))
        full=reachable(required);half=reachable(required/2,False) if not full else True
        reports.append(dict(room_id=rid,space_type='corridor' if corridor else 'room',target_openings=goals,state='passable' if full else 'partially_blocked' if half else 'blocked',minimum_passage=required,tested_widths=[required,required/2],obstacles=[dict(artifact_id=a,minimum=lo,maximum=hi) for a,lo,hi in obstacles]))
    return reports


def domain(plan,state,objects,extra_floor_levels=None):
    boxes={aid:bounds(o) for aid,o in objects.items() if o.type=='MESH'};volumes={};findings=[];checked=set();candidates=0
    nodes={n['node_id']:n for n in plan['nodes']}
    def core(aid):
        # furniture_part is a validated rectangular-shell contract. A box inset
        # by twice the bevel is a contained solid. Changed meshes have no such
        # guarantee and are never assigned an inferred core.
        obj=objects[aid];n=nodes.get(obj.get('producer_node_id'))
        if aid in state['modified'] or n is None or n['skill']['skill_id']!='furniture_part':return None
        p=n['parameters'];r=2*p['bevel'];dims=[p[k] for k in ['width','depth','height']]
        if min(dims)<=2*r:return None
        return ([-dims[0]/2+r,-dims[1]/2+r,r],[dims[0]/2-r,dims[1]/2-r,dims[2]-r])
    def classify(measure,a,b,dimension,semantic,intended=False):
        high=classify_intersection(measure['upper'],a,b,dimension,semantic,intended,measure['depth'])
        low=classify_intersection(measure['lower'],a,b,dimension,semantic,intended,measure['depth'])
        return 'FAIL' if low=='FAIL' else 'PASS' if high=='PASS' else 'WARNING'
    def volume(aid):
        if aid not in volumes:volumes[aid]=solid_volume(objects[aid].data)*abs(objects[aid].matrix_world.to_3x3().determinant())
        return volumes[aid]
    for aid in sorted(state['affected']):
        a=boxes[aid]
        for bid,b in boxes.items():
            pair=tuple(sorted([aid,bid]))
            if aid==bid or pair in checked:continue
            checked.add(pair);overlaps=[min(a[1][i],b[1][i])-max(a[0][i],b[0][i]) for i in range(3)]
            if min(overlaps)<=1e-6:continue
            candidates+=1;measure=intersection_measure(objects[aid],objects[bid],core(aid),core(bid));v=measure['upper'];depth=measure['depth']
            if v<=1e-12:continue
            dimension=min(a[1][i]-a[0][i] for i in range(3));semantic='floor' if objects[bid].get('preview_group')=='floor' else 'furniture'
            classification=classify(measure,volume(aid),volume(bid),dimension,semantic,bool(objects[aid].get('damage_lineage') or objects[aid].get('effect_origin')))
            # A thin wall may cut completely through a large object while its
            # fraction of the object's volume remains small. Confirm solid
            # overlap first, then estimate how much of the crossing section is
            # occupied; small doorway-jamb contacts remain warnings/pass.
            crossing_coverage=0.
            node=next(n for n in plan['nodes'] if n['node_id']==objects[bid]['producer_node_id'])
            if node['skill']['skill_id']=='arch_wall':
                normal=objects[bid].matrix_world.to_3x3().col[1].normalized();origin=objects[bid].matrix_world.translation
                distances=[(objects[aid].matrix_world@p.co-origin).dot(normal) for p in objects[aid].data.vertices]
                thickness=node['parameters']['thickness'];extent=max(distances)-min(distances)
                if min(distances)<-thickness/2 and max(distances)>thickness/2:
                    crossing_coverage=measure['lower']/(volume(aid)*min(1.,thickness/extent))
                    if crossing_coverage>.5:classification='FAIL'
            findings.append(dict(state=classification,artifact_ids=[aid,bid],intersection_volume=v,penetration_depth=depth,wall_crossing_coverage=crossing_coverage,relative_volume=v/min(volume(aid),volume(bid)),method=measure['method'],measurement_warning=measure.get('measurement_warning'),volume_lower=measure['lower'],volume_upper=measure['upper'],semantic=semantic))
    # Ground reference is Z=0 for this phase's building_scene convention. Test
    # submerged solid volume rather than only the finite floor slab thickness.
    floors={aid:op['floor_elevation'] for op in state['supports'] for aid in [*op['artifact_ids'],*([op['fragment_artifact_id']] if op['fragment_artifact_id'] else [])]}
    floors.update(extra_floor_levels or {})
    for aid in sorted(state['affected']):
        box=boxes[aid];level=floors[aid]
        # A retained floor slab is intentionally below its walking surface.
        # Only released pieces/posed objects are subject to burial judgement.
        n=next(n for n in plan['nodes'] if n['node_id']==objects[aid]['producer_node_id'])
        retained_floor=n['skill']['skill_id']=='arch_slab' and n['parameters']['purpose']==1 and not objects[aid].get('damage_lineage')
        if retained_floor or box[0][2]>=level-1e-6:continue
        low=[box[0][0]-1,box[0][1]-1,box[0][2]-1];high=[box[1][0]+1,box[1][1]+1,level]
        floor=cutter(low,high)
        try:measure=intersection_measure(objects[aid],floor,core(aid));v=measure['upper']
        finally:remove_object(floor)
        classification=classify_intersection(v,volume(aid),volume(aid),min(box[1][i]-box[0][i] for i in range(3)),'floor',penetration_depth=measure['depth'])
        findings.append(dict(state=classification,artifact_ids=[aid],intersection_volume=v,relative_volume=v/volume(aid),semantic='floor_burial',method=measure['method'],volume_lower=measure['lower'],volume_upper=measure['upper']))
    for op in plan.get('damage',{}).get('operations',[]):
        if op['support']['ground']:
            ids=[op['fragment_artifact_id']] if 'fragment_artifact_id' in op else op['artifact_ids']
            lowest=min(boxes[aid][0][2] for aid in ids)
            if abs(lowest-op['floor_elevation'])>2e-5:raise ValueError('damage: requested floor grounding mismatch')
    # Retained normal supports must not silently disappear underneath unchanged
    # contents. A point ray is a support check, not a stability simulation.
    by_node={o.get('producer_node_id'):o for o in objects.values() if o.type=='MESH'}
    for item in plan.get('interior',{}).get('items',[]):
        if item['support']['kind']!='on_top':continue
        support=by_node.get(item['support']['node_id'])
        contents=[o for o in objects.values() if o.get('source_node_id')==item['node_id'] and o.type=='MESH']
        if support is None or not contents:continue
        if any(o['artifact_id'] in state['affected'] for o in contents):continue
        center=[sum(bounds(o)[k][i] for o in contents for k in [0,1])/(2*len(contents)) for i in range(2)]
        bottom=min(bounds(o)[0][2] for o in contents)
        from mathutils import Vector
        inverse=support.matrix_world.inverted();origin=inverse@Vector([*center,bottom+.01]);direction=(inverse.to_3x3()@Vector([0,0,-1])).normalized()
        hit,point,_,_=support.ray_cast(origin,direction)
        if not hit or abs((support.matrix_world@point).z-bottom)>.02:
            findings.append(dict(state='FAIL',artifact_ids=[o['artifact_id'] for o in contents],semantic='unsupported_contents',method='retained support ray'))
    passages=passage_report(plan,objects)
    for rid,expected in plan.get('damage',{}).get('passage_expectations',{}).items():
        actual=next((p['state'] for p in passages if p['room_id']==rid),None)
        if actual!=expected:findings.append(dict(state='FAIL',artifact_ids=[],semantic='passage_expectation',room_id=rid,expected=expected,actual=actual,method='clearance flood fill'))
    return dict(kind='damage',baseline_validated=True,operations=state['supports'],fragment_count=len(plan.get('damage',{}).get('fragments',[])),state='failed' if any(f['state']=='FAIL' for f in findings) else 'passed',findings=findings,
                warnings=sum(f['state']=='WARNING' for f in findings),candidate_pairs=candidates,passages=passages,
                checks=['normal baseline validation','deterministic replay','copy-on-write','closed positive solids','source lineage','supports','exact-volume collision policy'])
