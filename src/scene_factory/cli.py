"""Scene Factory command line interface; app Python, no bpy import."""
import argparse
import json
from pathlib import Path
import sys

from .config import load_config, resolve_blender, validate_options, DEVICES
from .platforms import host_info
from .project import init_project, new_id, operate, run_build, status, compile_project
from .runner import run_blender, RunnerError
from .registry import Registry
from .scene_v2 import migrate_file
from .skill_testing import validate_skill


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
    for name in ("doctor", "init", "build", "preview", "validate", "status", "compile"):
        command = commands.add_parser(name)
        command.add_argument("project", nargs="?" if name == "doctor" else None,
                             **({"default": "."} if name == "doctor" else {}))
        common_options(command)
        if name == "init":
            command.add_argument("--schema-version", choices=(1,2), type=int, default=1)
    migration = commands.add_parser("migrate")
    migration.add_argument("source")
    migration.add_argument("destination")
    migration.set_defaults(project=".")
    skills = commands.add_parser("skills")
    skills.set_defaults(project=".")
    actions = skills.add_subparsers(dest="skill_action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--query", default="")
    for name in ("show", "validate"):
        action = actions.add_parser(name)
        action.add_argument("skill_id")
        action.add_argument("--version", default="1.0.0")
        common_options(action)
        if name == "validate":
            action.add_argument("--activate", action="store_true")
            action.add_argument("--test-report")
            action.add_argument("--contract-only", action="store_true")
    for name in ('generate','edit','rebuild','repair','review','history','diff','rollback','resume','present'):
        command=commands.add_parser(name)
        command.add_argument('project'); common_options(command)
        if name in ('generate','edit','repair'): command.add_argument('--proposal',required=True)
        if name=='review': command.add_argument('--file',required=True)
        if name=='rebuild': command.add_argument('--revision')
        if name=='rollback':
            command.add_argument('--revision',required=True); command.add_argument('--reason',default='Return to a previously accepted revision')
        if name=='diff':
            command.add_argument('--from',dest='from_revision',required=True); command.add_argument('--to',dest='to_revision',required=True)
        if name=='resume': command.add_argument('--execute',action='store_true')
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    try:
        if args.command in ('generate','edit','rebuild','repair','review','history','diff','rollback','resume','present'):
            from . import workflow
            from .workflow_store import history,diff_revisions,read_state,load_record
            from .publication import rollback
            from .spec import read_json
            if args.command=='history': result=history(project)
            elif args.command=='diff': result=diff_revisions(project,args.from_revision,args.to_revision)
            elif args.command=='rollback': result=rollback(project,args.revision,args.reason)
            elif args.command=='review': result=workflow.submit_review(project,read_json(args.file))
            elif args.command=='present':
                s=read_state(project)
                if not s['latest_presentation']: raise ValueError('No presentation available')
                result=load_record(project,'presentation',s['latest_presentation'],s)
            elif args.command=='resume' and not args.execute: result=workflow.resume_context(project)
            else:
                options=load_config(project)
                for key in ('timeout','device','resolution','samples'):
                    if hasattr(args,key): options[key]=getattr(args,key)
                validate_options(options)
                executable=resolve_blender(getattr(args,'blender_path',None),options,project)
                if args.command in ('generate','edit'):
                    result=workflow.start(project,read_json(args.proposal),executable,options,args.command=='edit')
                elif args.command=='rebuild': result=workflow.rebuild(project,executable,options,args.revision)
                elif args.command=='repair': result=workflow.repair(project,read_json(args.proposal),executable,options)
                else: result=workflow.resume(project,executable,options,True)
                result=workflow.summary(result)
        elif args.command == "init":
            result = init_project(project, args.schema_version)
        elif args.command == "status":
            result = status(project)
        elif args.command == "compile":
            result = compile_project(project)
        elif args.command == "migrate":
            migrated = migrate_file(args.source, args.destination)
            result = {"destination":str(Path(args.destination).resolve()),"migration":migrated["migration"]}
        elif args.command == "skills":
            registry = Registry()
            if args.skill_action == "list":
                result = {"skills":[{key:m[key] for key in ("skill_id","version","name","description","category","tags","validation_status")}
                                    for m in registry.search(args.query)]}
            else:
                key = (args.skill_id,args.version)
                if key not in registry.manifests:
                    raise ValueError(f"Unknown skill/version: {key}")
                if args.skill_action == "show":
                    result = registry.manifests[key]
                elif args.contract_only:
                    if args.activate:
                        raise ValueError("Contract-only checks cannot activate a skill")
                    result = {"skill_id":args.skill_id,"contract":"passed","activated":False}
                else:
                    options = load_config(project)
                    if hasattr(args,"timeout"):
                        options["timeout"] = args.timeout
                    validate_options(options)
                    executable = resolve_blender(getattr(args,"blender_path",None),options,project)
                    result = validate_skill(args.skill_id,args.version,executable,
                        project / "artifacts" / "skill-validation" / new_id(),
                        options["timeout"],args.activate,args.test_report)
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
