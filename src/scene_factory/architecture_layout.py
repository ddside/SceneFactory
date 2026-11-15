"""Small deterministic orthogonal layout constructor, callable by Codex.

Produces ordinary editable SceneSpec v2 nodes, not an opaque generated script.
No natural-language parser, Blender or registry access. Bounds are outer width /
depth; height is clear floor-to-ceiling height. One room has no corridor; 2/3
rooms share a south corridor. Unused wall opening slots remain stable.
"""


def node(nid,skill,parameters,parent=None,location=(0,0,0),angle=0,inputs=None,depends=()):
    return {'node_id':nid,'skill':{'skill_id':skill,'version':'1.0.0'},'parameters':parameters,
            'parent_id':parent,'transform':{'location':list(location),'rotation_degrees':[0,0,angle]},
            'inputs':inputs or {},'depends_on':list(depends)}


def ref(nid,output): return {'node_id':nid,'output':output}


def building_scene(width=12,depth=8,height=3,rooms=3,thickness=.2,scene_id='modular-building',seed=42):
    if type(rooms) is not int or rooms not in (1,2,3): raise ValueError('layout supports 1..3 rooms')
    if width<6 or depth<5 or height<2.7 or not .1<=thickness<=.4:
        raise ValueError('layout requires width>=6, depth>=5, height>=2.7, wall thickness .1.. .4')
    w,d,h,t=width,depth,height,thickness; root='building.main'; cw=1.6 if rooms>1 else 0
    ns=[node(root,'arch_building',{'width':w,'depth':d,'height':h,'wall_thickness':t,'room_count':rooms,'corridor_width':cw})]
    def wall(key,length,location,angle=0,kind=1,side=0,holes=()):
        wid=root+'.wall.'+key; p={'length':length,'height':h,'thickness':t,'wall_kind':kind,'side':side,'opening_count':len(holes)}
        ns.append(node(wid,'arch_wall',p,root,location,angle))
        for slot,(name,ow,oh,sill,offset,otype) in enumerate(holes,1):
            for k,v in zip(('width','height','sill','offset','kind'),(ow,oh,sill,offset,otype)): p[f'o{slot}_{k}']=v
            oid=root+'.opening.'+('window.' if otype==2 else '')+name
            ns.append(node(oid,'arch_opening',{'slot':slot,'width':ow,'height':oh,'sill':sill,'offset':offset,'kind':otype,'depth':t},
                           wid,(offset,0,sill),inputs={'wall':ref(wid,'wall')}))
            fid=root+('.door.' if otype==1 else '.window.')+name
            ns.append(node(fid,'arch_door' if otype==1 else 'arch_window',{'width':ow,'height':oh,'depth':t},oid,
                           inputs={'opening':ref(oid,'opening')}))
        return wid
    entrance=('entrance',1,2.2,0,0,1)
    innerw=w-2*t
    roomw=(innerw-(rooms-1)*t)/rooms
    xs=[-w/2+t+roomw/2+i*(roomw+t) for i in range(rooms)]
    windows=[('room%02d'% (i+1),1.2,1.2,1,x,2) for i,x in enumerate(xs)] if rooms>1 else [
             ('room01a',1.2,1.2,1,-w/4,2),('room01b',1.2,1.2,1,w/4,2)]
    wall('south',w,(0,-d/2+t/2,0),side=1,holes=[entrance])
    wall('north',w,(0,d/2-t/2,0),side=2,holes=windows)
    wall('west',d-2*t,(-w/2+t/2,0,0),90,side=3)
    wall('east',d-2*t,(w/2-t/2,0,0),90,side=4)
    if rooms>1:
        boundary=-d/2+t+cw+t/2; roomd=d-2*t-cw-t
        wall('corridor',innerw,(0,boundary,0),kind=3,
             holes=[('room%02d'%(i+1),.95,2.2,0,x,1) for i,x in enumerate(xs)])
        cy=boundary+t/2+roomd/2
        for i in range(1,rooms):
            px=-w/2+t+i*roomw+(i-.5)*t
            wall('partition%02d'%i,roomd,(px,cy,0),90,kind=2)
        corridor=root+'.corridor.main'
        ns.append(node(corridor,'arch_corridor',{'width':innerw,'depth':cw,'height':h},root,(0,-d/2+t+cw/2,0),
                       inputs={'entrance':ref(root+'.opening.entrance','opening')}))
        for i,x in enumerate(xs,1):
            ns.append(node(root+'.room.%02d'%i,'arch_room',{'width':roomw,'depth':roomd,'height':h},root,(x,cy,0),
                       inputs={'access':ref(root+'.opening.room%02d'%i,'opening'),'corridor':ref(corridor,'space')}))
    else:
        ns.append(node(root+'.room.01','arch_room',{'width':innerw,'depth':d-2*t,'height':h},root,
                       inputs={'access':ref(root+'.opening.entrance','opening')}))
    return {'schema_version':2,'scene_id':scene_id,'seed':seed,'units':'m','nodes':ns}


def enlarge_window(spec,window_id,width,height=None):
    """Explicit three-node edit. Preserve all identities/seeds and unrelated data."""
    import copy
    result=copy.deepcopy(spec); nodes={n['node_id']:n for n in result['nodes']}; window=nodes[window_id]
    if window['skill']['skill_id']!='arch_window': raise ValueError('target is not a window')
    opening=nodes[window['inputs']['opening']['node_id']]; wall=nodes[opening['inputs']['wall']['node_id']]
    for key,value in {'width':width,**({'height':height} if height is not None else {})}.items():
        window['parameters'][key]=value; opening['parameters'][key]=value
        wall['parameters'][f'o{opening["parameters"]["slot"]}_{key}']=value
    return result
