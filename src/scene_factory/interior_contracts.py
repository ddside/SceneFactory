"""Rectangular upright interior constraints, independent of Blender geometry creation.

All measurements are in the owning room frame. A conservative 2-D occupancy
flood fill checks connected usable space at the requested passage clearance.
No navmesh, physics or general constraint solver is implied.
"""
import math
from collections import Counter,deque
from .spec import fields,identifier,number,SpecError
from .furniture_contracts import EPS,require,box,overlap,transformed_box
from .transforms import multiply


def validate(value):
    fields(value,'interior',('schema_version','minimum_passage','rooms','items'))
    if type(value['schema_version']) is not int or value['schema_version']!=1:raise SpecError('interior: schema version 1 required')
    number(value['minimum_passage'],'minimum_passage',.4,2)
    if not isinstance(value['rooms'],list) or not value['rooms'] or not isinstance(value['items'],list):raise SpecError('interior rooms/items arrays required')
    rooms=set();items=set()
    for r in value['rooms']:
        fields(r,'interior.room',('room_id','purpose','requirements'))
        identifier(r['room_id'],'room_id');identifier(r['purpose'],'purpose')
        require(r['room_id'] not in rooms,'duplicate room');rooms.add(r['room_id'])
        if not isinstance(r['requirements'],dict) or not r['requirements']:raise SpecError('interior requirements required')
        for k,v in r['requirements'].items():
            identifier(k,'required skill');require(type(v) is int and v>=0,'required counts must be nonnegative integers')
    for item in value['items']:
        fields(item,'interior.item',('node_id','room_id','semantic_type','initial_state','support','placement'))
        for k in ['node_id','room_id','semantic_type']:identifier(item[k],k)
        require(item['node_id'] not in items,'duplicate item');items.add(item['node_id'])
        require(item['room_id'] in rooms,'undeclared room');require(item['initial_state']=='normal','only normal state supported')
        s=item['support'];fields(s,'support',('kind',),('node_id',))
        require(s['kind'] in ('floor','on_top','ceiling'),'unsupported support')
        require((s['kind']=='floor')==('node_id' not in s),'support reference required only for attachment')
        if 'node_id' in s:identifier(s['node_id'],'support.node_id')
        p=item['placement'];fields(p,'placement',('mode','facing','minimum_clearance'),('wall',))
        require(p['mode'] in ('explicit','wall_aligned','near_wall','centered'),'unsupported placement')
        require(p['facing'] in (0,90,180,270),'orthogonal facing required')
        number(p['minimum_clearance'],'minimum_clearance',0,1)
        if p['mode'] in ('wall_aligned','near_wall'):require(p.get('wall') in ('north','south','west','east'),'wall required')
        elif 'wall' in p:raise SpecError('wall only supported for wall placement')
    return value


def inverse_room(room):
    m=room['world_matrix'];require(all(abs(sum(m[k][i]*m[k][j] for k in range(3))-(i==j))<EPS for i in range(3) for j in range(3)),'room requires unit orthogonal frame')
    inv=[[m[j][i] for j in range(3)]+[-sum(m[k][i]*m[k][3] for k in range(3))] for i in range(3)]
    return inv+[[0,0,0,1]]


def bounds_union(boxes):return [[min(b[0][i] for b in boxes) for i in range(3)],[max(b[1][i] for b in boxes) for i in range(3)]]


def check(value,nodes,measured=None):
    validate(value);metadata=[];by_room={r['room_id']:[] for r in value['rooms']}
    for declaration in value['rooms']:
        rid=declaration['room_id'];require(rid in nodes and nodes[rid]['skill']['skill_id']=='arch_room','room reference missing')
    # A furniture/asset root below a declared room must be tracked, preventing
    # undeclared obstacles from escaping interior validation.
    tracked={x['node_id'] for x in value['items']}
    for n in nodes.values():
        if any(a['type']=='Mesh' for a in n['expected_artifacts']) and not n['skill']['skill_id'].startswith('arch_') and n['skill']['skill_id']!='ground':
            require(n['node_id'] in tracked or bool(tracked.intersection(n['lineage'])),'untracked furniture obstacle')
        if n['parent_id'] in by_room and n['skill']['skill_id']!='arch_space':require(n['node_id'] in tracked,'untracked room item')
    for item in value['items']:
        nid=item['node_id'];rid=item['room_id'];room=nodes[rid];require(nid in nodes,'item reference missing');n=nodes[nid];inv=inverse_room(room)
        ancestor=n;seen=set()
        while ancestor['node_id']!=rid and ancestor['parent_id'] and ancestor['node_id'] not in seen:
            seen.add(ancestor['node_id']);ancestor=nodes[ancestor['parent_id']]
        require(ancestor['node_id']==rid,'item belongs to another room')
        t=n['transform'];require(t['rotation_degrees'][:2]==[0,0] and t['rotation_degrees'][2]%360==item['placement']['facing'],'upright/facing mismatch')
        require(t['scale'][0]==t['scale'][1]==t['scale'][2] and (t['scale']==[1,1,1] or 'asset_ref' in n),'furniture scaling requires dimensions')
        parts=[p for p in nodes.values() if (p['node_id']==nid or nid in p['lineage']) and any(a['type']=='Mesh' for a in p['expected_artifacts'])]
        boxes={}
        for part in parts:
            if measured is not None:
                for role,points in measured[part['node_id']].items():
                    local=[[sum(inv[i][j]*p[j] for j in range(3))+inv[i][3] for i in range(3)] for p in points]
                    boxes[part['node_id']+':'+role]=[[min(p[i] for p in local) for i in range(3)],[max(p[i] for p in local) for i in range(3)]]
            elif part['skill']['skill_id']=='furniture_part':
                p=part['parameters'];boxes[part['node_id']+':geometry']=transformed_box(multiply(inv,part['world_matrix']),[-p['width']/2,-p['depth']/2,0],[p['width']/2,p['depth']/2,p['height']])
            elif 'asset_ref' in part:
                # Frozen asset metadata is required for pure asset bounds.
                bounds=part.get('interior_asset_bounds');require(bounds is not None,'asset bounds missing')
                boxes[part['node_id']+':asset']=transformed_box(multiply(inv,part['world_matrix']),*bounds)
            else:raise SpecError('interior: unsupported mesh skill')
        require(bool(boxes),'item has no mesh components');bounds=bounds_union(list(boxes.values()));p=room['parameters'];clearance=item['placement']['minimum_clearance']
        require(all(bounds[0][i]>=-p[k]/2+clearance-EPS and bounds[1][i]<=p[k]/2-clearance+EPS for i,k in enumerate(['width','depth'])),'item outside room / wall clearance: '+nid)
        require(bounds[0][2]>=-EPS and bounds[1][2]<=p['height']+EPS,'vertical room containment: '+nid)
        support=item['support']
        if support['kind']=='floor':require(abs(bounds[0][2])<EPS,'floating floor item: '+nid)
        else:
            target=nodes.get(support['node_id']);require(target is not None,'support reference missing')
            if target['skill']['skill_id']=='furniture_part':
                tb=transformed_box(multiply(inv,target['world_matrix']),[-target['parameters']['width']/2,-target['parameters']['depth']/2,0],[target['parameters']['width']/2,target['parameters']['depth']/2,target['parameters']['height']])
                if measured is not None:
                    pts=next(iter(measured[target['node_id']].values()));loc=[[sum(inv[i][j]*pt[j] for j in range(3))+inv[i][3] for i in range(3)] for pt in pts];tb=[[min(pt[i] for pt in loc) for i in range(3)],[max(pt[i] for pt in loc) for i in range(3)]]
                require(support['kind']=='on_top' and abs(bounds[0][2]-tb[1][2])<EPS,'invalid top attachment')
                require(all(bounds[0][i]>=tb[0][i]-EPS and bounds[1][i]<=tb[1][i]+EPS for i in range(2)),'unsupported overhang')
            else:
                require(support['kind']=='ceiling' and target['role_prefix']==['ceiling'] and target['parent_id']==room['parent_id'] and abs(bounds[1][2]-p['height'])<EPS,'invalid ceiling attachment')
        place=item['placement'];distances=dict(west=bounds[0][0]+p['width']/2,east=p['width']/2-bounds[1][0],south=bounds[0][1]+p['depth']/2,north=p['depth']/2-bounds[1][1])
        if place['mode']=='wall_aligned':require(abs(distances[place['wall']]-clearance)<EPS,'wall alignment mismatch')
        if place['mode']=='near_wall':require(distances[place['wall']]<=clearance+.3,'near wall distance exceeded')
        if place['mode']=='centered':require(max(abs((bounds[0][i]+bounds[1][i])/2) for i in range(2))<EPS,'centered item mismatch')
        entry=dict(node_id=nid,room_id=rid,semantic_type=item['semantic_type'],initial_state='normal',support=support,component_ids=sorted(boxes),bounds=bounds,boxes=boxes,source=n['skill'],asset_ref=n.get('asset_ref'))
        by_room[rid].append(entry);metadata.append(entry)
    for declaration in value['rooms']:
        rid=declaration['room_id'];room=nodes[rid];items=by_room[rid];p=room['parameters'];w,d=p['width'],p['depth'];passage=value['minimum_passage']
        counts=Counter()
        for item in items:
            counts.update(n['skill']['skill_id'] for n in nodes.values() if n['node_id']==item['node_id'] or item['node_id'] in n['lineage'])
        for skill,count in declaration['requirements'].items():require(counts[skill]==count,f'room required count {rid}/{skill}: expected {count}, got {counts[skill]}')
        for i,a in enumerate(items):
            for b in items[:i]:require(not any(overlap(x,y) for x in a['boxes'].values() for y in b['boxes'].values()),'furniture intersection: '+a['node_id']+'/'+b['node_id'])
        opening=nodes[room['inputs']['access']['node_id']];inv=inverse_room(room);op=opening['parameters'];om=multiply(inv,opening['world_matrix']);cx=om[0][3]
        require(op['width']+EPS>=passage,'door narrower than required passage')
        door=[[cx-op['width']/2,-d/2,0],[cx+op['width']/2,-d/2+passage,op['height']]]
        for item in items:require(not any(overlap(b,door) for b in item['boxes'].values()),'door clearance blocked: '+item['node_id'])
        obstacles=[item['bounds'] for item in items if item['support']['kind']=='floor']
        # Conservative cell-free test: inflate by half passage plus half cell
        # diagonal, so a connected cell path guarantees requested width.
        step=.15;nx=math.ceil(w/step);ny=math.ceil(d/step);sx=w/nx;sy=d/ny;radius=passage/2;pad=math.hypot(sx,sy)/2
        free=set()
        for ix in range(nx):
            x=-w/2+(ix+.5)*sx
            for iy in range(ny):
                y=-d/2+(iy+.5)*sy
                if abs(x)>w/2-radius or y>d/2-radius:continue
                # Only the actual door channel may cross the south wall's
                # clearance strip; otherwise flood fill could walk through walls.
                if y < -d/2+radius and abs(x-cx) > (op['width']-passage)/2+EPS:continue
                if any(b[0][0]-radius-pad<x<b[1][0]+radius+pad and b[0][1]-radius-pad<y<b[1][1]+radius+pad for b in obstacles):continue
                free.add((ix,iy))
        starts=[v for v in free if v[1]==0 and abs(-w/2+(v[0]+.5)*sx-cx)<(op['width']-passage)/2+sx]
        require(bool(starts),'entrance passage blocked');seen=set(starts);todo=deque(starts)
        while todo:
            x,y=todo.popleft()
            for v in [(x+1,y),(x-1,y),(x,y+1),(x,y-1)]:
                if v in free and v not in seen:seen.add(v);todo.append(v)
        # Ignore tiny isolated pockets smaller than one passage disc. Larger
        # disconnected usable regions indicate a room split by furniture.
        missing=free-seen
        require(len(seen)*sx*sy>=passage*passage,'no usable interior access')
        while missing:
            pocket={missing.pop()};todo=deque(pocket)
            while todo:
                x,y=todo.popleft()
                for v in [(x+1,y),(x-1,y),(x,y+1),(x,y-1)]:
                    if v in missing:missing.remove(v);pocket.add(v);todo.append(v)
            require(len(pocket)*sx*sy<passage*passage,'room partitioned / insufficient passage width')
    return dict(kind='interior',state='passed',furniture_count=len(metadata),rooms=len(by_room),items=metadata,minimum_passage=value['minimum_passage'])
