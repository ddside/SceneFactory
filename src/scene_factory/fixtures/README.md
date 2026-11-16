# Local import fixture provenance

`source/hierarchy.gltf` is a project-authored, synthetic pair of tetrahedra with
red/blue materials under an Empty parent. Its geometry, embedded buffer and
colors contain no third-party assets. The fixture data is explicitly CC0-1.0;
this statement is limited to this test asset and does not license project code.

`library/` is the frozen LocalAssetProvider registration used by the real Blender
`asset_instance` Skill activation. Records use portable URNs and relative cache
paths. It is an intentional, small test input, not a tracked generated scene or
Poly Haven download. Runtime builds and external asset bytes belong in ignored
`artifacts/`.
