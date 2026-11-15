import subprocess

import pytest

from scene_factory.runner import RunnerError, check_result, run_blender
from scene_factory.spec import read_json
from scene_factory.storage import check_artifacts, digest, project_lock, write_json


@pytest.mark.parametrize("mode", ["crash", "exception", "timeout", "missing", "malformed", "false"])
def test_runner_failures(tmp_path, monkeypatch, mode):
    # Unit-level fault injection only; real bpy tests are in test_integration.py.
    def fake_run(command, **kwargs):
        assert isinstance(command, list) and kwargs["shell"] is False
        assert "--background" in command and "--python-exit-code" in command
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, .01)
        if mode == "crash":
            return subprocess.CompletedProcess(command, -11)
        if mode == "exception":
            return subprocess.CompletedProcess(command, 1)
        if mode == "malformed":
            (tmp_path / "result.json").write_text("bad json")
        if mode == "false":
            write_json(tmp_path / "result.json", {"ok": False})
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RunnerError):
        run_blender("blender", {"action": "test"}, tmp_path, .01)
    record = read_json(tmp_path / "execution.json")
    assert record["elapsed_seconds"] >= 0
    assert record.get("error")
    if mode == "timeout":
        assert record["timed_out"]


def test_storage_hash_and_lock(tmp_path):
    write_json(tmp_path / "result.json", {"ok": True})
    hashes = {"result.json": digest(tmp_path / "result.json")}
    check_artifacts(tmp_path, hashes)
    with project_lock(tmp_path):
        with pytest.raises(ValueError, match="locked"):
            with project_lock(tmp_path):
                pass
    assert not (tmp_path / ".scene-factory.lock").exists()
    (tmp_path / "result.json").write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        check_artifacts(tmp_path, hashes)
    (tmp_path / "result.json").unlink()
    with pytest.raises(ValueError, match="Missing"):
        check_artifacts(tmp_path, hashes)


def test_incomplete_success_result_is_rejected():
    with pytest.raises(RunnerError, match="metadata"):
        check_result({"ok": True}, "build")
    with pytest.raises(RunnerError, match="fingerprint"):
        check_result({"ok": True, "action": "build", "blender": "4.5.15"}, "build")
