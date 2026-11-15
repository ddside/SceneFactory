"""Environment contract and optional real Blender integration (no bpy mocks)."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_application_environment():
    assert sys.version_info[:2] == (3, 12)
    assert sys.prefix != sys.base_prefix
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["project"]["requires-python"] == ">=3.12,<3.13"
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    ast.parse((ROOT / "scripts/blender_probe.py").read_text(), feature_version=(3, 11))


@pytest.mark.skipif(sys.platform != "darwin", reason="Phase 0 Metal probe is macOS-specific")
def test_real_blender():
    executable = os.environ.get("BLENDER_EXECUTABLE")
    if not executable:
        pytest.skip("Set BLENDER_EXECUTABLE to run real Blender integration")
    # Never overwrite any previous probe run.
    output = Path(tempfile.mkdtemp(prefix="environment-python312-", dir=ROOT / "artifacts"))
    print(f"Blender probe output: {output}")
    env = os.environ.copy()
    env["SF_PROBE_OUTPUT"] = str(output)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    with (output / "blender.log").open("w") as log:
        result = subprocess.run(
            [executable, "--background", "--factory-startup", "--python-exit-code", "1",
             "--python", str(ROOT / "scripts/blender_probe.py")],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300,
        )
    assert result.returncode == 0, f"See {output / 'blender.log'}"
    report = json.loads((output / "report.json").read_text())
    assert report["python"].startswith("3.11.")
    assert report["blender"].startswith("4.5.")
    assert set(report["tests"]) == {
        "usd_export_and_stage_read", "cycles_cpu", "eevee", "cycles_metal"}
    assert all(t["status"] == "passed" for t in report["tests"].values())
