from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Any

from .model import Diagnostic


class ProjectError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadPath:
    flag: str
    physical: Path
    logical: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "physical", self.physical.expanduser().resolve())

    def command_args(self) -> list[str]:
        return [self.flag, str(self.physical), self.logical]

    def resolve_library(self, library: str, suffix: str = ".vo") -> Path | None:
        if library == self.logical:
            remainder: list[str] = []
        elif library.startswith(self.logical + "."):
            remainder = library[len(self.logical) + 1 :].split(".")
        else:
            return None
        return self.physical.joinpath(*remainder).with_suffix(suffix)

    def to_dict(self) -> dict[str, str]:
        return {"flag": self.flag, "physical": str(self.physical), "logical": self.logical}


@dataclass(frozen=True)
class Project:
    root: Path
    project_file: Path
    load_paths: tuple[LoadPath, ...]
    rocq_args: tuple[str, ...]
    coqidetop: str
    rocq: str

    @classmethod
    def discover(cls, start: Path, explicit_root: Path | None = None) -> "Project":
        root = explicit_root.resolve() if explicit_root is not None else _find_root(start)
        project_file = root / "_CoqProject"
        if not project_file.is_file():
            raise ProjectError(f"no _CoqProject found at {project_file}")
        load_paths, rocq_args = _parse_project_file(root, project_file)
        coqidetop = shutil.which("coqidetop")
        rocq = shutil.which("rocq")
        if coqidetop is None:
            raise ProjectError("coqidetop is required for Phase 1 diagnostics")
        if rocq is None:
            raise ProjectError("rocq is not available on PATH")
        return cls(
            root=root,
            project_file=project_file,
            load_paths=tuple(load_paths),
            rocq_args=tuple(rocq_args),
            coqidetop=coqidetop,
            rocq=rocq,
        )

    def coqidetop_args(self) -> list[str]:
        args = [
            self.coqidetop,
            "-q",
            "-quiet",
            "-main-channel",
            "stdfds",
            "--xml_format=Ppcmds",
            "-async-proofs",
            "off",
        ]
        args.extend(self.rocq_args)
        return args

    def compile_args(self, source: Path) -> list[str]:
        return [self.rocq, "compile", "-q", "-quiet", *self.rocq_args, str(source)]

    def check_args(self, modules: list[str]) -> list[str]:
        load_path_args = [
            argument
            for load_path in self.load_paths
            for argument in load_path.command_args()
        ]
        return [self.rocq, "check", "-silent", *load_path_args, *modules]

    def logical_name(self, source: Path) -> str:
        source = source.resolve()
        matches: list[tuple[int, LoadPath, Path]] = []
        for load_path in self.load_paths:
            try:
                relative = source.relative_to(load_path.physical)
            except ValueError:
                continue
            matches.append((len(load_path.physical.parts), load_path, relative))
        if not matches:
            raise ProjectError(f"source {source} is outside every configured Rocq load path")
        _, load_path, relative = max(matches, key=lambda item: item[0])
        if relative.suffix != ".v":
            raise ProjectError(f"Rocq source does not end in .v: {source}")
        components = (load_path.logical, *relative.with_suffix("").parts)
        return ".".join(component for component in components if component)

    def resolve_library(self, library: str, suffix: str = ".vo") -> Path | None:
        candidates: list[Path] = []
        for load_path in self.load_paths:
            path = load_path.resolve_library(library, suffix)
            if path is not None and path.is_file():
                candidates.append(path.resolve())
        if not candidates:
            return None
        return candidates[0]

    def metadata(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "project_file": str(self.project_file),
            "root_commit": _git_output(self.root, ["rev-parse", "HEAD"]),
            "submodules": _submodule_metadata(self.root),
            "rocq_version": _command_first_line([self.rocq, "--version"]),
            "coqidetop": self.coqidetop,
            "load_paths": [load_path.to_dict() for load_path in self.load_paths],
        }

    def inconsistent_assumptions_diagnostic(self, message: str) -> Diagnostic | None:
        collapsed = " ".join(message.split())
        match = re.search(
            r"Compiled library\s+([A-Za-z0-9_.']+).*?makes inconsistent "
            r"assumptions over library\s+([A-Za-z0-9_.']+)",
            collapsed,
        )
        if match is None:
            return None
        compiled_library, dependency_library = match.groups()
        compiled_path = self.resolve_library(compiled_library)
        dependency_path = self.resolve_library(dependency_library)
        details: dict[str, Any] = {
            "compiled_library": compiled_library,
            "dependency_library": dependency_library,
            "compiled_artifact": _artifact_metadata(compiled_path),
            "dependency_artifact": _artifact_metadata(dependency_path),
        }
        if compiled_path is not None and dependency_path is not None:
            details["compiled_artifact_older"] = (
                compiled_path.stat().st_mtime < dependency_path.stat().st_mtime
            )
        return Diagnostic(
            kind="stale_compiled_artifact",
            message=collapsed,
            details=details,
            suggestion=(
                f"Rebuild {compiled_library} and its dependents against the pinned "
                f"{dependency_library} artifact, then rerun diagnose."
            ),
        )


def _find_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "_CoqProject").is_file():
            return candidate
    raise ProjectError(f"could not find _CoqProject above {start}")


def find_project_root(start: Path) -> Path:
    return _find_root(start)


def _parse_project_file(root: Path, project_file: Path) -> tuple[list[LoadPath], list[str]]:
    tokens: list[str] = []
    for raw_line in project_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens.extend(shlex.split(line, comments=True, posix=True))

    load_paths: list[LoadPath] = []
    rocq_args: list[str] = []
    index = 0
    one_arg = {"-I", "-w", "-set", "-unset", "-compat", "-compat-from"}
    while index < len(tokens):
        token = tokens[index]
        if token in {"-Q", "-R"}:
            if index + 2 >= len(tokens):
                raise ProjectError(f"incomplete {token} entry in {project_file}")
            physical = Path(tokens[index + 1])
            if not physical.is_absolute():
                physical = (root / physical).resolve()
            logical = tokens[index + 2]
            load_path = LoadPath(token, physical, logical)
            load_paths.append(load_path)
            rocq_args.extend(load_path.command_args())
            index += 3
            continue
        if token == "-arg":
            if index + 1 >= len(tokens):
                raise ProjectError(f"incomplete -arg entry in {project_file}")
            rocq_args.append(tokens[index + 1])
            index += 2
            continue
        if token in one_arg:
            if index + 1 >= len(tokens):
                raise ProjectError(f"incomplete {token} entry in {project_file}")
            rocq_args.extend((token, tokens[index + 1]))
            index += 2
            continue
        index += 1
    return load_paths, rocq_args


def _git_output(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _submodule_metadata(root: Path) -> dict[str, dict[str, Any]]:
    output = _git_output(root, ["submodule", "status", "--recursive"])
    if not output:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        match = re.match(r"(?P<state>[-+ U])(?P<sha>[0-9a-f]+)\s+(?P<path>\S+)", line)
        if match is None:
            continue
        result[match.group("path")] = {
            "sha": match.group("sha"),
            "state": match.group("state"),
        }
    return result


def _command_first_line(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.splitlines()[0] if result.stdout else None


def _artifact_metadata(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }
