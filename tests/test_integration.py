"""Opt-in real Blender tests, CPU works on either supported OS.

Set SCENE_FACTORY_TEST_BLENDER to the executable. All subprocesses are real;
fault injection redirects the worker script, never mocks bpy or process success.
"""
import os
from pathlib import Path
import tempfile

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.project import init_project, latest_build, operate, run_build, state, status
from scene_factory.runner import RunnerError, run_blender
from scene_factory.spec import load_spec, read_json
from scene_factory.storage import digest, write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_project():
    executable = os.environ.get("SCENE_FACTORY_TEST_BLENDER")
    if not executable:
        pytest.skip("SCENE_FACTORY_TEST_BLENDER required for real integration")
    artifact_root = ROOT / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="phase1-integration-", dir=artifact_root))
    project = directory / "example"
    init_project(project)
    spec = load_spec(project / "scene.json")
    pillar = next(o for o in spec["objects"] if o["generator"] == "pillar")
    pillar["transform"].update(location=[4, -2, .1], rotation_degrees=[5, 10, 25], scale=[1.2, .8, 1.1])
    write_json(project / "scene.json", spec)
    result = run_build(project, executable, DEFAULTS)
    print(f"\nIntegration artifacts: {directory}")
    return project, executable, result


def test_build_four_generators_and_reopen(real_project):
    project, executable, result = real_project
    directory, metadata = latest_build(project)
    assert metadata["status"] == "validated"
    assert (directory / "scene.blend").stat().st_size > 0
    built = read_json(directory / "result.json")
    checked = read_json(directory / "validation.json")
    assert checked["reopened"] and checked["object_count"] == 4
    assert {o["generator"] for o in checked["objects"]} == {"ground", "box_building", "pillar", "roof"}
    assert {o["stable_id"] for o in checked["objects"]} == {o["stable_id"] for o in load_spec(project / "scene.json")["objects"]}
    assert built["structure_sha256"] == checked["structure_sha256"] == result["structure_sha256"]


def test_cpu_preview_and_validate(real_project):
    project, executable, _ = real_project
    options = {**DEFAULTS, "device": "cpu", "resolution": 128, "samples": 2}
    result = operate(project, "preview", executable, options)
    assert result["render"]["selected"] == "cpu"
    directory, _ = latest_build(project)
    assert (directory / "preview.png").stat().st_size > 24
    assert operate(project, "validate", executable, options)["reopened"]
    assert status(project)["artifact_integrity"]


def test_reproducible_structure(real_project):
    project, executable, result = real_project
    first, _ = latest_build(project)
    previous_hash = digest(first / "scene.blend")
    second = run_build(project, executable, DEFAULTS)
    assert second["build_id"] != result["build_id"]
    assert second["structure_sha256"] == result["structure_sha256"]
    assert digest(first / "scene.blend") == previous_hash


def test_actual_worker_exception_and_preservation(real_project, monkeypatch):
    import scene_factory.project as project_module
    project, executable, _ = real_project
    previous = state(project)["last_successful_build"]
    directory, metadata = latest_build(project)
    before = dict(metadata["sha256"])
    fault = project.parent / "raise_in_blender.py"
    fault.write_text('import bpy\nraise RuntimeError("intentional Blender integration fault")\n')

    def fault_runner(executable, request, directory, timeout):
        return run_blender(executable, request, directory, timeout, worker=fault)
    monkeypatch.setattr(project_module, "run_blender", fault_runner)
    with pytest.raises(RunnerError, match="exited 1"):
        run_build(project, executable, DEFAULTS)
    assert state(project)["last_successful_build"] == previous
    assert state(project)["latest"]["status"] == "failed"
    assert latest_build(project)[1]["sha256"] == before
    failed = project / state(project)["latest"]["directory"]
    assert "intentional Blender integration fault" in (failed / "blender.log").read_text()


def test_real_timeout_preserves_success(real_project):
    project, executable, _ = real_project
    previous = state(project)["last_successful_build"]
    with pytest.raises(RunnerError, match="timed out"):
        run_build(project, executable, {**DEFAULTS, "timeout": .001})
    assert state(project)["last_successful_build"] == previous
    latest_build(project)  # Checks all successful artifact hashes.


def test_unavailable_explicit_device_preserves_preview(real_project):
    project, executable, _ = real_project
    directory, _ = latest_build(project)
    operate(project, "preview", executable, {**DEFAULTS, "resolution": 64, "samples": 1})
    before = digest(directory / "preview.png")
    doctor = run_blender(executable, {"action": "doctor"}, project.parent / "device-doctor")
    assert any(p["ok"] for p in doctor["render_probes"])
    backends = {d["backend"] for d in doctor["devices"]}
    missing = next((d for d in ("metal", "cuda", "optix") if d not in backends), None)
    if missing is None:
        pytest.skip("All GPU backends enumerated; unavailable backend case not applicable")
    with pytest.raises(RunnerError):
        operate(project, "preview", executable, {**DEFAULTS, "device": missing})
    assert digest(directory / "preview.png") == before
    assert read_json(project / state(project)["latest"]["directory"] / "result.json")["ok"] is False


def test_reloaded_tampered_geometry_rejected(real_project):
    project, executable, _ = real_project
    directory, _ = latest_build(project)
    fault = project.parent / "tamper.py"
    corrupt = project.parent / "corrupt.blend"
    fault.write_text(
        'import bpy, json, sys\nfrom pathlib import Path\n'
        f'bpy.ops.wm.open_mainfile(filepath={str(directory / "scene.blend")!r})\n'
        'o = next(o for o in bpy.context.scene.objects if o.type == "MESH")\n'
        'o.data.vertices[0].co.x += 1\n'
        f'bpy.ops.wm.save_as_mainfile(filepath={str(corrupt)!r})\n'
        'Path(sys.argv[-1]).write_text(json.dumps({"ok": True}))\n')
    run_blender(executable, {}, project.parent / "tamper-run", worker=fault)
    with pytest.raises(RunnerError):
        run_blender(executable, {"action": "validate", "spec_path": str(directory / "scene.json"),
                                "blend_path": str(corrupt)}, project.parent / "tamper-validation")
    latest_build(project)
