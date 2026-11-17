"""Project operations and transactional validated-build promotion."""
from datetime import datetime, timezone
from contextlib import nullcontext
from pathlib import Path
import shutil
import platform
import uuid
import time

from .runner import run_blender, RunnerError
from .spec import example_spec, load_spec, read_json
from .storage import check_artifacts, digest, project_lock, write_json
from . import __version__
from .compiler import compile_scene, verify_plan
from .scene_v2 import example_v2
from .artifacts import check_manifest
from .quality import report as quality_report, validate_report
from .png import verify_png
from .contract_utils import canonical_digest


def new_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]


def implementation_hash():
    root = Path(__file__).parent
    files = {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*.py"))}
    return canonical_digest(files)


def init_project(path, schema_version=1):
    path = Path(path).resolve()
    if schema_version not in (1,2):
        raise ValueError("schema_version must be 1 or 2")
    spec = example_spec(path.name) if schema_version == 1 else example_v2(path.name)
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / "scene.json", spec)
    (path / "scene-factory.toml").write_text(
        '# Blender resolved via CLI, SCENE_FACTORY_BLENDER, PATH or OS candidates.\n'
        'timeout = 120.0\ndevice = "cpu"\nresolution = 256\nsamples = 8\n', encoding="utf-8")
    write_json(path / "state.json", {"latest": None, "last_successful_build": None})
    return {"project": str(path), "spec": str(path / "scene.json")}


def state(project):
    return read_json(Path(project) / "state.json")


def record_operation(project, action, directory, status, error=None, promote=None):
    data = state(project)
    data["latest"] = {"action": action, "directory": str(directory.relative_to(project)),
                      "status": status, "error": error, "at": datetime.now(timezone.utc).isoformat()}
    if promote is not None:
        data["last_successful_build"] = promote
    write_json(project / "state.json", data)


def current_spec_path(project):
    data=state(project)
    if data.get('working_revision'):
        from .workflow_store import load_record, revision_spec
        revision_spec(project,data['working_revision'])
        record=load_record(project,'revision',data['working_revision'])
        return Path(project)/record['scene_spec_snapshot']
    return Path(project)/'scene.json'


def remaining_timeout(options):
    remaining=options.get('_deadline_epoch',float('inf'))-time.time()
    if remaining<=0: raise RunnerError('Workflow total time budget exhausted')
    return min(options['timeout'],remaining)


def latest_build(project):
    return build_at(project,state(project)['last_successful_build'])


def build_at(project,build_id):
    project = Path(project).resolve()
    if not build_id or not isinstance(build_id, str) or Path(build_id).name != build_id or build_id in ('.','..'):
        raise ValueError("No successful build. Run scene-factory build first.")
    directory = project / "builds" / build_id
    metadata = read_json(directory / "build.json")
    if metadata.get("status") != "validated":
        raise ValueError(f"Build {build_id} is not validated")
    required = {"scene.json", "scene.blend", "result.json", "validation.json"}
    if metadata.get("manifest_version") == 2:
        required.update(("scene-v2.json", "plan.json", "resolved-scene.json", "skills.lock.json", "artifact-manifest.json", "quality.json"))
    required.update(metadata.get("resource_files",[]))
    if metadata.get("effects_cache"):required.update(("base-scene.blend","base-state.json"))
    if set(metadata.get("sha256", {})) != required:
        raise ValueError("Build manifest has missing or unexpected artifact entries")
    check_artifacts(directory, metadata["sha256"])
    if metadata.get("manifest_version") == 2:
        plan = verify_plan(read_json(directory / "plan.json"))
        if metadata["plan_digest"] != plan["plan_digest"]:
            raise ValueError("Build metadata / plan digest mismatch")
        manifest = check_manifest(read_json(directory / "artifact-manifest.json"), plan["expected_artifacts"])
        if manifest["plan_digest"] != plan["plan_digest"]:
            raise ValueError("ArtifactManifest / BuildPlan digest mismatch")
        validate_report(read_json(directory / "quality.json"))
        if 'resources' in plan:
            from .resources import resource_files,verify_resources
            if sorted(metadata.get('resource_files',[]))!=sorted(resource_files(plan['resources'])):raise ValueError('resource file inventory mismatch')
            verify_resources(directory,plan['resources'])
    return directory, metadata


def run_build(project, executable, options, source_path=None, _locked=False):
    project = Path(project).resolve()
    with (nullcontext() if _locked else project_lock(project)):
        build_id = new_id()
        directory = project / "builds" / build_id
        directory.mkdir(parents=True)
        metadata = {"build_id": build_id, "status": "staging", "error": None}
        write_json(directory / "build.json", metadata)
        record_operation(project, "build", directory, "staging")
        completed, stage = [], "specification"
        try:
            shutil.copyfile(source_path or current_spec_path(project), directory / "scene.json")
            compiled = prepare_plan(directory / "scene.json", directory)
            plan = compiled["build_plan"]
            metadata.update(manifest_version=2, source_schema_version=plan["source_schema_version"], plan_digest=plan["plan_digest"])
            completed.append("specification")
            write_json(directory / "quality.json", quality_report(completed))
            stage = "execution"
            request = {"action":"build", "spec_path":str(directory / "scene.json"),
                       "plan_path":str(directory / "plan.json"),"plan_digest":plan["plan_digest"]}
            if 'effects' in plan:
                previous=state(project).get('last_successful_build')
                if previous:
                    old,oldmeta=build_at(project,previous)
                    oldplan=read_json(old/'plan.json')
                    if oldmeta.get('effects_cache') and oldplan['effects_baseline_plan']['plan_digest']==plan['effects_baseline_plan']['plan_digest']:
                        request['reuse_effect_base']=effect_cache_request(old,oldmeta)
            built = run_blender(executable, request,
                                directory, remaining_timeout(options))
            if not (directory / "scene.blend").is_file() or (directory / "scene.blend").stat().st_size == 0:
                raise ValueError("Missing/empty artifact: scene.blend")
            completed.append("execution")
            stage = "structure"
            if "effects_cache" in built:request["effect_base_cache"]=built["effects_cache"]
            checked = run_blender(executable, {**request,
                "action": "validate",
                "blend_path": str(directory / "scene.blend")}, directory / "reopen", remaining_timeout(options))
            if not checked.get("reopened") or built.get("structure_sha256") != checked.get("structure_sha256"):
                raise ValueError("Reopened scene does not match generated structure")
            write_json(directory / "validation.json", checked)
            check_manifest(checked["artifact_manifest"], plan["expected_artifacts"])
            write_json(directory / "artifact-manifest.json", checked["artifact_manifest"])
            completed.append("structure")
            write_json(directory / "quality.json", quality_report(completed))
            metadata.update(status="validated", structure_sha256=checked["structure_sha256"],
                            blender=built["blender"], blender_hash=built["blender_hash"],
                            application_version=__version__, implementation_sha256=implementation_hash(),
                            application_python=platform.python_version(),
                            blender_python=built["blender_python"],
                            sha256={name: digest(directory / name) for name in
                                    ("scene.json", "scene.blend", "result.json", "validation.json", "scene-v2.json",
                                     "plan.json", "resolved-scene.json", "skills.lock.json", "artifact-manifest.json", "quality.json")})
            if 'resources' in plan:
                from .resources import resource_files
                metadata['resource_files']=resource_files(plan['resources'])
                metadata['sha256'].update({name:digest(directory/name) for name in metadata['resource_files']})
            if 'effects' in plan:
                metadata['effects_cache']=True
                metadata['sha256'].update({name:digest(directory/name) for name in ['base-scene.blend','base-state.json']})
            write_json(directory / "build.json", metadata)
            # Only this atomic state update publishes the validated build.
            record_operation(project, "build", directory, "validated", promote=build_id)
            return {"build_id": build_id, "directory": str(directory), **metadata}
        except Exception as exc:
            write_json(directory / "quality.json", quality_report(completed, (stage, str(exc))))
            metadata.update(status="failed", error=str(exc))
            write_json(directory / "build.json", metadata)
            record_operation(project, "build", directory, "failed", str(exc))
            raise


def prepare_plan(source_path, directory):
    source = read_json(source_path)
    from .resources import resolve_resources,stage_resources
    resources=resolve_resources(source)
    stage_resources(directory,resources)
    compiled = compile_scene(source, resources=resources, source_sha256=digest(source_path), runtime_profile={
        "application_python": platform.python_version(), "os": platform.system(), "architecture": platform.machine()})
    for filename, data in (("scene-v2.json", compiled["resolved_scene"]["authoring_spec"]),
                           ("resolved-scene.json", compiled["resolved_scene"]),
                           ("plan.json", compiled["build_plan"]), ("skills.lock.json", compiled["skills_lock"])):
        write_json(directory / filename, data)
    return compiled


def compile_project(project):
    project = Path(project).resolve()
    with project_lock(project):
        directory = project / "operations" / new_id()
        directory.mkdir(parents=True)
        record_operation(project,"compile",directory,"staging")
        try:
            shutil.copyfile(current_spec_path(project), directory / "scene.json")
            compiled = prepare_plan(directory / "scene.json", directory)
            record_operation(project, "compile", directory, "succeeded")
            return {"directory":str(directory),"plan_digest":compiled["build_plan"]["plan_digest"],
                    "node_count":len(compiled["build_plan"]["nodes"])}
        except Exception as exc:
            write_json(directory/"error.json",{"error":str(exc)})
            record_operation(project,"compile",directory,"failed",str(exc))
            raise


def verify_preview(project, build_dir):
    preview = read_json(build_dir / "preview.json")
    original = (project / preview["path"]).resolve()
    if not original.is_relative_to(project.resolve()):
        raise ValueError("Preview reference escapes project directory")
    check_artifacts(project, {preview["path"]: preview["sha256"]})
    if preview.get("schema_version") == 2:
        verify_png(original, preview["resolution"])
    else:
        # Existing Phase 1 preview records keep their original integrity contract.
        check_artifacts(build_dir, {"preview.png": preview["sha256"]})
    return preview


def operate(project, action, executable, options, build_id=None, check_working_spec=True, _locked=False):
    project = Path(project).resolve()
    with (nullcontext() if _locked else project_lock(project)):
        directory = project / "operations" / new_id()
        directory.mkdir(parents=True)
        record_operation(project, action, directory, "staging")
        try:
            build_dir, metadata = build_at(project,build_id) if build_id else latest_build(project)
            if action == "validate" and (build_dir / "preview.json").exists():
                verify_preview(project, build_dir)
            if check_working_spec and load_spec(current_spec_path(project)) != load_spec(build_dir / "scene.json"):
                raise ValueError("Scene Specification changed since the successful build; build again first")
            request = {"action": action, "spec_path": str(build_dir / "scene.json"),
                       "blend_path": str(build_dir / "scene.blend"), **{k:v for k,v in options.items() if not k.startswith('_')}}
            if metadata.get("manifest_version") == 2:
                request.update(plan_path=str(build_dir / "plan.json"), plan_digest=metadata["plan_digest"])
            if metadata.get("effects_cache"):request["effect_base_cache"]=effect_cache_request(build_dir,metadata)
            result = run_blender(executable, request, directory, remaining_timeout(options))
            if result.get("structure_sha256") != metadata["structure_sha256"]:
                raise ValueError("Structure fingerprint differs from validated build")
            if action == "preview":
                verify_png(directory / "preview.png", options["resolution"])
                # Publish preview only after successful rendering and file checks.
                preview = {"schema_version":2,"path": str((directory / "preview.png").relative_to(project)),
                           "sha256": digest(directory / "preview.png"), "resolution":options["resolution"],
                           "render": result["render"],"attempt_id":directory.name}
                # A first-preview snapshot for Phase 1 consumers only. Never updated,
                # never authoritative, never checked against a later canonical preview.
                if metadata.get("source_schema_version",1) == 1 and not (build_dir / "preview.png").exists():
                    shutil.copyfile(directory / "preview.png", build_dir / "preview.png")
                record_operation(project, action, directory, "succeeded")
                # Final publication is ONE atomic reference update, after all other writes.
                write_json(build_dir / "preview.json", preview)
            else:
                record_operation(project, action, directory, "succeeded")
            return {"build_id": metadata["build_id"], "directory": str(directory), **result}
        except Exception as exc:
            write_json(directory / "error.json", {"error": str(exc)})
            record_operation(project, action, directory, "failed", str(exc))
            raise


def status(project):
    project = Path(project).resolve()
    data = state(project)
    try:
        directory, metadata = latest_build(project)
        data["artifacts"] = {name: str(directory / name) for name in metadata["sha256"]}
        data["artifact_integrity"] = True
        data["spec_matches_build"] = load_spec(current_spec_path(project)) == load_spec(directory / "scene.json")
        if (directory / "preview.json").exists():
            data["preview"] = verify_preview(project, directory)
        if metadata.get("manifest_version") == 2:
            data["quality"] = read_json(directory / "quality.json")
    except ValueError as exc:
        data["artifact_integrity"] = False
        data["integrity_error"] = str(exc)
    if data.get('working_revision'):
        from .workflow import resume_context
        data['workflow']=resume_context(project)
    return data


def effect_cache_request(directory,metadata):
    plan=read_json(directory/'plan.json')
    return dict(blend_path=str(directory/'base-scene.blend'),state_path=str(directory/'base-state.json'),
                blend_sha256=metadata['sha256']['base-scene.blend'],state_sha256=metadata['sha256']['base-state.json'],
                plan_digest=plan['effects_baseline_plan']['plan_digest'])
