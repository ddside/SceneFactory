"""Atomic metadata, artifact integrity and exclusive project mutation."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def check_artifacts(directory, hashes):
    for name, expected in hashes.items():
        path = Path(directory) / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing/empty artifact: {path}")
        if digest(path) != expected:
            raise ValueError(f"Artifact hash mismatch: {path}")


@contextmanager
def project_lock(project):
    path = Path(project) / ".scene-factory.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"Project locked: {path}. Check running processes before removing a stale lock.") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink()
