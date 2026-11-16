"""Explicit candidate integration checks and evidence-based catalog activation."""
import copy
from pathlib import Path
import platform
import time
import xml.etree.ElementTree as ET

from .compiler import compile_scene
from .registry import Registry, file_hash
from .runner import run_blender
from .storage import write_json
from .artifacts import check_manifest


def unit_test_evidence(path):
    if path is None:
        raise ValueError("--activate requires --test-report from a passing pytest --junitxml unit test run")
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid unit test XML report: {exc}") from exc
    cases = list(root.iter("testcase"))
    if not cases or any(list(case.iter(tag)) for case in cases for tag in ("failure", "error", "skipped")):
        raise ValueError("unit test report must contain passing cases without failure/error/skip")
    return {"sha256": file_hash(path), "case_count": len(cases),
            "cases": [f"{c.get('classname')}.{c.get('name')}" for c in cases]}


def validate_skill(skill_id, version, executable, directory, timeout=120, activate=False, test_report=None):
    registry = Registry()
    manifest = registry.get(skill_id, version, (skill_id,))
    if manifest["validation_status"] == "disabled":
        raise ValueError("Disabled skill must be explicitly returned to candidate state before testing")
    units = unit_test_evidence(test_report) if activate else None
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    tests = []
    scenes = manifest.get("test_scenes") or [
        {"schema_version":2,"scene_id":"skill-validation","seed":42,"units":"m","nodes":[
            {"node_id":"probe","skill":{"skill_id":skill_id,"version":version},"transform":{},"parameters":p}]}
        for p in manifest["examples"]]
    for i, spec in enumerate(scenes):
        output = directory / f"example-{i}"
        output.mkdir()
        write_json(output / "scene.json", spec)
        from .resources import resolve_resources,stage_resources
        from .library import Catalog
        from .registry import PACKAGE
        catalog=Catalog(PACKAGE/manifest['test_catalog']) if 'test_catalog' in manifest else None
        resources=resolve_resources(spec,catalog)
        stage_resources(output,resources,catalog)
        compiled = compile_scene(spec, registry, file_hash(output / "scene.json"), allow_candidates=(skill_id,),resources=resources)
        plan = compiled["build_plan"]
        if not any(n['skill']=={'skill_id':skill_id,'version':version} for n in plan['nodes']):
            raise ValueError('skill validation fixture must exercise the target skill/version')
        write_json(output / "plan.json", plan)
        request = {"action":"build","spec_path":str(output / "scene.json"),"plan_path":str(output / "plan.json"),
                   "plan_digest":plan["plan_digest"],"skill_validation":True}
        started = time.monotonic()
        built = run_blender(executable, request, output, timeout)
        if not (output / "scene.blend").is_file() or (output / "scene.blend").stat().st_size == 0:
            raise ValueError("skill validation: missing .blend artifact")
        checked = run_blender(executable, {**request,"action":"validate","blend_path":str(output / "scene.blend")},
                              output / "reopen", timeout)
        check_manifest(checked["artifact_manifest"], plan["expected_artifacts"])
        if built["structure_sha256"] != checked["structure_sha256"]:
            raise ValueError("skill validation: reopened structure mismatch")
        tests.append({"example":i,"checks":["compile","generate","skill-validator","reopen","artifact-contract"],
                      "structure_sha256":checked["structure_sha256"],"plan_digest":plan["plan_digest"],
                      "metrics":{"build_reopen_seconds":round(time.monotonic()-started,3),
                                 "mesh_count":sum(a['type']=='Mesh' for a in checked['artifact_manifest']['artifacts']),
                                 "vertex_count":sum(a['vertex_count'] for a in checked['artifact_manifest']['artifacts']),
                                 "face_count":sum(a['face_count'] for a in checked['artifact_manifest']['artifacts'])}})
    evidence = {"status":"passed","pin":registry.pin(manifest),"tests":tests,"unit_tests":units,
                "runtime":{"blender":built["blender"],"blender_python":built["blender_python"],
                           "implementation_sha256":built["runtime_implementation_sha256"],
                           "os":platform.system(),"architecture":platform.machine(),"application_python":platform.python_version()}}
    write_json(directory / "validation-evidence.json", evidence)
    if activate:
        # Recheck source hashes after all subprocesses; never attest changed code.
        current = Registry()
        current_manifest = current.manifests[(skill_id, version)]
        if current.pin(current_manifest) != evidence["pin"]:
            raise ValueError("skill implementation changed while validation was running")
        updated = copy.deepcopy(current_manifest)
        updated.update(validation_status="validated",validation_evidence=evidence)
        write_json(current.paths[(skill_id,version)], updated)
    return {"skill_id":skill_id,"version":version,"activated":activate,"directory":str(directory),"evidence":evidence}
