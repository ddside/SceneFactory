"""Scene Factory command line interface; app Python, no bpy import."""
import argparse
import json
from pathlib import Path
import sys

from .config import load_config, resolve_blender, validate_options, DEVICES
from .platforms import host_info
from .project import init_project, new_id, operate, run_build, status
from .runner import run_blender, RunnerError


def common_options(parser):
    parser.add_argument("--blender-path", default=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--device", choices=DEVICES, default=argparse.SUPPRESS)
    parser.add_argument("--resolution", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--samples", type=int, default=argparse.SUPPRESS)


def parser():
    root = argparse.ArgumentParser(prog="scene-factory")
    common_options(root)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("doctor", "init", "build", "preview", "validate", "status"):
        command = commands.add_parser(name)
        command.add_argument("project", nargs="?" if name == "doctor" else None,
                             **({"default": "."} if name == "doctor" else {}))
        common_options(command)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    try:
        if args.command == "init":
            result = init_project(project)
        elif args.command == "status":
            result = status(project)
        else:
            options = load_config(project)
            for key in ("timeout", "device", "resolution", "samples"):
                if hasattr(args, key):
                    options[key] = getattr(args, key)
            validate_options(options)
            executable = resolve_blender(getattr(args, "blender_path", None), options, project)
            if args.command == "doctor":
                directory = project / "artifacts" / "doctor" / new_id()
                result = {**host_info(), "blender_executable": str(executable),
                          "diagnostics_directory": str(directory)}
                try:
                    result.update(run_blender(executable, {"action": "doctor"}, directory, options["timeout"]))
                except RunnerError as exc:
                    print(json.dumps({**result, "ok": False, "startup_error": str(exc)}, indent=2))
                    return 1
            elif args.command == "build":
                result = run_build(project, executable, options)
            else:
                result = operate(project, args.command, executable, options)
        # Full vertex inventories remain in result.json / validation.json.
        summary = {k: v for k, v in result.items() if k != "objects"}
        print(json.dumps(summary, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RunnerError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
