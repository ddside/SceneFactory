"""Registered glTF import adapter. No .blend execution or forced mesh joining."""
import hashlib,json,tempfile,time
from pathlib import Path
import bpy
from scene_factory.blender.appearance import signature
from scene_factory.contract_utils import canonical_digest
from .common import close


def generate(node,context):
    started=time.monotonic();record=context['plan']['resources']['assets'][node['asset_key']]
    cached=context.get('asset_prototypes',{}).get(node['asset_key'])
    if cached:
        objects={role:obj.copy() for role,obj in cached.items()}
        for obj in objects.values():bpy.context.scene.collection.objects.link(obj)
        objects['frame']['asset_import_seconds']=0.
        return objects
    base=Path(context['resource_root'])/'resources'/record['local_cache_path'];doc=json.loads((base/record['entrypoint']).read_text())
    prefix='sf'+hashlib.sha256(node['node_id'].encode()).hexdigest()[:24]
    for i,n in enumerate(doc['nodes']):n['name']=prefix+'_%04d'%i
    for collection in ('buffers','images'):
        for item in doc.get(collection,[]):
            if 'uri' in item and not item['uri'].startswith('data:'):item['uri']=str((base/item['uri']).resolve())
    before=set(bpy.context.scene.objects)
    with tempfile.TemporaryDirectory(prefix='scene-factory-gltf-') as tmp:
        file=Path(tmp)/'import.gltf';file.write_text(json.dumps(doc))
        if bpy.ops.import_scene.gltf(filepath=str(file),merge_vertices=False)!= {'FINISHED'}:raise ValueError('glTF import failed')
    imported=set(bpy.context.scene.objects)-before
    frame=bpy.data.objects.new(node['node_id'],None);bpy.context.scene.collection.objects.link(frame);objects={'frame':frame}
    for part in record['source_metadata']['gltf']['parts']:
        name=prefix+'_%04d'%part['source_index'];obj=next((o for o in imported if o.name==name),None)
        if obj is None:raise ValueError('imported glTF hierarchy differs from source: '+name)
        objects[part['role']]=obj
        if obj.type=='MESH':
            for mat in obj.data.materials:
                if mat is None or not mat.use_nodes:raise ValueError('imported material missing')
                for shader in mat.node_tree.nodes:
                    if shader.type=='TEX_IMAGE' and shader.image:
                        image=shader.image
                        if not image.packed_file:image.pack()
                        sha=hashlib.sha256(image.packed_file.data).hexdigest()
                        match=next((f for f in record['files'] if f['sha256']==sha),None)
                        if match:image.filepath='//resources/'+record['local_cache_path']+'/'+match['path']
            obj['asset_shader_hash']=canonical_digest([signature(m) for m in obj.data.materials])
    if set(objects.values())-{frame}!=imported:raise ValueError('unexpected objects produced by import adapter')
    context.get('asset_prototypes',{})[node['asset_key']]=objects
    frame['asset_import_seconds']=time.monotonic()-started
    return objects


def validate(node,objects,context):
    record=context['plan']['resources']['assets'][node['asset_key']]
    if objects['frame'].type!='EMPTY':raise ValueError('asset instance frame missing')
    valid_hashes={f['sha256'] for f in record['files']}
    for part in record['source_metadata']['gltf']['parts']:
        obj=objects[part['role']]
        if part['type']=='Mesh':
            if obj.type!='MESH' or not obj.data.polygons:raise ValueError('asset Mesh missing')
            vertices=[v.co for v in obj.data.vertices]
            for a in range(3):close([min(p[a] for p in vertices),max(p[a] for p in vertices)],[part['bounds'][0][a],part['bounds'][1][a]],'imported glTF local bounds')
            if len(obj.data.materials)!=part['material_count']:raise ValueError('imported material count mismatch')
            if obj.get('asset_shader_hash')!=canonical_digest([signature(m) for m in obj.data.materials]):raise ValueError('asset material/texture changed')
            for mat in obj.data.materials:
                for shader in mat.node_tree.nodes:
                    if shader.type=='NORMAL_MAP' and shader.inputs['Color'].is_linked:
                        producer=shader.inputs['Color'].links[0].from_node
                        if producer.type=='TEX_IMAGE' and producer.image.colorspace_settings.name!='Non-Color':raise ValueError('asset normal color space mismatch')
                    if shader.type=='BSDF_PRINCIPLED' and shader.inputs['Base Color'].is_linked:
                        producer=shader.inputs['Base Color'].links[0].from_node
                        if producer.type=='TEX_IMAGE' and producer.image.colorspace_settings.name!='sRGB':raise ValueError('asset base color space mismatch')
                    if shader.type=='TEX_IMAGE':
                        if shader.image is None or shader.image.packed_file is None:raise ValueError('asset texture dependency missing')
                        sha=hashlib.sha256(shader.image.packed_file.data).hexdigest()
                        # Embedded source images are covered by the glTF content hash.
                        if sha not in valid_hashes and any(f['path'].startswith('textures/') for f in record['files']):raise ValueError('asset texture content hash mismatch')
        elif obj.type!='EMPTY':raise ValueError('asset hierarchy object type mismatch')
