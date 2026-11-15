from pathlib import Path

import pytest

from scene_factory.config import DEFAULTS
from scene_factory.project import init_project, latest_build, operate, run_build, state, status, verify_png
from scene_factory.spec import example_spec, read_json
from scene_factory.storage import digest, write_json


def prior_build(project):
    """Unit-test manifest fixture only; not a Blender integration result."""
    init_project(project)
    directory = project / "builds" / "previous"
    directory.mkdir(parents=True)
    write_json(directory / "scene.json", example_spec(project.name))
    for name in ("scene.blend", "result.json", "validation.json"):
        (directory / name).write_bytes(b"unit-test fixture")
    write_json(directory / "build.json", {"status": "validated", "build_id": "previous",
               "structure_sha256": "a" * 64, "sha256": {name: digest(directory / name) for name in
                   ("scene.json", "scene.blend", "result.json", "validation.json")}})
    write_json(project / "state.json", {"latest": None, "last_successful_build": "previous"})
    return directory


def test_successful_exit_missing_artifact_does_not_publish(tmp_path, monkeypatch):
    project = tmp_path / "example"
    previous = prior_build(project)
    before = digest(previous / "scene.blend")
    monkeypatch.setattr("scene_factory.project.run_blender", lambda *a, **k: {"ok": True})
    with pytest.raises(ValueError, match="Missing/empty.*scene.blend"):
        run_build(project, "blender", DEFAULTS)
    assert state(project)["last_successful_build"] == "previous"
    assert state(project)["latest"]["status"] == "failed"
    assert read_json(project / state(project)["latest"]["directory"] / "build.json")["status"] == "failed"
    assert digest(previous / "scene.blend") == before
    latest_build(project)


def test_invalid_spec_does_not_invoke_blender_or_publish(tmp_path, monkeypatch):
    project = tmp_path / "example"
    prior_build(project)
    (project / "scene.json").write_text('{"schema_version":99}')
    def must_not_run(*args, **kwargs):
        pytest.fail("Blender must not run for invalid specification")
    monkeypatch.setattr("scene_factory.project.run_blender", must_not_run)
    with pytest.raises(ValueError):
        run_build(project, "blender", DEFAULTS)
    assert state(project)["last_successful_build"] == "previous"


def test_manifest_integrity_and_changed_spec(tmp_path):
    project = tmp_path / "example"
    previous = prior_build(project)
    assert status(project)["spec_matches_build"]
    modified = example_spec(project.name)
    modified["seed"] += 1
    write_json(project / "scene.json", modified)
    assert status(project)["spec_matches_build"] is False
    with pytest.raises(ValueError, match="changed"):
        operate(project, "validate", "not invoked", DEFAULTS)
    (previous / "scene.blend").write_bytes(b"tampered")
    assert status(project)["artifact_integrity"] is False
    with pytest.raises(ValueError, match="hash mismatch"):
        latest_build(project)


def test_invalid_png_is_rejected(tmp_path):
    path = tmp_path / "preview.png"
    path.write_bytes(b"not a PNG")
    with pytest.raises(ValueError, match="PNG"):
        verify_png(path, 64)


def test_preview_copy_integrity(tmp_path):
    project = tmp_path / "example"
    previous = prior_build(project)
    original = project / "operations" / "test" / "preview.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"preview fixture")
    (previous / "preview.png").write_bytes(original.read_bytes())
    write_json(previous / "preview.json", {"path": str(original.relative_to(project)), "sha256": digest(original)})
    assert status(project)["artifact_integrity"]
    (previous / "preview.png").write_bytes(b"tampered copy")
    assert status(project)["artifact_integrity"] is False
