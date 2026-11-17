"""Measured region/count/source/support checks plus inherited contact policy."""
import json,math
from mathutils import Matrix,Vector
from scene_factory.effect_contracts import count
from .damage_geometry import bounds,solid_volume
from .damage_validation import domain as damage_domain


def domain(plan,state,objects):
    nodes={n['node_id']:n for n in state['plan']['nodes']};floors={};reports=[]
    for e in plan['effects']['items']:
        room=nodes[e['region']['room_id']];inv=Matrix(room['world_matrix']).inverted();p=e['parameters']
        if e['effect_type'] in ('debris','scatter'):
            if len(e['generated_root_ids'])!=count(e):raise ValueError('effects: generated count mismatch')
            measured=0.
            for nid in e['generated_root_ids']:
                parts=[o for o in objects.values() if o.type=='MESH' and (o['producer_node_id']==nid or nid in nodes[o['producer_node_id']]['lineage'])]
                if not parts:raise ValueError('effects: missing generated obstacle')
                for obj in parts:
                    points=[inv@(obj.matrix_world@v.co) for v in obj.data.vertices]
                    if any(min(v[i] for v in points)<e['region']['minimum'][i]-.002-(p.get('settle_fraction',0)*p['size_max'][2] if i==2 else 0) or max(v[i] for v in points)>e['region']['maximum'][i]+.002 for i in range(3)):raise ValueError('effects: generated object outside region')
                    floors[obj['artifact_id']]=room['world_matrix'][2][3];measured+=solid_volume(obj.data)*abs(obj.matrix_world.to_3x3().determinant())
                    if not obj.get('effect_support'):raise ValueError('effects: missing support')
                lowest=min(bounds(o)[0][2] for o in parts)
                support=parts[0].get('effect_support');floor=room['world_matrix'][2][3]
                tolerance=max(.003,min(.01,p['size_max'][2]*.1))+p.get('settle_fraction',0)*p['size_max'][2]
                if support=='floor':
                    if abs(lowest-floor)>tolerance:raise ValueError('effects: unsupported floating group')
                else:
                    obj=objects.get(support)
                    if obj is None or obj.type!='MESH':raise ValueError('effects: invalid support reference')
                    inverse=obj.matrix_world.inverted();gaps=[]
                    for part in parts:
                        feature_points=[v.co for v in part.data.vertices]+[f.center for f in part.data.polygons]+[(part.data.vertices[edge.vertices[0]].co+part.data.vertices[edge.vertices[1]].co)/2 for edge in part.data.edges]
                        for coordinate in feature_points:
                            point=part.matrix_world@coordinate;origin=inverse@Vector([point.x,point.y,floor+room['parameters']['height']+.2]);direction=(inverse.to_3x3()@Vector([0,0,-1])).normalized()
                            hit,where,_,_=obj.ray_cast(origin,direction)
                            if hit:gaps.append(abs(point.z-(obj.matrix_world@where).z))
                            near,where,_,_=obj.closest_point_on_mesh(inverse@point)
                            if near:gaps.append((point-obj.matrix_world@where).length)
                    # A support vertex can touch the interior of a lower face,
                    # with no debris vertex directly above the support polygon.
                    for part in parts:
                        pinv=part.matrix_world.inverted()
                        for v in obj.data.vertices:
                            point=obj.matrix_world@v.co;near,where,_,_=part.closest_point_on_mesh(pinv@point)
                            if near:gaps.append((point-part.matrix_world@where).length)
                    if not gaps or min(gaps)>tolerance:raise ValueError('effects: supported group has no near contact: '+nid+' / '+support+' gap='+str(min(gaps) if gaps else None))
                if p['distribution'] in ('source_based','directional'):
                    from .effect_runtime import source_point
                    source=inv@source_point(state['plan'],e,objects)
                    center=[sum((inv@(o.matrix_world@v.co))[i] for o in parts for v in o.data.vertices)/sum(len(o.data.vertices) for o in parts) for i in range(2)]
                    for i in range(2):
                        projected=min(e['region']['maximum'][i],max(e['region']['minimum'][i],source[i]))
                        if abs(center[i]-projected)>p['extent'][i]+max(p['size_max']):raise ValueError('effects: debris detached from declared source footprint')
                # Saved solids remain strict; contacts use the inherited volume policy.
            for nid in p['existing_ids']:
                for obj in objects.values():
                    if obj.type=='MESH' and (obj['producer_node_id']==nid or nid in nodes[obj['producer_node_id']]['lineage']):floors[obj['artifact_id']]=room['world_matrix'][2][3]
            reports.append(dict(effect_id=e['effect_id'],requested_count=count(e),measured_volume=measured,volume_budget=p['volume_budget']))
        elif e['effect_type']=='surface':
            prefix='effect.'+e['effect_id']+'.';matches=[]
            for aid,obj in objects.items():
                if e['effect_id'] not in json.loads(obj.get('effect_layers','[]')):continue
                if aid not in e['target_mesh_ids']:raise ValueError('effects: layer on undeclared target')
                tree=obj.material_slots[0].material.node_tree;ns=tree.nodes
                if ns[prefix+'room_position'].object.get('producer_node_id')!=e['region']['room_id']:raise ValueError('effects: surface coordinate region mismatch')
                if ns[prefix+'noise'].noise_dimensions!='4D' or abs(ns[prefix+'noise'].inputs['W'].default_value-(e['seed']%10000)/137)>1e-5:raise ValueError('effects: surface seed mismatch')
                for i,axis in enumerate('XYZ'):
                    for name,expected in [('min'+axis,e['region']['minimum'][i]-.001),('max'+axis,e['region']['maximum'][i]+.001)]:
                        if abs(ns[prefix+name].inputs[1].default_value-expected)>1e-5:raise ValueError('effects: surface mask escaped region')
                record=plan['resources']['materials'][e['material']]['parameters']
                if any(abs(a-b)>1e-5 for a,b in zip(ns[prefix+'base_color'].inputs[2].default_value,record['base_color'])):raise ValueError('effects: surface MaterialRef color mismatch')
                if abs(ns[prefix+'roughness'].inputs[2].default_value[0]-record['roughness'])>1e-5:raise ValueError('effects: wet/material roughness mismatch')
                if p['surface_type']=='waterline' and (abs(ns[prefix+'water_height'].inputs[1].default_value-p['height'])>1e-5 or abs(ns[prefix+'band_scale'].inputs[1].default_value-p['band_width'])>1e-5):raise ValueError('effects: waterline height/width mismatch')
                matches.append(aid)
            if not matches:raise ValueError('effects: missing surface layer')
            reports.append(dict(effect_id=e['effect_id'],surface_type=p['surface_type'],height=p['height'],targets=matches))
    collision=damage_domain(state['plan'],state,objects,extra_floor_levels=floors)
    return dict(kind='effects',state=collision['state'],baseline_validated=True,effect_count=len(plan['effects']['items']),reports=state['effect_reports'],checks=reports,contacts=collision['findings'],warnings=collision['warnings'],passages=collision['passages'],reproducible=True)
