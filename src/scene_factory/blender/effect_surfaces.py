"""Object-isolated procedural layers over unchanged catalog PBR references."""
import json
import bpy
from mathutils import Matrix,Vector
from scene_factory.contract_utils import canonical_digest
from .appearance import signature


def apply_layers(plan,effect,objects):
    p=effect['parameters'];room=next(n for n in plan['nodes'] if n['node_id']==effect['region']['room_id']);origin=[room['world_matrix'][i][3] for i in range(3)]
    target_ids=set(p['targets']);nodes={n['node_id']:n for n in plan['nodes']}
    anchor=Matrix(room['world_matrix']).inverted()@Vector(effect.get('anchor_world',origin))
    record=plan['resources']['materials'][effect['material']];affected=[]
    for aid,obj in objects.items():
        if obj.type!='MESH':continue
        n=nodes[obj['producer_node_id']]
        chain=set(n['lineage']);parent=n
        while parent['parent_id']:
            chain.add(parent['parent_id']);parent=nodes[parent['parent_id']]
        if n['node_id'] not in target_ids and not target_ids.intersection(chain):continue
        points=[Matrix(room['world_matrix']).inverted()@(obj.matrix_world@v.co) for v in obj.data.vertices]
        if any(max(v[i] for v in points)<effect['region']['minimum'][i]-.002 or min(v[i] for v in points)>effect['region']['maximum'][i]+.002 for i in range(3)):continue
        # Layers share mesh geometry but isolate the material slot per Object.
        slot=obj.material_slots[0]
        if slot.link!='OBJECT':slot.link='OBJECT';slot.material=obj.data.materials[0].copy()
        material=slot.material;tree=material.node_tree;ns,links=tree.nodes,tree.links;prefix='effect.'+effect['effect_id']+'.'
        shader=ns.get('Principled BSDF')
        if shader is None:raise ValueError('effects: supported Principled base required')
        def math_node(name,operation,*inputs):
            node=ns.new('ShaderNodeMath');node.name=prefix+name;node.operation=operation
            for i,value in enumerate(inputs):
                if hasattr(value,'node'):links.new(value,node.inputs[i])
                else:node.inputs[i].default_value=value
            return node.outputs[0]
        geo=ns.new('ShaderNodeTexCoord');geo.name=prefix+'room_position';geo.object=bpy.data.objects[room['expected_artifacts'][0]['artifact_id']]
        sep=ns.new('ShaderNodeSeparateXYZ');sep.name=prefix+'position_xyz';links.new(geo.outputs['Object'],sep.inputs[0])
        factors=[]
        for i,axis in enumerate(['X','Y','Z']):
            lo=effect['region']['minimum'][i];hi=effect['region']['maximum'][i]
            factors += [math_node('min'+axis,'GREATER_THAN',sep.outputs[axis],lo-.001),math_node('max'+axis,'LESS_THAN',sep.outputs[axis],hi+.001)]
        mask=factors[0]
        for i,f in enumerate(factors[1:]):mask=math_node('region'+str(i),'MULTIPLY',mask,f)
        noise=ns.new('ShaderNodeTexNoise');noise.name=prefix+'noise';noise.noise_dimensions='4D';noise.inputs['Scale'].default_value=3.5;noise.inputs['Detail'].default_value=2
        noise.inputs['W'].default_value=(effect['seed']%10000)/137;links.new(geo.outputs['Object'],noise.inputs['Vector'])
        kind=p['surface_type'];z=sep.outputs['Z'];level=p['height']
        if kind=='waterline':
            distance=math_node('water_distance','ABSOLUTE',math_node('water_height','SUBTRACT',z,level))
            band=math_node('water_band','MAXIMUM',math_node('water_inverse','SUBTRACT',1,math_node('band_scale','DIVIDE',distance,p['band_width'])),0)
            mask=math_node('water_mask','MULTIPLY',mask,band)
        elif kind in ('wet','mud'):
            below=math_node('below_water','LESS_THAN',z,level);mask=math_node('wet_mask','MULTIPLY',mask,below)
        elif kind=='fine_crack':
            wave=ns.new('ShaderNodeTexWave');wave.name=prefix+'crack_lines';wave.wave_type='BANDS';wave.bands_direction='X';wave.inputs['Scale'].default_value=9;wave.inputs['Distortion'].default_value=5;direction=ns.new('ShaderNodeVectorMath');direction.name=prefix+'crack_direction';direction.operation='DOT_PRODUCT';direction.inputs[1].default_value=p['direction'];links.new(geo.outputs['Object'],direction.inputs[0]);links.new(direction.outputs['Value'],wave.inputs['Vector'])
            narrow=math_node('fine_width','GREATER_THAN',wave.outputs['Fac'],.965);mask=math_node('fine_mask','MULTIPLY',mask,narrow)
        elif kind in ('soot','scorch','char','discoloration'):
            # Source-centered horizontal falloff and height-biased soot.
            xy=[]
            for i,axis in enumerate(['X','Y']):
                center=anchor[i];extent=(effect['region']['maximum'][i]-effect['region']['minimum'][i])/2
                value=math_node('distance'+axis,'DIVIDE',math_node('abs'+axis,'ABSOLUTE',math_node('delta'+axis,'SUBTRACT',sep.outputs[axis],center)),extent)
                xy.append(value)
            radius=math_node('radius','MAXIMUM',xy[0],xy[1]);falloff=math_node('falloff','MAXIMUM',math_node('inverse_radius','SUBTRACT',1,radius),0)
            mask=math_node('fire_extent','MULTIPLY',mask,falloff)
            if kind=='soot':
                height=math_node('soot_height','MINIMUM',math_node('soot_bias','ADD',math_node('height_scale','DIVIDE',math_node('above_floor','SUBTRACT',z,0),3),.25),1)
                mask=math_node('soot_plume','MULTIPLY',mask,height)
        mask=math_node('noise_mask','MULTIPLY',mask,math_node('noise_range','ADD',math_node('noise_amplitude','MULTIPLY',noise.outputs['Fac'],.7),.3))
        mask=math_node('severity','MULTIPLY',mask,effect['severity'])
        color=ns.new('ShaderNodeMixRGB');color.name=prefix+'base_color';color.blend_type='MIX';links.new(mask,color.inputs[0]);color.inputs[2].default_value=record['parameters']['base_color']
        old=shader.inputs['Base Color']
        if old.is_linked:links.new(old.links[0].from_socket,color.inputs[1])
        else:color.inputs[1].default_value=old.default_value
        links.new(color.outputs[0],old)
        rough=ns.new('ShaderNodeMixRGB');rough.name=prefix+'roughness';links.new(mask,rough.inputs[0]);r=record['parameters']['roughness'];rough.inputs[2].default_value=(r,r,r,1)
        old=shader.inputs['Roughness']
        if old.is_linked:links.new(old.links[0].from_socket,rough.inputs[1])
        else:r=old.default_value;rough.inputs[1].default_value=(r,r,r,1)
        links.new(rough.outputs[0],old)
        layers=json.loads(obj.get('effect_layers','[]'));layers.append(effect['effect_id']);obj['effect_layers']=json.dumps(layers)
        obj['appearance_graph_hash']=signature(material);affected.append(aid)
    return affected
