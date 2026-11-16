"""Data-only skill catalog. Entry points are bound by a reviewed allowlist."""
import ast
import copy
from functools import lru_cache
from pathlib import Path

from .spec import SpecError, fields, identifier, read_json
from .contract_utils import (TYPES, canonical_digest, check_digest, check_expression,
                             check_version, parameter_schema, topological_order)

CATALOG = Path(__file__).parent / "skills"
PACKAGE = Path(__file__).parent


@lru_cache(maxsize=32)
def defined_functions(source):
    # Cache syntax analysis by exact source bytes, never by path/mtime. Every
    # binding still reads/hashes current source and all reviewed support files.
    tree = ast.parse(source, feature_version=(3, 11))
    return frozenset(node.name for node in tree.body if isinstance(node, ast.FunctionDef))


def file_hash(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_digest(manifest):
    return canonical_digest({k: v for k, v in manifest.items() if k not in ("validation_status", "validation_evidence")})


class Registry:
    def __init__(self, directory=CATALOG, bindings=None):
        self.directory = Path(directory)
        self.bindings = read_json(self.directory / "entrypoints.json") if bindings is None else copy.deepcopy(bindings)
        if not isinstance(self.bindings,dict):
            raise SpecError("entrypoints: expected reviewed binding object")
        self.manifests = {}
        self.paths = {}
        for path in sorted(self.directory.glob("*.skill.json")):
            manifest = read_json(path)
            self.check_manifest(manifest)
            key = (manifest["skill_id"], manifest["version"])
            if key in self.manifests:
                raise SpecError(f"skill registry: duplicate version {key}")
            self.manifests[key] = manifest
            self.paths[key] = path
        edges = {}
        for key, manifest in self.manifests.items():
            name = "@".join(key)
            edges[name] = [f"{d['skill_id']}@{d['version']}" for d in manifest["dependencies"]]
            if manifest["kind"] == "recipe":
                declared = {(d["skill_id"], d["version"]) for d in manifest["dependencies"]}
                for child in manifest["recipe"]["nodes"]:
                    if (child["skill"]["skill_id"], child["skill"]["version"]) not in declared:
                        raise SpecError(f"{name}: recipe child missing declared dependency")
        topological_order(edges, "skill dependencies")

    def binding(self, key):
        if not isinstance(key, str) or key not in self.bindings:
            raise SpecError(f"entry point: unknown/unregistered entry point {key!r}")
        entry = self.bindings[key]
        fields(entry, "entry point", ("module", "function"), ("support_files",))
        module, function = entry["module"], entry["function"]
        prefix = "scene_factory.blender.skills."
        if (not isinstance(module, str) or not (module.startswith(prefix) or module == "scene_factory.architecture_contracts")
            or not all(x.isidentifier() for x in module.split("."))
            or not isinstance(function, str) or not function.isidentifier()):
            raise SpecError("entry point: only reviewed Blender skills and pure architectural contract bindings are allowed")
        path = PACKAGE.parent.joinpath(*module.split(".")).with_suffix(".py")
        if not path.is_file():
            raise SpecError(f"entry point: implementation file missing {module}")
        if function not in defined_functions(path.read_bytes()):
            raise SpecError(f"entry point: function not defined {module}:{function}")
        support = {}
        supporting = entry.get("support_files", [])
        if not isinstance(supporting,list) or not all(isinstance(x,str) for x in supporting):
            raise SpecError("entry point: support_files must be a string array")
        for relative in supporting:
            p = (PACKAGE / relative).resolve()
            if not p.is_relative_to(PACKAGE.resolve()) or not p.is_file() or p.suffix != ".py":
                raise SpecError("entry point: invalid reviewed support file")
            support[relative] = file_hash(p)
        return {"module": module, "function": function, "sha256": file_hash(path), "support_sha256": support}

    def check_manifest(self, value):
        required = ("schema_version", "skill_id", "version", "name", "description", "category", "tags",
                    "kind", "parameter_schema", "inputs", "outputs", "artifacts", "implementation",
                    "validator", "dependencies", "blender_compatibility", "examples", "validation_status")
        fields(value, "SkillManifest", required, ("recipe", "validation_evidence", "contract", "test_scenes", "asset_consumer", "test_catalog"))
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise SpecError("SkillManifest.schema_version: only 1 supported")
        identifier(value["skill_id"], "skill_id")
        check_version(value["version"], "skill.version")
        for key in ("name", "description", "category"):
            if not isinstance(value[key], str) or not value[key].strip():
                raise SpecError(f"SkillManifest.{key}: expected nonempty string")
        if not isinstance(value["tags"], list) or not all(isinstance(t, str) and t for t in value["tags"]):
            raise SpecError("SkillManifest.tags: expected string array")
        if value["kind"] not in ("leaf", "recipe"):
            raise SpecError("SkillManifest.kind: expected leaf/recipe")
        if value["validation_status"] not in ("candidate", "validated", "disabled"):
            raise SpecError("SkillManifest.validation_status: invalid status")
        if "validation_evidence" in value:
            fields(value["validation_evidence"], "validation_evidence", ("status","pin","tests","unit_tests","runtime"))
        parameter_schema(value["parameter_schema"], "parameter_schema")
        for category in ("inputs", "outputs"):
            if not isinstance(value[category], dict):
                raise SpecError(f"{category}: expected object")
            for name, port in value[category].items():
                identifier(name, category + ".port")
                fields(port, f"{category}.{name}", ("type", "required", "target") if category == "inputs" else ("type", "value"))
                if port["type"] not in TYPES:
                    raise SpecError(f"{category}.{name}: unsupported type")
                if category == "inputs":
                    if type(port["required"]) is not bool or not ((port["target"] == "elevation" and port["type"] == "Length") or (port["target"] == "reference" and port["type"] in ("WallRef", "OpeningRef", "SpaceRef"))):
                        raise SpecError(f"inputs.{name}: expected Length/elevation or architectural typed reference binding")
                else:
                    check_expression(port["value"], value["parameter_schema"], f"outputs.{name}")
        if not isinstance(value["artifacts"], list) or not value["artifacts"]:
            raise SpecError("artifacts: nonempty role declarations required")
        roles = set()
        for artifact in value["artifacts"]:
            fields(artifact, "artifacts", ("role", "type"))
            identifier(artifact["role"], "artifacts.role")
            if artifact["role"] in roles or artifact["type"] not in ("Mesh", "Object"):
                raise SpecError("artifacts: duplicate role or unsupported type")
            roles.add(artifact["role"])
        if "contract" in value:
            binding = self.binding(value["contract"])
            if binding["module"] != "scene_factory.architecture_contracts":
                raise SpecError("contract: only reviewed pure contract bindings allowed")
        if "test_scenes" in value and (not isinstance(value["test_scenes"], list) or not value["test_scenes"]):
            raise SpecError("test_scenes: nonempty full SceneSpec fixtures required")
        if 'asset_consumer' in value and type(value['asset_consumer']) is not bool:
            raise SpecError('asset_consumer must be boolean')
        if 'test_catalog' in value:
            catalog=(PACKAGE/value['test_catalog']).resolve()
            if not catalog.is_relative_to(PACKAGE.resolve()) or not catalog.is_dir():
                raise SpecError('test_catalog must be a reviewed packaged fixture directory')
        self.binding(value["implementation"])
        self.binding(value["validator"])
        if value["kind"] == "recipe":
            if value["implementation"] != "recipe.generate":
                raise SpecError("recipe: implementation must use reviewed recipe dispatcher")
            self.check_recipe(value)
        elif "recipe" in value:
            raise SpecError("leaf: recipe not allowed")
        if not isinstance(value["dependencies"], list):
            raise SpecError("dependencies: expected array")
        seen = set()
        for dependency in value["dependencies"]:
            fields(dependency, "dependency", ("skill_id", "version"))
            identifier(dependency["skill_id"], "dependency.skill_id")
            check_version(dependency["version"], "dependency.version")
            key = (dependency["skill_id"], dependency["version"])
            if key in seen:
                raise SpecError("dependencies: duplicate dependency")
            seen.add(key)
        if value["blender_compatibility"] != {"series": "4.5", "python_series": "3.11"}:
            raise SpecError("blender_compatibility: requires Blender 4.5 / Python 3.11")
        if not isinstance(value["examples"], list) or not value["examples"]:
            raise SpecError("examples: nonempty parameter examples required")
        from .contract_utils import normalize_parameters
        for example in value["examples"]:
            normalize_parameters(example, value["parameter_schema"], "examples")

    def check_recipe(self, manifest):
        recipe = manifest.get("recipe")
        fields(recipe, "recipe", ("nodes",))
        if not isinstance(recipe["nodes"], list) or not 1 <= len(recipe["nodes"]) <= 32:
            raise SpecError("recipe.nodes: expected 1..32 children")
        keys = set()
        for child in recipe["nodes"]:
            fields(child, "recipe.child", ("local_key", "skill", "parameters", "transform", "depends_on", "inputs"))
            identifier(child["local_key"], "recipe.local_key")
            if child["local_key"] in keys:
                raise SpecError("recipe: duplicate local_key")
            keys.add(child["local_key"])
            fields(child["skill"], "recipe.skill", ("skill_id", "version"))
            identifier(child["skill"]["skill_id"], "recipe.skill_id")
            check_version(child["skill"]["version"], "recipe.version")
            if not isinstance(child["parameters"], dict):
                raise SpecError("recipe.parameters: expected object")
            for expr in child["parameters"].values():
                check_expression(expr, manifest["parameter_schema"], "recipe.parameters")
            fields(child["transform"], "recipe.transform", (), ("location", "rotation_degrees", "scale"))
            for expr in child["transform"].values():
                check_expression(expr, manifest["parameter_schema"], "recipe.transform")
        edges = {}
        for child in recipe["nodes"]:
            if not isinstance(child["depends_on"], list) or not all(isinstance(x, str) for x in child["depends_on"]):
                raise SpecError("recipe.depends_on: expected local keys")
            if not isinstance(child["inputs"], dict):
                raise SpecError("recipe.inputs: expected object")
            references = set(child["depends_on"])
            for port in child["inputs"].values():
                fields(port, "recipe.input", ("node_id", "output"))
                identifier(port["node_id"], "recipe.input.node_id")
                identifier(port["output"], "recipe.input.output")
                references.add(port["node_id"])
            edges[child["local_key"]] = references
        topological_order(edges, "recipe child dependencies")

    def get(self, skill_id, version, allow_candidates=()):
        key = (skill_id, version)
        if key not in self.manifests:
            raise SpecError(f"skill {skill_id}@{version}: unregistered skill/version")
        manifest = self.manifests[key]
        if manifest["validation_status"] == "disabled":
            raise SpecError(f"skill {skill_id}: disabled")
        if manifest["validation_status"] != "validated" and skill_id not in allow_candidates:
            raise SpecError(f"skill {skill_id}: candidate is not validated")
        if manifest["validation_status"] == "validated" and skill_id not in allow_candidates:
            evidence = manifest.get("validation_evidence", {})
            expected = self.pin(manifest)
            if (evidence.get("status") != "passed" or evidence.get("pin") != expected
                or not evidence.get("tests") or not evidence.get("runtime") or not evidence.get("unit_tests")):
                raise SpecError(f"skill {skill_id}: missing/stale validation evidence; validate again")
        return copy.deepcopy(manifest)

    def pin(self, manifest):
        return {"skill_id": manifest["skill_id"], "version": manifest["version"],
                "manifest_sha256": manifest_digest(manifest),
                "implementation": self.binding(manifest["implementation"]),
                "validator": self.binding(manifest["validator"]),
                **({"contract": self.binding(manifest["contract"])} if "contract" in manifest else {}),
                "dependencies": manifest["dependencies"],
                "dependency_pins": [self.pin(self.manifests[(d["skill_id"],d["version"])]) for d in manifest["dependencies"]]}

    def runtime_digest(self):
        return canonical_digest({str(p.relative_to(PACKAGE)):file_hash(p) for p in sorted(PACKAGE.rglob("*.py"))})

    def search(self, query=""):
        query = query.lower()
        return [copy.deepcopy(m) for key, m in sorted(self.manifests.items()) if query in
                " ".join([m["skill_id"], m["name"], m["description"], m["category"], *m["tags"]]).lower()]
