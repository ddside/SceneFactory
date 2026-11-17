"""Strict lightweight ArtifactManifest contract shared across both runtimes."""
import math

from .contract_utils import canonical_digest, check_digest
from .spec import SpecError, fields, identifier


def matrix(value, path):
    if (not isinstance(value, list) or len(value) != 4 or any(not isinstance(row, list) or len(row) != 4 for row in value)
        or any(type(v) not in (int, float) or not math.isfinite(v) for row in value for v in row)):
        raise SpecError(f"{path}: expected finite 4x4 matrix")


def check_manifest(manifest, expected=None):
    fields(manifest, "ArtifactManifest", ("schema_version", "plan_digest", "artifact_count", "artifacts", "node_artifacts"))
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise SpecError("ArtifactManifest.schema_version: expected 1")
    check_digest(manifest["plan_digest"], "ArtifactManifest.plan_digest")
    if (not isinstance(manifest["artifacts"], list) or type(manifest["artifact_count"]) is not int
        or manifest["artifact_count"] != len(manifest["artifacts"])):
        raise SpecError("ArtifactManifest.artifact_count: inventory count mismatch")
    seen = set()
    actual = {}
    for artifact in manifest["artifacts"]:
        fields(artifact, "artifact", ("artifact_id", "source_node_id", "producer_node_id", "role", "local_role", "type",
            "lineage", "dependencies", "reference", "geometry_digest", "vertex_count", "face_count", "bounds",
            "local_matrix", "world_matrix"), ("component", "asset", "appearance", "damage", "effect"))
        for key in ("artifact_id", "source_node_id", "producer_node_id", "local_role"):
            identifier(artifact[key], f"artifact.{key}")
        if not isinstance(artifact["role"], str) or not artifact["role"]:
            raise SpecError("artifact.role: expected nonempty role")
        aid = artifact["artifact_id"]
        if aid in seen:
            raise SpecError("artifact.artifact_id: duplicate ID")
        seen.add(aid)
        if artifact["type"] not in ("Mesh", "Object"):
            raise SpecError("artifact.type: unsupported type")
        fields(artifact["reference"], "artifact.reference", ("object", "mesh"))
        if not isinstance(artifact["reference"]["object"], str) or not artifact["reference"]["object"]:
            raise SpecError("artifact.reference.object: expected diagnostic name")
        if artifact["type"] == "Mesh":
            check_digest(artifact["geometry_digest"], "artifact.geometry_digest")
            if not isinstance(artifact["reference"]["mesh"], str):
                raise SpecError("artifact.reference.mesh: expected mesh name")
        elif artifact["geometry_digest"] is not None or artifact["reference"]["mesh"] is not None:
            raise SpecError("Object artifact must not claim mesh geometry")
        for key in ("vertex_count", "face_count"):
            if type(artifact[key]) is not int or artifact[key] < 0:
                raise SpecError(f"artifact.{key}: expected nonnegative count")
        if (artifact["type"] == "Mesh" and (not artifact["vertex_count"] or not artifact["face_count"])):
            raise SpecError("Mesh artifact requires nonempty geometry counts")
        if artifact["type"] == "Object" and (artifact["vertex_count"] or artifact["face_count"]):
            raise SpecError("Empty Object artifact must have zero geometry counts")
        bounds = artifact["bounds"]
        if (not isinstance(bounds, list) or len(bounds) != 2
            or any(not isinstance(row, list) or len(row) != 3 for row in bounds)
            or any(type(v) not in (int, float) or not math.isfinite(v) for row in bounds for v in row)
            or any(bounds[0][i] > bounds[1][i] for i in range(3))):
            raise SpecError("artifact.bounds: expected finite ordered min/max")
        matrix(artifact["local_matrix"], "artifact.local_matrix")
        matrix(artifact["world_matrix"], "artifact.world_matrix")
        for key in ("dependencies", "lineage"):
            if (not isinstance(artifact[key], list) or not all(isinstance(x,str) for x in artifact[key])
                or len(set(artifact[key])) != len(artifact[key])):
                raise SpecError(f"artifact.{key}: expected unique ID array")
            for item in artifact[key]:
                identifier(item, "artifact." + key)
        actual[aid] = artifact
    for artifact in actual.values():
        if set(artifact["dependencies"]) - seen:
            raise SpecError("artifact.dependencies: missing artifact reference")
    if not isinstance(manifest["node_artifacts"], dict):
        raise SpecError("node_artifacts: expected source node mapping")
    recomputed = {}
    for artifact in actual.values():
        recomputed.setdefault(artifact["source_node_id"], []).append(artifact["artifact_id"])
    recomputed = {key: sorted(value) for key, value in recomputed.items()}
    if manifest["node_artifacts"] != recomputed:
        raise SpecError("node_artifacts: inconsistent source node mapping")
    if expected is not None:
        expected_by_id = {e["artifact_id"]: e for e in expected}
        if set(expected_by_id) != seen:
            raise SpecError("artifact inventory: missing or unexpected artifact IDs")
        for aid, declaration in expected_by_id.items():
            for key, value in declaration.items():
                if actual[aid][key] != value:
                    raise SpecError(f"artifact.{aid}.{key}: plan declaration mismatch")
    return manifest


def structure_digest(manifest):
    return canonical_digest([{key: a[key] for key in ("artifact_id", "source_node_id", "producer_node_id", "role", "type",
        "geometry_digest", "local_matrix", "world_matrix", "dependencies")} for a in
        sorted(manifest["artifacts"], key=lambda a: a["artifact_id"])])
