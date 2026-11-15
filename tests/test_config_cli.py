from pathlib import Path

import pytest

from scene_factory.cli import main, parser
from scene_factory.config import ConfigError, DEFAULTS, load_config, resolve_blender
from scene_factory.platforms import blender_candidates, clean_blender_environment, host_info


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder for discovery tests")
    path.chmod(0o755)
    return path


def test_cli_options_before_and_after_command():
    args = parser().parse_args(["--device", "cpu", "build", "/tmp/example", "--timeout", "5"])
    assert args.project == "/tmp/example" and args.device == "cpu" and args.timeout == 5
    with pytest.raises(SystemExit):
        parser().parse_args(["preview", "example", "--device", "bad"])


def test_init_and_status(tmp_path, capsys):
    project = tmp_path / "example"
    assert main(["init", str(project)]) == 0
    original = (project / "scene.json").read_bytes()
    assert main(["init", str(project)]) == 1
    assert (project / "scene.json").read_bytes() == original
    assert main(["status", str(project)]) == 0
    assert '"last_successful_build": null' in capsys.readouterr().out
    assert main(["build", str(project), "--blender-path", str(tmp_path / "missing")]) == 1


def test_config(tmp_path):
    assert load_config(tmp_path) == DEFAULTS
    path = tmp_path / "scene-factory.toml"
    path.write_text('device="cpu"\ntimeout=30\nblender_path="tools/blender"')
    assert load_config(tmp_path)["timeout"] == 30
    for invalid in ('device="vulkan"', 'timeout=nan', 'resolution=100000', 'samples=true',
                    'unknown=1', 'blender_path=12', 'bad=[', 'timeout=-1'):
        path.write_text(invalid)
        with pytest.raises(ConfigError):
            load_config(tmp_path)


def test_resolution_precedence(tmp_path):
    cli, env, configured, path, candidate = [executable(tmp_path / x) for x in
                                            ("cli", "env", "conf", "path", "standard")]
    kwargs = {"config": {"blender_path": str(configured)}, "project": tmp_path,
              "environ": {"SCENE_FACTORY_BLENDER": str(env)},
              "which": lambda name: str(path), "candidates": [candidate]}
    assert resolve_blender(str(cli), **kwargs) == cli
    assert resolve_blender(**kwargs) == env
    kwargs["environ"] = {}
    assert resolve_blender(**kwargs) == configured
    kwargs["config"] = {}
    assert resolve_blender(**kwargs) == path
    kwargs["which"] = lambda name: None
    assert resolve_blender(**kwargs) == candidate
    kwargs["candidates"] = []
    with pytest.raises(ConfigError, match="SCENE_FACTORY_BLENDER"):
        resolve_blender(**kwargs)


def test_invalid_explicit_does_not_fall_back(tmp_path):
    candidate = executable(tmp_path / "real")
    with pytest.raises(ConfigError, match="unavailable"):
        resolve_blender(str(tmp_path / "missing"), environ={}, which=lambda _: None, candidates=[candidate])
    with pytest.raises(ConfigError, match="nonempty"):
        resolve_blender("", environ={}, candidates=[candidate])


def test_config_relative_path(tmp_path):
    binary = executable(tmp_path / "tools" / "blender")
    assert resolve_blender(config={"blender_path": "tools/blender"}, project=tmp_path,
                           environ={}, which=lambda _: None) == binary


def test_platform_isolation():
    assert all(".app" not in str(p) for p in blender_candidates("Linux", "/home/user"))
    assert Path("/usr/bin/blender") in blender_candidates("Linux")
    assert all(".app" in str(p) for p in blender_candidates("Darwin", "/Users/test"))
    assert blender_candidates("Unknown") == []
    assert host_info()["application_python"].startswith("3.12.")
    assert clean_blender_environment({"PYTHONPATH": "bad", "VIRTUAL_ENV": "bad", "PATH": "keep"}) == {"PATH": "keep"}
