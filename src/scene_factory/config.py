"""Project configuration and explicit Blender executable precedence."""
import math
import os
from pathlib import Path
import shutil
import tomllib

from .platforms import blender_candidates


class ConfigError(ValueError):
    pass


DEFAULTS = {"timeout": 120.0, "device": "cpu", "resolution": 256, "samples": 8}
DEVICES = ("auto", "cpu", "metal", "cuda", "optix")


def load_config(project):
    path = Path(project) / "scene-factory.toml"
    config = dict(DEFAULTS)
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        if set(raw) - {"blender_path", *DEFAULTS}:
            raise ConfigError(f"{path}: unknown settings {sorted(set(raw) - {'blender_path', *DEFAULTS})}")
        config.update(raw)
    if "blender_path" in config and (not isinstance(config["blender_path"], str) or not config["blender_path"]):
        raise ConfigError("blender_path: expected nonempty string")
    validate_options(config)
    return config


def validate_options(config):
    timeout = config["timeout"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600 or not math.isfinite(timeout):
        raise ConfigError("timeout: expected finite seconds in (0, 3600]")
    if config["device"] not in DEVICES:
        raise ConfigError(f"device: expected one of {DEVICES}")
    for key, low, high in (("resolution", 32, 1024), ("samples", 1, 64)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ConfigError(f"{key}: expected integer in [{low}, {high}]")


def resolve_blender(cli_path=None, config=None, project=Path("."), environ=None,
                    which=None, candidates=None):
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    config = config or {}
    configured = cli_path if cli_path is not None else (
        environ.get("SCENE_FACTORY_BLENDER") or config.get("blender_path"))
    if configured is not None:
        if not isinstance(configured, str) or not configured.strip():
            raise ConfigError("Blender executable path must be a nonempty string")
        expanded = Path(configured).expanduser()
        # Config-relative paths belong to the project; CLI/env paths belong to cwd.
        if not cli_path and not environ.get("SCENE_FACTORY_BLENDER") and not expanded.is_absolute():
            expanded = Path(project) / expanded
        found = expanded if expanded.is_file() else which(str(expanded))
        if found and Path(found).is_file() and os.access(found, os.X_OK):
            return Path(found).resolve()
        raise ConfigError(f"Blender executable unavailable: {configured}. Set --blender-path, "
                          "SCENE_FACTORY_BLENDER, or blender_path in scene-factory.toml.")
    found = which("blender")
    options = ([Path(found)] if found else []) + list(
        blender_candidates() if candidates is None else candidates)
    for path in options:
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    raise ConfigError("Blender not found. Set --blender-path, SCENE_FACTORY_BLENDER, "
                      "or blender_path in scene-factory.toml; Blender is not installed automatically.")
