"""Platform-independent source contracts; not an Ubuntu runtime certification."""
import ast
import subprocess
import sys
from pathlib import Path

from scene_factory.cli import parser
from scene_factory.spec import example_spec, validate_spec

ROOT = Path(__file__).resolve().parents[1]


def test_blender_source_is_python311_compatible():
    files = list((ROOT / "src/scene_factory/blender").glob("*.py"))
    files.append(ROOT / "src/scene_factory/spec.py")
    for path in files:
        ast.parse(path.read_text(), feature_version=(3, 11))


def test_no_bpy_in_application_imports():
    result = subprocess.run([sys.executable, "-c",
                             'import sys; import scene_factory.cli; assert "bpy" not in sys.modules'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_os_paths_are_isolated_and_ubuntu_style_arguments():
    for path in (ROOT / "src/scene_factory").glob("*.py"):
        if path.name != "platforms.py":
            assert "/Applications/" not in path.read_text()
            assert "/usr/bin/" not in path.read_text()
            assert "/opt/homebrew/" not in path.read_text()
    args = parser().parse_args(["build", "/home/user/projects/example", "--blender-path", "/opt/blender/blender"])
    assert args.project == "/home/user/projects/example"
    assert args.blender_path == "/opt/blender/blender"
    assert validate_spec(example_spec()) == example_spec()
