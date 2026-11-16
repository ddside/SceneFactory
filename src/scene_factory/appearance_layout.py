"""Codex authoring helpers: semantic material bindings, never Provider API parsing."""
from .compiler import child_id
from .library import mat_ref,builtins
from .architecture_layout import node


def apply_building_materials(spec,concrete,wood,tile=None,asphalt=None):
    import copy
    s=copy.deepcopy(spec);materials={'concrete':concrete,'wood':wood,'paint':mat_ref(builtins()['painted_wall']),
        'glass':mat_ref(builtins()['glass']),'metal':mat_ref(builtins()['metal'])}
    if tile:materials['tile']=tile
    if asphalt:materials['asphalt']=asphalt
    bindings=[]
    def bind(nid,role,material,scale=(2,2),region=None):
        b={'node_id':nid,'role':role,'material':material,'uv':{'meters_per_repeat':list(scale),'rotation_degrees':0}}
        if region:b['region']=region
        bindings.append(b)
    for n in s['nodes']:
        skill=n['skill']['skill_id'];nid=n['node_id']
        if skill=='arch_wall':bind(nid,'geometry','concrete' if n['parameters']['wall_kind']==1 else 'paint')
        elif skill=='arch_door':bind(nid,'frame','paint');bind(nid,'leaf','wood')
        elif skill=='arch_window':bind(nid,'frame','metal');bind(nid,'glass','glass')
        elif skill=='arch_building':
            bind(child_id(nid,'floor'),'geometry','wood');bind(child_id(nid,'ceiling'),'geometry','paint');bind(child_id(nid,'roof'),'geometry','concrete')
        elif skill=='ground' and asphalt:bind(nid,'geometry','asphalt')
    if tile:
        for n in s['nodes']:
            if n['skill']['skill_id']=='arch_corridor':
                p=n['parameters'];x,y,_=n['transform']['location'];bind(child_id(n['parent_id'],'floor'),'geometry','tile',region={
                    'xmin':x-p['width']/2,'xmax':x+p['width']/2,'ymin':y-p['depth']/2,'ymax':y+p['depth']/2})
    s['appearance']={'schema_version':1,'materials':materials,'bindings':bindings};return s


def add_asset_instances(spec,asset_ref,bounds,positions,scale=1,ground_z=0):
    import copy
    s=copy.deepcopy(spec)
    for i,(x,y) in enumerate(positions,1):
        n=node('rock.%02d'%i,'asset_instance',{},location=(x,y,ground_z-bounds[0][2]*scale));n['asset_ref']=copy.deepcopy(asset_ref);n['transform']['scale']=[scale]*3;s['nodes'].append(n)
    return s
