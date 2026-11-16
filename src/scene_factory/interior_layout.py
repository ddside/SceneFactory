"""Small editable room patterns for Codex; deterministic explicit orthogonal layout.

Placement is a construction heuristic followed by strict validation, never a
silent correction of invalid authored scenes. Unsupported sizes fail validation.
"""
import copy
from .architecture_layout import building_scene,node
from .compiler import child_id,compile_scene
from .appearance_layout import apply_building_materials
from .library import builtins,mat_ref


def item(spec,nid,skill,room,location,parameters=None,angle=0,support=None,mode='explicit',wall=None,clearance=.08):
    spec['nodes'].append(node(nid,skill,parameters or {},room,location,angle))
    placement=dict(mode=mode,facing=angle%360,minimum_clearance=clearance)
    if wall:placement['wall']=wall
    spec['interior']['items'].append(dict(node_id=nid,room_id=room,semantic_type=skill,initial_state='normal',support=support or dict(kind='floor'),placement=placement))
    return nid


def room_pattern(spec,room,purpose):
    """Append a supported use pattern in the room's local coordinate system."""
    r=next(n for n in spec['nodes'] if n['node_id']==room);w,d=r['parameters']['width'],r['parameters']['depth'];prefix=room+'.furniture';req={}
    def add(key,skill,x,y,params=None,angle=0,**kw):return item(spec,prefix+'.'+key,skill,room,(x,y,0),params,angle,**kw)
    def shelf(key,x,y,angle=0,wall=None):
        sid=add(key,'shelf',x,y,angle=angle,mode='wall_aligned' if wall else 'explicit',wall=wall)
        for j in range(2):
            bid=prefix+'.'+key+'.box.%02d'%j
            # Explicit attachment to a stable board component, rather than a
            # contact with the aggregate shelf bounding box.
            item(spec,bid,'storage_box',room,(x+(-.25 if j==0 else .25),y,.93),support=dict(kind='on_top',node_id=child_id(sid,'board.middle')))
        return sid
    if purpose=='work_area':
        for i,(x,y) in enumerate([(x,y) for y in [-3.2,0,3.2] for x in [-1.65,1.65]],1):add('workstation.%02d'%i,'workstation',x,y)
        add('partition','partition',0,d/2-.08-.175,angle=0,mode='wall_aligned',wall='north')
        req=dict(workstation=6,desk=6,chair=6,monitor=6,partition=1)
    elif purpose=='meeting':
        # North-half meeting cluster leaves an unobstructed entry and a path
        # around either side of the table.
        add('table','desk',0,1.5,dict(width=2.1,depth=1,height=.75))
        for i,x in enumerate([-.7,0,.7]):
            add('chair.south.%d'%i,'chair',x,.55,angle=180)
            add('chair.north.%d'%i,'chair',x,2.45)
        req=dict(desk=1,chair=6)
    elif purpose in ('storage','backroom'):
        for i,x in enumerate([-1.45,1.45]):shelf('shelf.%02d'%i,x,d/2-.08-.225,wall='north')
        add('filing','filing_cabinet',-w/2+.08+.305,0,angle=270,mode='explicit')
        req=dict(shelf=2,storage_box=4,filing_cabinet=1)
    elif purpose=='living':
        add('table','desk',0,1,dict(width=1.1,depth=.65,height=.45,thickness=.04))
        add('chair.left','chair',-1.1,1,angle=270);add('chair.right','chair',1.1,1,angle=90)
        add('shelf','shelf',-w/2+.08+.6,d/2-.08-.225,mode='wall_aligned',wall='north')
        cid=add('cabinet','cabinet',w/2-.08-.5,d/2-.08-.25,mode='wall_aligned',wall='north')
        for i in range(2):item(spec,prefix+'.small.%d'%i,'product_package',room,(w/2-.08-.5+(i-.5)*.3,d/2-.08-.25,1.1),support=dict(kind='on_top',node_id=child_id(cid,'top')))
        req=dict(desk=1,chair=2,shelf=1,cabinet=1,product_package=2)
    elif purpose=='bedroom':
        add('bed','bed',-1,1);add('cabinet','cabinet',w/2-.08-.5,d/2-.08-.25,mode='wall_aligned',wall='north')
        req=dict(bed=1,cabinet=1)
    elif purpose=='kitchen':
        add('counter','counter',-1,d/2-.08-.3,mode='wall_aligned',wall='north')
        add('table','desk',0,0,dict(width=1.2,depth=.7));add('chair','chair',0,-.9,angle=180)
        req=dict(counter=1,desk=1,chair=1)
    elif purpose=='retail':
        for i,x in enumerate([-1.8,1.8]):
            sid=add('shelf.%02d'%i,'shelf',x,d/2-.08-.225,mode='wall_aligned',wall='north')
            for j in range(4):item(spec,prefix+'.package.%d.%d'%(i,j),'product_package',room,(x+(j-1.5)*.22,d/2-.08-.225,.93),support=dict(kind='on_top',node_id=child_id(sid,'board.middle')))
        add('counter','counter',-w/2+.08+.8,-d/2+1.5)
        req=dict(shelf=2,product_package=8,counter=1)
    else:raise ValueError('Unsupported room pattern '+purpose)
    # Fixture is intentionally shape-only, not an emissive or scene light.
    ceiling=child_id(r['parent_id'],'ceiling')
    item(spec,prefix+'.light','light_fixture',room,(0,0,2.92),support=dict(kind='ceiling',node_id=ceiling))
    req['light_fixture']=1
    spec['interior']['rooms'].append(dict(room_id=room,purpose=purpose,requirements=req))
    return spec


def interior_scene(kind='office'):
    patterns={'living':(8,8,['living']),'bedroom':(8,8,['bedroom']),'kitchen':(8,8,['kitchen']),
              'office':(18,14,['work_area','meeting','storage']),'retail':(16,12,['retail','backroom'])}
    if kind not in patterns:raise ValueError('Unsupported interior scene')
    w,d,uses=patterns[kind];s=building_scene(w,d,3,len(uses),scene_id='interior-'+kind)
    s['interior']=dict(schema_version=1,minimum_passage=.8,rooms=[],items=[])
    for i,use in enumerate(uses,1):room_pattern(s,'building.main.room.%02d'%i,use)
    return s


def edit_office(spec,resources=None):
    """The requested six-to-four edit, without changing other node IDs/seeds."""
    s=copy.deepcopy(spec);removed={'building.main.room.01.furniture.workstation.05','building.main.room.01.furniture.workstation.06'}
    s['nodes']=[n for n in s['nodes'] if n['node_id'] not in removed]
    s['interior']['items']=[i for i in s['interior']['items'] if i['node_id'] not in removed]
    req=s['interior']['rooms'][0]['requirements']
    for key in ('workstation','desk','chair','monitor'):req[key]=4
    rid='building.main.room.03';r=next(n for n in s['nodes'] if n['node_id']==rid)
    item(s,rid+'.furniture.shelf.02','shelf',rid,(r['parameters']['width']/2-.08-.225,0,0),angle=90,mode='wall_aligned',wall='east')
    s['interior']['rooms'][2]['requirements']['shelf']=3
    if 'appearance' in s:
        before=_geometry_plan(spec,resources)
        deleted={n['node_id'] for n in before['nodes'] if n['node_id'] in removed or removed.intersection(n['lineage'])}
        s['appearance']['bindings']=[b for b in s['appearance']['bindings'] if b['node_id'] not in deleted]
        added=rid+'.furniture.shelf.02'
        _bind_furniture(s,_geometry_plan(s,resources),{added})
    return s


def _geometry_plan(spec,resources=None):
    geometry=copy.deepcopy(spec);geometry.pop('appearance',None)
    if resources is not None:
        from .contract_utils import canonical_digest
        keys={canonical_digest(n['asset_ref']) for n in geometry['nodes'] if 'asset_ref' in n}
        resources=dict(schema_version=1,materials={},assets={k:resources['assets'][k] for k in keys})
    return compile_scene(geometry,resources=resources)['build_plan']


def _bind_furniture(spec,plan,owners=None):
    names=['wood','metal','painted_wall','asphalt','plaster','wood'];materials=spec['appearance']['materials']
    for n in plan['nodes']:
        if n['skill']['skill_id']=='furniture_part' and (owners is None or owners.intersection(n['lineage']) or n['node_id'] in owners):
            name=names[n['parameters']['surface']]
            materials.setdefault(name,mat_ref(builtins()[name]))
            spec['appearance']['bindings'].append(dict(node_id=n['node_id'],role='geometry',material=name,uv=dict(meters_per_repeat=[1,1],rotation_degrees=0)))


def apply_materials(spec,resources=None):
    """Explicit default PBR preset. Edits use edit_office to preserve overrides."""
    b=builtins();s=apply_building_materials(spec,mat_ref(b['concrete']),mat_ref(b['wood']))
    _bind_furniture(s,_geometry_plan(spec,resources))
    return s
