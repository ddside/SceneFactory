"""Project operations and transactional validated-build promotion."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import struct
import platform
import hashlib
import uuid

from .runner import run_blender
from .spec import example_spec, load_spec, read_json
from .storage import check_artifacts, digest, project_lock, write_json
from . import __version__


def new_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]


def implementation_hash():
    root = Path(__file__).parent
    files = {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*.py"))}
    return hashlib.sha256(str(sorted(files.items())).encode()).hexdigest()


def init_project(path):
    path = Path(path).resolve()
    spec = example_spec(path.name)
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


def latest_build(project):
    project = Path(project).resolve()
    build_id = state(project)["last_successful_build"]
    if not build_id or not isinstance(build_id, str) or Path(build_id).name != build_id:
        raise ValueError("No successful build. Run scene-factory build first.")
    directory = project / "builds" / build_id
    metadata = read_json(directory / "build.json")
    if metadata.get("status") != "validated":
        raise ValueError(f"Build {build_id} is not validated")
    required = {"scene.json", "scene.blend", "result.json", "validation.json"}
    if set(metadata.get("sha256", {})) != required:
        raise ValueError("Build manifest has missing or unexpected artifact entries")
    check_artifacts(directory, metadata["sha256"])
    return directory, metadata


def run_build(project, executable, options):
    project = Path(project).resolve()
    with project_lock(project):
        build_id = new_id()
        directory = project / "builds" / build_id
        directory.mkdir(parents=True)
        metadata = {"build_id": build_id, "status": "staging", "error": None}
        write_json(directory / "build.json", metadata)
        record_operation(project, "build", directory, "staging")
        try:
            spec = load_spec(project / "scene.json")
            write_json(directory / "scene.json", spec)
            built = run_blender(executable, {"action": "build", "spec_path": str(directory / "scene.json")},
                                directory, options["timeout"])
            if not (directory / "scene.blend").is_file() or (directory / "scene.blend").stat().st_size == 0:
                raise ValueError("Missing/empty artifact: scene.blend")
            checked = run_blender(executable, {
                "action": "validate", "spec_path": str(directory / "scene.json"),
                "blend_path": str(directory / "scene.blend")}, directory / "reopen", options["timeout"])
            if not checked.get("reopened") or built.get("structure_sha256") != checked.get("structure_sha256"):
                raise ValueError("Reopened scene does not match generated structure")
            write_json(directory / "validation.json", checked)
            metadata.update(status="validated", structure_sha256=checked["structure_sha256"],
                            blender=built["blender"], blender_hash=built["blender_hash"],
                            application_version=__version__, implementation_sha256=implementation_hash(),
                            application_python=platform.python_version(),
                            blender_python=built["blender_python"],
                            sha256={name: digest(directory / name) for name in
                                    ("scene.json", "scene.blend", "result.json", "validation.json")})
            write_json(directory / "build.json", metadata)
            # Only this atomic state update publishes the validated build.
            record_operation(project, "build", directory, "validated", promote=build_id)
            return {"build_id": build_id, "directory": str(directory), **metadata}
        except Exception as exc:
            metadata.update(status="failed", error=str(exc))
            write_json(directory / "build.json", metadata)
            record_operation(project, "build", directory, "failed", str(exc))
            raise


def verify_png(path, resolution):
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid/missing PNG artifact: {path}")
    if struct.unpack(">II", header[16:24]) != (resolution, resolution):
        raise ValueError("Preview resolution mismatch")


def verify_preview(project, build_dir):
    preview = read_json(build_dir / "preview.json")
    check_artifacts(project, {preview["path"]: preview["sha256"]})
    check_artifacts(build_dir, {"preview.png": preview["sha256"]})
    return preview


def operate(project, action, executable, options):
    project = Path(project).resolve()
    with project_lock(project):
        directory = project / "operations" / new_id()
        directory.mkdir(parents=True)
        record_operation(project, action, directory, "staging")
        try:
            build_dir, metadata = latest_build(project)
            if action == "validate" and (build_dir / "preview.json").exists():
                verify_preview(project, build_dir)
            if load_spec(project / "scene.json") != load_spec(build_dir / "scene.json"):
                raise ValueError("Scene Specification changed since the successful build; build again first")
            request = {"action": action, "spec_path": str(build_dir / "scene.json"),
                       "blend_path": str(build_dir / "scene.blend"), **options}
            result = run_blender(executable, request, directory, options["timeout"])
            if result.get("structure_sha256") != metadata["structure_sha256"]:
                raise ValueError("Structure fingerprint differs from validated build")
            if action == "preview":
                verify_png(directory / "preview.png", options["resolution"])
                # Publish preview only after successful rendering and file checks.
                preview = {"path": str((directory / "preview.png").relative_to(project)),
                           "sha256": digest(directory / "preview.png"), "render": result["render"]}
                # Root convenience artifact, copied atomically, original operation is immutable.
                temporary = build_dir / ".preview.png"
                shutil.copyfile(directory / "preview.png", temporary)
                temporary.replace(build_dir / "preview.png")
                write_json(build_dir / "preview.json", preview)
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
        data["spec_matches_build"] = load_spec(project / "scene.json") == load_spec(directory / "scene.json")
        if (directory / "preview.json").exists():
            data["preview"] = verify_preview(project, directory)
    except ValueError as exc:
        data["artifact_integrity"] = False
        data["integrity_error"] = str(exc)
    return data
