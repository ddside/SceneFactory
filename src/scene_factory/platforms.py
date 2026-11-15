"""All OS-specific discovery candidates live here. No installation side effects."""
from pathlib import Path
import platform


def host_info():
    return {"os": platform.system(), "os_release": platform.release(),
            "architecture": platform.machine(), "application_python": platform.python_version()}


def blender_candidates(system=None, home=None):
    system = system or platform.system()
    home = Path(home) if home is not None else Path.home()
    if system == "Darwin":
        return [Path("/Applications/Blender.app/Contents/MacOS/Blender"),
                home / "Applications/Blender.app/Contents/MacOS/Blender"]
    if system == "Linux":
        return [Path("/usr/bin/blender"), Path("/usr/local/bin/blender"),
                Path("/opt/blender/blender")]
    return []


def clean_blender_environment(environ):
    env = dict(environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    return env


def crash_hint(returncode):
    if returncode in (-11, 139):
        return ("Blender segmentation fault. On macOS Phase 0, sandboxed Metal discovery "
                "failed similarly. Inspect blender.log; sandbox causality is not proven. "
                "An approved execution environment may be required; restrictions were not changed.")
    return "Inspect blender.log for Blender errors or crash diagnostics."
