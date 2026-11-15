"""Bounded subprocess runner. Never changes sandbox or Blender installation."""
from pathlib import Path
import os
import re
import subprocess
import time

from .platforms import clean_blender_environment, crash_hint
from .spec import read_json
from .storage import write_json

WORKER = Path(__file__).parent / "blender" / "worker.py"


class RunnerError(RuntimeError):
    pass


def check_result(result, action):
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RunnerError(f"Blender result failed: {result}")
    if action not in ("build", "validate", "preview", "doctor"):
        return
    if result.get("action") != action or not isinstance(result.get("blender"), str):
        raise RunnerError("Blender result missing action/version metadata")
    if action == "doctor":
        if not isinstance(result.get("render_probes"), list) or not isinstance(result.get("devices"), list):
            raise RunnerError("Blender doctor result missing probes/devices")
        return
    fingerprint = result.get("structure_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RunnerError("Blender result missing/invalid structure fingerprint")
    if type(result.get("object_count")) is not int or not isinstance(result.get("objects"), list):
        raise RunnerError("Blender result missing geometry inventory")
    if action == "validate" and result.get("reopened") is not True:
        raise RunnerError("Blender validation did not confirm file reopening")
    if action == "preview" and not isinstance(result.get("render"), dict):
        raise RunnerError("Blender preview missing device selection")


def run_blender(executable, request, directory, timeout=120, worker=WORKER):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / "request.json"
    result_path = directory / "result.json"
    if result_path.exists():
        raise RunnerError(f"Refusing to reuse result directory: {directory}")
    write_json(request_path, request)
    command = [str(executable), "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", str(worker), "--", str(request_path), str(result_path)]
    record = {"command": command, "timeout_seconds": timeout}
    start = time.monotonic()
    try:
        with (directory / "blender.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, shell=False, stdout=log, stderr=subprocess.STDOUT,
                                     timeout=timeout, env=clean_blender_environment(os.environ))
        record["returncode"] = process.returncode
        if process.returncode != 0:
            detail = ""
            if result_path.is_file():
                try:
                    failed = read_json(result_path)
                    if isinstance(failed, dict) and failed.get("error"):
                        detail = f" Worker error: {failed['error']}."
                except ValueError:
                    pass
            raise RunnerError(f"Blender exited {process.returncode}.{detail} "
                              f"{crash_hint(process.returncode)} Log: {directory / 'blender.log'}")
        result = read_json(result_path)
        check_result(result, request.get("action"))
        return result
    except subprocess.TimeoutExpired as exc:
        record["timed_out"] = True
        record["error"] = str(exc)
        raise RunnerError(f"Blender timed out after {timeout}s; see {directory / 'blender.log'}") from exc
    except (OSError, ValueError) as exc:
        record["error"] = str(exc)
        raise RunnerError(f"Blender execution/result error: {exc}") from exc
    except RunnerError as exc:
        record["error"] = str(exc)
        raise
    finally:
        record["elapsed_seconds"] = time.monotonic() - start
        write_json(directory / "execution.json", record)
