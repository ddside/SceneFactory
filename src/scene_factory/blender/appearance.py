"""PBR application/validation as a separate stage from geometry generation."""
import hashlib,json,math,time
from pathlib import Path
import bpy
from scene_factory.contract_utils import canonical_digest
from scene_factory.storage import digest
from scene_factory.library_contracts import validate_material

SOCKETS={'base_color':'Base Color','roughness':'Roughness','metallic':'Metallic','transmission':'Transmission Weight','ior':'IOR'}


def projected_uv(vertex,normal):
    axis=max(range(3),key=lambda a:abs(normal[a]));a,b=((1,2) if axis==0 else (0,2) if axis==1 else (0,1))
    return vertex[a],vertex[b]


def metric_uv(obj):
    mesh=obj.data;layer=mesh.uv_layers.get('SceneFactoryUV') or mesh.uv_layers.new(name='SceneFactoryUV')
    mesh.uv_layers.active=layer
    for face in mesh.polygons:
        for loop in face.loop_indices:layer.data[loop].uv=projected_uv(mesh.vertices[mesh.loops[loop].vertex_index].co,face.normal)


def uv_digest(obj):
    layer=obj.data.uv_layers.get('SceneFactoryUV')
    if layer is None:raise ValueError('missing standard metric UV map')
    values=[]
    for face in obj.data.polygons:
        for loop in face.loop_indices:
            expected=projected_uv(obj.data.vertices[obj.data.loops[loop].vertex_index].co,face.normal)
            actual=layer.data[loop].uv
            if any(abs(a-b)>2e-5 for a,b in zip(expected,actual)):raise ValueError('incorrect metric UV coordinate')
            values.append([round(float(x),6) for x in actual])
    return canonical_digest(values)


def image_for(texture,bundle,root):
    record=bundle['assets'][canonical_digest(texture['asset'])];file=next(f for f in record['files'] if f['path']==texture['file'])
    relative='resources/'+record['local_cache_path']+'/'+file['path'];path=Path(root)/relative
    image=next((i for i in bpy.data.images if i.get('sf_sha256')==file['sha256'] and i.colorspace_settings.name==texture['color_space']),None)
    if image is not None:return image
    image=bpy.data.images.load(str(path),check_existing=False);image.colorspace_settings.name=texture['color_space']
    if min(image.size)<=0:raise ValueError('texture image decode failed')
    image['sf_sha256']=file['sha256'];image['sf_relative_path']=relative;image.pack();image.filepath='//'+relative
    return image


def build_shader(tree,record,binding,bundle,root,prefix):
    nodes,links=tree.nodes,tree.links;p=record['parameters'];bsdf=nodes.new('ShaderNodeBsdfPrincipled');bsdf.name=prefix+'bsdf'
    for key,socket in SOCKETS.items():bsdf.inputs[socket].default_value=p[key]
    uv=nodes.new('ShaderNodeUVMap');uv.name=prefix+'uv';uv.uv_map='SceneFactoryUV'
    mapping=nodes.new('ShaderNodeMapping');mapping.name=prefix+'mapping';mapping.inputs['Scale'].default_value=(1/binding['uv']['meters_per_repeat'][0],1/binding['uv']['meters_per_repeat'][1],1)
    mapping.inputs['Rotation'].default_value[2]=math.radians(binding['uv']['rotation_degrees']);links.new(uv.outputs['UV'],mapping.inputs['Vector'])
    images={}
    for channel,texture in record['texture_references'].items():
        node=nodes.new('ShaderNodeTexImage');node.name=prefix+channel;node.image=image_for(texture,bundle,root);node.extension='REPEAT'
        links.new(mapping.outputs['Vector'],node.inputs['Vector']);images[channel]=node
        if channel=='base_color':
            tint=nodes.new('ShaderNodeMixRGB');tint.name=prefix+'tint';tint.blend_type='MULTIPLY';tint.inputs[0].default_value=1
            tint.inputs[2].default_value=p['base_color'];links.new(node.outputs['Color'],tint.inputs[1]);links.new(tint.outputs[0],bsdf.inputs['Base Color'])
        elif channel in ('roughness','metallic'):links.new(node.outputs['Color'],bsdf.inputs[SOCKETS[channel]])
    normal=None
    if 'normal' in images:
        normal=nodes.new('ShaderNodeNormalMap');normal.name=prefix+'normal_map';normal.uv_map='SceneFactoryTangent.'+prefix.rstrip('.');normal.inputs['Strength'].default_value=p['normal_strength']
        links.new(images['normal'].outputs['Color'],normal.inputs['Color'])
    if 'height' in images:
        bump=nodes.new('ShaderNodeBump');bump.name=prefix+'bump';bump.inputs['Distance'].default_value=p['bump_distance'];bump.inputs['Strength'].default_value=.35
        links.new(images['height'].outputs['Color'],bump.inputs['Height'])
        if normal:links.new(normal.outputs['Normal'],bump.inputs['Normal'])
        links.new(bump.outputs['Normal'],bsdf.inputs['Normal'])
    elif normal:links.new(normal.outputs['Normal'],bsdf.inputs['Normal'])
    return bsdf.outputs['BSDF']


def signature(material):
    nodes=[]
    for n in material.node_tree.nodes:
        values=[]
        for s in n.inputs:
            if hasattr(s,'default_value'):
                value=s.default_value
                if isinstance(value,(float,int)):value=round(float(value),6)
                else:
                    try:value=[round(float(x),6) for x in value]
                    except TypeError:continue
                values.append([s.name,value])
        image=None
        if n.type=='TEX_IMAGE':
            if n.image is None or n.image.packed_file is None:raise ValueError('missing packed texture dependency')
            image={'sha256':hashlib.sha256(n.image.packed_file.data).hexdigest(),'color_space':n.image.colorspace_settings.name}
        nodes.append({'name':n.name,'type':n.bl_idname,'values':values,'image':image,'uv_map':getattr(n,'uv_map',None),'operation':getattr(n,'operation',None),'settings':{k:getattr(n,k,None) for k in ('blend_type','space','extension','projection','interpolation')}})
    links=sorted([l.from_node.name,list(l.from_node.outputs).index(l.from_socket),l.to_node.name,list(l.to_node.inputs).index(l.to_socket)] for l in material.node_tree.links)
    return canonical_digest({'nodes':sorted(nodes,key=lambda n:n['name']),'links':links})


def grouped(plan):
    groups={}
    for binding in (plan.get('appearance') or {}).get('bindings',[]):groups.setdefault((binding['node_id'],binding['role']),[]).append(binding)
    return groups


def apply(plan,root):
    started=time.monotonic();bundle=plan.get('resources');groups=grouped(plan)
    for (nid,role),bindings in groups.items():
        n=next(n for n in plan['nodes'] if n['node_id']==nid);aid=next(a['artifact_id'] for a in n['expected_artifacts'] if a['local_role']==role);obj=bpy.data.objects[aid]
        base=[b for b in bindings if 'region' not in b]
        if len(base)!=1:raise ValueError('exactly one base material binding required for a target')
        ordered=base+[b for b in bindings if 'region' in b];metric_uv(obj)
        mat=bpy.data.materials.new(nid+'.PBR');mat.use_nodes=True;tree=mat.node_tree;tree.nodes.clear()
        surface=None
        for i,b in enumerate(ordered):
            if 'normal' in bundle['materials'][b['material']]['texture_references']:
                layer=obj.data.uv_layers.get('SceneFactoryTangent.m'+str(i)) or obj.data.uv_layers.new(name='SceneFactoryTangent.m'+str(i))
                base=obj.data.uv_layers['SceneFactoryUV'];sx,sy=b['uv']['meters_per_repeat'];angle=math.radians(b['uv']['rotation_degrees'])
                for loop in range(len(base.data)):
                    u,v=base.data[loop].uv.x/sx,base.data[loop].uv.y/sy
                    layer.data[loop].uv=(u*math.cos(angle)-v*math.sin(angle),u*math.sin(angle)+v*math.cos(angle))
            record=validate_material(bundle['materials'][b['material']]);shader=build_shader(tree,record,b,bundle,root,f'm{i}.')
            if i==0:surface=shader;mat.diffuse_color=record['parameters']['base_color']
            else:
                coord=tree.nodes.new('ShaderNodeTexCoord');coord.name=f'r{i}.coordinate'
                separate=tree.nodes.new('ShaderNodeSeparateXYZ');separate.name=f'r{i}.separate';tree.links.new(coord.outputs['Object'],separate.inputs[0]);factors=[]
                for j,(axis,op,value) in enumerate([('X','GREATER_THAN',b['region']['xmin']),('X','LESS_THAN',b['region']['xmax']),('Y','GREATER_THAN',b['region']['ymin']),('Y','LESS_THAN',b['region']['ymax'])]):
                    test=tree.nodes.new('ShaderNodeMath');test.name=f'r{i}.test{j}';test.operation=op;tree.links.new(separate.outputs[axis],test.inputs[0]);test.inputs[1].default_value=value;factors.append(test.outputs[0])
                mask=factors[0]
                for j,factor in enumerate(factors[1:]):
                    multiply=tree.nodes.new('ShaderNodeMath');multiply.name=f'r{i}.and{j}';multiply.operation='MULTIPLY';tree.links.new(mask,multiply.inputs[0]);tree.links.new(factor,multiply.inputs[1]);mask=multiply.outputs[0]
                mix=tree.nodes.new('ShaderNodeMixShader');mix.name=f'r{i}.mix';tree.links.new(mask,mix.inputs[0]);tree.links.new(surface,mix.inputs[1]);tree.links.new(shader,mix.inputs[2]);surface=mix.outputs[0]
        output=tree.nodes.new('ShaderNodeOutputMaterial');output.name='Material Output';tree.links.new(surface,output.inputs['Surface'])
        # Retain conventional name for geometric validators; appearance validation owns PBR values.
        tree.nodes['m0.bsdf'].name='Principled BSDF'
        obj.data.uv_layers.active=obj.data.uv_layers['SceneFactoryUV']
        obj.data.materials.clear();obj.data.materials.append(mat);obj['appearance_bound']=True;obj['appearance_bindings']=canonical_digest(bindings);obj['appearance_graph_hash']=signature(mat)
    bpy.context.scene['material_build_seconds']=time.monotonic()-started


def validate(plan,root,skip_spatial=False):
    bundle=plan.get('resources');groups=grouped(plan);inventory={};texture_hashes=set()
    for obj in bpy.context.scene.objects:
        if obj.get('appearance_bound') and (obj.get('producer_node_id'),obj.get('local_role')) not in groups:raise ValueError('unbound/forged appearance marker')
    if not skip_spatial:no_coplanar_overlap([o for o in bpy.context.scene.objects if o.get('appearance_bound')])
    for (nid,role),bindings in groups.items():
        node=next(n for n in plan['nodes'] if n['node_id']==nid);aid=next(a['artifact_id'] for a in node['expected_artifacts'] if a['local_role']==role);obj=bpy.data.objects[aid]
        if not obj.get('appearance_bound') or obj.get('appearance_bindings')!=canonical_digest(bindings) or len(obj.data.materials)!=1:raise ValueError('appearance binding/material missing')
        mat=obj.data.materials[0];actual=signature(mat)
        if obj.get('appearance_graph_hash')!=actual:raise ValueError('PBR shader graph/value/texture changed')
        local_hashes=set()
        ordered=[b for b in bindings if 'region' not in b]+[b for b in bindings if 'region' in b]
        for i,b in enumerate(ordered):
            record=bundle['materials'][b['material']];prefix=f'm{i}.';bsdf=mat.node_tree.nodes['Principled BSDF' if i==0 else prefix+'bsdf']
            for key,socket in SOCKETS.items():
                values=bsdf.inputs[socket].default_value;expected=record['parameters'][key]
                if key=='base_color':valid=all(abs(a-e)<1e-5 for a,e in zip(values,expected))
                else:valid=abs(values-expected)<1e-5
                if not valid:raise ValueError('PBR parameter mismatch: '+key)
            mapping=mat.node_tree.nodes[prefix+'mapping']
            expected_scale=[1/b['uv']['meters_per_repeat'][0],1/b['uv']['meters_per_repeat'][1],1]
            if any(abs(a-e)>1e-5 for a,e in zip(mapping.inputs['Scale'].default_value,expected_scale)) or abs(mapping.inputs['Rotation'].default_value[2]-math.radians(b['uv']['rotation_degrees']))>1e-5:
                raise ValueError('UV meter scale/rotation mismatch')
            if 'region' in b:
                points=[v.co for v in obj.data.vertices];r=b['region']
                if r['xmin']<min(v.x for v in points)-1e-5 or r['xmax']>max(v.x for v in points)+1e-5 or r['ymin']<min(v.y for v in points)-1e-5 or r['ymax']>max(v.y for v in points)+1e-5:raise ValueError('material region outside object bounds')
            if 'normal' in record['texture_references']:
                tangent_name='SceneFactoryTangent.m'+str(i);layer=obj.data.uv_layers.get(tangent_name)
                if layer is None or mat.node_tree.nodes[prefix+'normal_map'].uv_map!=tangent_name:raise ValueError('missing mapped tangent UV')
                raw=obj.data.uv_layers['SceneFactoryUV'];angle=math.radians(b['uv']['rotation_degrees']);sx,sy=b['uv']['meters_per_repeat']
                for j,loop in enumerate(raw.data):
                    u,v=loop.uv.x/sx,loop.uv.y/sy;expected=(math.cos(angle)*u-math.sin(angle)*v,math.sin(angle)*u+math.cos(angle)*v)
                    if any(abs(a-e)>2e-5 for a,e in zip(layer.data[j].uv,expected)):raise ValueError('normal tangent UV scale/direction mismatch')
            if 'normal' in record['texture_references'] and abs(mat.node_tree.nodes[prefix+'normal_map'].inputs['Strength'].default_value-record['parameters']['normal_strength'])>1e-5:raise ValueError('normal map strength mismatch')
            if 'height' in record['texture_references'] and abs(mat.node_tree.nodes[prefix+'bump'].inputs['Distance'].default_value-record['parameters']['bump_distance'])>1e-5:raise ValueError('height bump distance mismatch')
            for channel,t in record['texture_references'].items():
                tex=mat.node_tree.nodes.get(prefix+channel)
                if tex is None or tex.image.colorspace_settings.name!=t['color_space']:raise ValueError('texture channel/color space mismatch')
                asset=bundle['assets'][canonical_digest(t['asset'])];file=next(f for f in asset['files'] if f['path']==t['file'])
                if hashlib.sha256(tex.image.packed_file.data).hexdigest()!=file['sha256']:raise ValueError('packed texture hash mismatch')
                texture_hashes.add(file['sha256']);local_hashes.add(file['sha256'])
        inventory[aid]={'bindings':bindings,'material_refs':{b['material']:plan['appearance']['materials'][b['material']] for b in bindings},
                        'uv_digest':uv_digest(obj),'shader_digest':actual,'texture_hashes':sorted(local_hashes)}
    return inventory,{'kind':'appearance','state':'passed','material_count':len(groups),'texture_count':len(texture_hashes),'asset_count':sum('asset_key' in n for n in plan['nodes']),
                      'material_build_seconds':bpy.context.scene.get('material_build_seconds',0),'checks':['PBR','texture_hashes','color_spaces','metric_UV','bindings','offline_resources',*(['no_coplanar_surface_overlap'] if not skip_spatial else [])]}


def no_coplanar_overlap(objects):
    """Reject positive-area overlap of convex upward faces; opposite-facing
    foundation/ground contact is intentional and is not rejected."""
    buckets={}
    for obj in objects:
        for face in obj.data.polygons:
            normal=(obj.matrix_world.to_3x3().inverted().transposed() @ face.normal).normalized()
            if normal.z<.99999:continue
            points=[obj.matrix_world @ obj.data.vertices[i].co for i in face.vertices]
            z=sum(v.z for v in points)/len(points)
            if max(abs(v.z-z) for v in points)>1e-5:continue
            polygon=[(v.x,v.y) for v in points]
            bounds=(min(v[0] for v in polygon),max(v[0] for v in polygon),min(v[1] for v in polygon),max(v[1] for v in polygon))
            bucket=round(z,5)
            for old_obj,old,box in buckets.get(bucket,[]):
                if obj==old_obj or min(bounds[1],box[1])-max(bounds[0],box[0])<=1e-5 or min(bounds[3],box[3])-max(bounds[2],box[2])<=1e-5:continue
                separated=False
                for poly in (polygon,old):
                    for a,b in zip(poly,poly[1:]+poly[:1]):
                        axis=(b[1]-a[1],a[0]-b[0]);length=math.hypot(*axis)
                        if length<1e-8:continue
                        p=[(v[0]*axis[0]+v[1]*axis[1])/length for v in polygon];q=[(v[0]*axis[0]+v[1]*axis[1])/length for v in old]
                        if min(max(p),max(q))-max(min(p),min(q))<=1e-5:separated=True;break
                    if separated:break
                if not separated:raise ValueError('overlapping coplanar upward surfaces: '+obj.name+' / '+old_obj.name)
            buckets.setdefault(bucket,[]).append((obj,polygon,bounds))
