"""Pure, reviewed architectural contracts. No bpy and no mesh construction.

WallRef/OpeningRef/SpaceRef carry positive local [width, depth, height]. Their
binding's node_id is the identity; reference inputs never implicitly move nodes.
"""
import math
from .spec import SpecError

EPS=2e-5


def require(condition, message):
    if not condition: raise SpecError('architecture: '+message)


def near(a,b):
    return abs(a-b)<EPS


def wall_openings(p):
    result=[]
    for i in range(1,p['opening_count']+1):
        result.append({'slot':i,'width':p[f'o{i}_width'],'height':p[f'o{i}_height'],
            'sill':p[f'o{i}_sill'],'offset':p[f'o{i}_offset'],'kind':p[f'o{i}_kind']})
    return result


def check_wall(node,nodes):
    p=node['parameters']; openings=wall_openings(p)
    for o in openings:
        require(abs(o['offset'])+o['width']/2 < p['length']/2-EPS,'opening outside wall or removes end pier')
        require(o['sill']+o['height'] < p['height']-EPS,'opening above wall/header missing')
        require(o['sill']>=0,'negative sill')
        require(o['kind']!=1 or near(o['sill'],0),'door opening must reach floor')
    for i,a in enumerate(openings):
        for b in openings[i+1:]:
            separated=(abs(a['offset']-b['offset'])>(a['width']+b['width'])/2+EPS or
                       a['sill']+a['height']<b['sill']-EPS or b['sill']+b['height']<a['sill']-EPS)
            require(separated,'overlapping/touching wall openings')


def bound(node,nodes,port,skill):
    binding=node['resolved_inputs'].get(port)
    require(binding is not None,f'{node["node_id"]}: missing {port} reference')
    producer=nodes[binding['node_id']]
    require(producer['skill']['skill_id']==skill,f'{port} must reference {skill}')
    return producer


def local(node,location,rotation=0):
    t=node['resolved_transform']
    require(all(near(a,b) for a,b in zip(t['location'],location)),f'{node["node_id"]}: placement inconsistent with reference')
    require(all(near(a,b) for a,b in zip(t['rotation_degrees'],[0,0,rotation])) and
            all(near(a,1) for a in t['scale']),f'{node["node_id"]}: invalid architectural local transform')


def check_opening(node,nodes):
    wall=bound(node,nodes,'wall','arch_wall'); p=node['parameters']; wp=wall['parameters']
    require(node['parent_id']==wall['node_id'],'opening spatial parent must be its WallRef')
    require(p['slot']<=wp['opening_count'],'opening references inactive slot')
    for key in ('width','height','sill','offset','kind'):
        require(near(p[key],wp[f'o{p["slot"]}_{key}']),'opening definition/WallRef dimensions mismatch')
    require(near(p['depth'],wp['thickness']),'opening depth/wall thickness mismatch')
    local(node,[p['offset'],0,p['sill']])
    others=[n for n in nodes.values() if n['skill']['skill_id']=='arch_opening' and
            n['parent_id']==wall['node_id'] and n['parameters']['slot']==p['slot']]
    require(len(others)==1,'duplicate opening slot')


def check_fitting(node,nodes):
    opening=bound(node,nodes,'opening','arch_opening'); p=node['parameters']; op=opening['parameters']
    require(node['parent_id']==opening['node_id'],'fitting spatial parent must be its OpeningRef')
    kind=1 if node['skill']['skill_id']=='arch_door' else 2
    require(op['kind']==kind,'door/window opening type mismatch')
    require(near(p['width'],op['width']) and near(p['height'],op['height']) and near(p['depth'],op['depth']),
            'opening and fitting dimensions mismatch')
    require(2*p['frame_thickness']<min(p['width'],p['height']),'frame fills opening')
    if kind==2: require(p['glass_thickness']<p['depth'],'glass thicker than opening')
    else: require(p['leaf_thickness']<p['depth'],'door leaf thicker than opening')
    local(node,[0,0,0])
    require(sum(n['skill']['skill_id'] in ('arch_door','arch_window') and n['parent_id']==opening['node_id']
                for n in nodes.values())==1,'multiple fittings in opening')


def check_space(node,nodes):
    # Logical free space; containment/access is checked by the containing building.
    if node['skill']['skill_id']=='arch_room':
        bound(node,nodes,'access','arch_opening')
        if 'corridor' in node['resolved_inputs']: bound(node,nodes,'corridor','arch_corridor')
    elif node['skill']['skill_id']=='arch_corridor': bound(node,nodes,'entrance','arch_opening')


def rect(node):
    p=node['parameters']; x,y,_=node['resolved_transform']['location']
    return x-p['width']/2,x+p['width']/2,y-p['depth']/2,y+p['depth']/2


def overlap(a,b):
    return min(a[1],b[1])-max(a[0],b[0])>EPS and min(a[3],b[3])-max(a[2],b[2])>EPS


def opening_rect(opening,nodes):
    wall=nodes[opening['parent_id']]; w=wall['resolved_transform']; p=opening['parameters']
    a=math.radians(w['rotation_degrees'][2]); x=w['location'][0]+p['offset']*math.cos(a)
    y=w['location'][1]+p['offset']*math.sin(a)
    half=p['width']/2
    return x,y,half*abs(math.cos(a)),half*abs(math.sin(a))


def on_boundary(opening,space,nodes):
    x,y,hx,hy=opening_rect(opening,nodes); a,b,c,d=rect(space)
    wall=nodes[opening['parent_id']]; tolerance=wall['parameters']['thickness']/2+EPS
    if hx>hy: return (abs(y-c)<=tolerance or abs(y-d)<=tolerance) and x-hx>a+EPS and x+hx<b-EPS
    return (abs(x-a)<=tolerance or abs(x-b)<=tolerance) and y-hy>c+EPS and y+hy<d-EPS


def check_building(node,nodes):
    p=node['parameters']; nid=node['node_id']; w,d,h,t=p['width'],p['depth'],p['height'],p['wall_thickness']
    require(w>4*t and d>4*t,'building has no usable interior')
    require(all(near(v,1) for v in node['transform']['scale']) and
            all(near(v,0) for v in node['transform']['rotation_degrees'][:2]),'building permits translation/Z rotation, unit scale only')
    children=[n for n in nodes.values() if n['parent_id']==nid]
    walls=[n for n in children if n['skill']['skill_id']=='arch_wall']
    rooms=[n for n in children if n['skill']['skill_id']=='arch_room']
    corridors=[n for n in children if n['skill']['skill_id']=='arch_corridor']
    require(len(rooms)==p['room_count'],'room count mismatch')
    require(len(corridors)==(1 if p['room_count']>1 else 0),'corridor count mismatch')
    require(len(walls)==4+(p['room_count'] if corridors else 0),'unexpected/missing partition walls')
    external=[n for n in walls if n['parameters']['wall_kind']==1]
    require(len(external)==4 and {n['parameters']['side'] for n in external}=={1,2,3,4},'closed perimeter needs four unique exterior sides')
    positions={1:([0,-d/2+t/2,0],0,w),2:([0,d/2-t/2,0],0,w),
               3:([-w/2+t/2,0,0],90,d-2*t),4:([w/2-t/2,0,0],90,d-2*t)}
    wall_rects=[]
    for wall in walls:
        wp=wall['parameters']; wt=wall['resolved_transform']; a=wt['rotation_degrees'][2]
        require(near(wp['thickness'],t) and near(wp['height'],h),'wall thickness/height mismatch')
        require(near(a,0) or near(a,90),'non-orthogonal wall layout')
        if wp['wall_kind']==1:
            pos,angle,length=positions[wp['side']]; local(wall,pos,angle)
            require(near(wp['length'],length),'exterior length mismatch')
        else:
            local(wall,wt['location'],a); require(near(wt['location'][2],0),'floating partition')
        x,y,_=wt['location']; dx,dy=(wp['length']/2,t/2) if near(a,0) else (t/2,wp['length']/2)
        box=(x-dx,x+dx,y-dy,y+dy)
        require(box[0]>=-w/2-EPS and box[1]<=w/2+EPS and box[2]>=-d/2-EPS and box[3]<=d/2+EPS,'wall outside building')
        for old in wall_rects: require(not overlap(box,old),'unintended wall intersection')
        wall_rects.append(box)
        openings=[n for n in nodes.values() if n['skill']['skill_id']=='arch_opening' and n['parent_id']==wall['node_id']]
        require({o['parameters']['slot'] for o in openings}==set(range(1,wp['opening_count']+1)),'wall opening nodes missing')
    slabs=[n for n in children if n['skill']['skill_id']=='arch_slab']
    require(len(slabs)==3 and {s['parameters']['purpose'] for s in slabs}=={1,2,3},'floor/ceiling/roof required')
    for slab in slabs:
        sp=slab['parameters']; purpose=sp['purpose']
        require(near(sp['width'],w) and near(sp['depth'],d),'slab footprint mismatch')
        z={1:-p['floor_thickness'],2:h,3:h+p['ceiling_thickness']}[purpose]
        thick={1:p['floor_thickness'],2:p['ceiling_thickness'],3:p['roof_thickness']}[purpose]
        require(near(sp['thickness'],thick),'slab thickness mismatch'); local(slab,[0,0,z])
    spaces=rooms+corridors; total=0
    for i,space in enumerate(spaces):
        local(space,space['resolved_transform']['location']); sp=space['parameters']; box=rect(space)
        require(near(space['resolved_transform']['location'][2],0) and near(sp['height'],h),'space height/elevation mismatch')
        require(box[0]>=-w/2+t-EPS and box[1]<=w/2-t+EPS and box[2]>=-d/2+t-EPS and box[3]<=d/2-t+EPS,'space outside interior')
        require(not any(overlap(box,b) for b in wall_rects),'wall blocks free room/corridor space')
        require(not any(overlap(box,rect(s)) for s in spaces[:i]),'overlapping spaces')
        total+=sp['width']*sp['depth']
        port='access' if space in rooms else 'entrance'; opening=nodes[space['resolved_inputs'][port]['node_id']]
        require(opening['parameters']['kind']==1 and on_boundary(opening,space,nodes),'room/corridor doorway not connected geometrically')
        if space in rooms and corridors:
            require(space['resolved_inputs'].get('corridor',{}).get('node_id')==corridors[0]['node_id'],'room missing corridor connection')
            require(on_boundary(opening,corridors[0],nodes),'door leads to wall/closed space instead of corridor')
        else:
            require(nodes[opening['parent_id']]['parameters']['wall_kind']==1,'entrance must lead outside')
    interior_area=(w-2*t)*(d-2*t)
    partition_area=sum(n['parameters']['length']*t for n in walls if n['parameters']['wall_kind']!=1)
    require(near(total+partition_area,interior_area),'unassigned/closed interior space')
    if corridors: require(near(corridors[0]['parameters']['depth'],p['corridor_width']),'corridor width mismatch')
