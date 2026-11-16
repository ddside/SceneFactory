"""Reviewed format registration, independent of Providers and Catalog storage.

Adding another format means adding a pure inspector here and a Blender importer;
USD records may already be stored without claiming import/format validation.
"""
from .gltf_contract import inspect_gltf

FORMATS={'gltf':{'inspector':inspect_gltf,'metadata_key':'gltf','units':'m','up_axis':'Y','importer':'gltf','version':'1.0.0'}}
