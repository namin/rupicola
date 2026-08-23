from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import uuid


class RunStoreError(RuntimeError):
    pass


_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def create(self, theorem: str) -> "RunDirectory":
        self.root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", theorem).strip("-").lower() or "proof"
        for _ in range(10):
            run_id = f"{timestamp}-{slug[:48]}-{uuid.uuid4().hex[:8]}"
            path = self.root / run_id
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                continue
            (path / "logs").mkdir()
            return RunDirectory(run_id, path)
        raise RunStoreError("could not allocate a unique run ID")

    def open(self, run_id: str) -> "RunDirectory":
        if _RUN_ID_RE.fullmatch(run_id) is None:
            raise RunStoreError(f"invalid run ID: {run_id!r}")
        path = self.root / run_id
        if not path.is_dir():
            raise RunStoreError(f"run not found: {run_id}")
        return RunDirectory(run_id, path)


class RunDirectory:
    def __init__(self, run_id: str, path: Path) -> None:
        self.run_id = run_id
        self.path = path.resolve()

    def write_json(self, name: str, value: Any) -> Path:
        _validate_artifact_name(name)
        data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return self.write_text(name, data)

    def read_json(self, name: str) -> Any:
        _validate_artifact_name(name)
        try:
            return json.loads((self.path / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RunStoreError(f"could not read {name} for run {self.run_id}: {error}") from error

    def write_text(self, name: str, value: str) -> Path:
        _validate_artifact_name(name)
        destination = self.path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(value)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    def append_jsonl(self, name: str, value: Any) -> Path:
        _validate_artifact_name(name)
        destination = self.path / name
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return destination

    def sha256(self, name: str) -> str:
        _validate_artifact_name(name)
        return hashlib.sha256((self.path / name).read_bytes()).hexdigest()


def default_runs_root(project_root: Path) -> Path:
    return project_root / ".rupicola" / "llm" / "runs"


def _validate_artifact_name(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RunStoreError(f"unsafe run artifact path: {name!r}")
