from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


class PatchError(ValueError):
    pass


_HUNK_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?:\s.*)?(?:\n)?$"
)


@dataclass(frozen=True)
class PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[PatchHunk, ...]

    @property
    def path(self) -> str:
        path = self.new_path or self.old_path
        if path is None:
            raise PatchError("patch entry has neither an old nor a new path")
        return path

    @property
    def is_new(self) -> bool:
        return self.old_path is None


@dataclass(frozen=True)
class ParsedPatch:
    files: tuple[FilePatch, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(file_patch.path for file_patch in self.files)


def parse_unified_diff(text: str) -> ParsedPatch:
    lines = text.splitlines(keepends=True)
    file_patches: list[FilePatch] = []
    index = 0

    while index < len(lines):
        while index < len(lines) and not (
            lines[index].startswith("diff --git ") or lines[index].startswith("--- ")
        ):
            if lines[index].strip():
                raise PatchError(f"unexpected patch preamble: {lines[index].rstrip()!r}")
            index += 1
        if index >= len(lines):
            break

        git_paths: tuple[str, str] | None = None
        if lines[index].startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)\n?", lines[index])
            if match is None:
                raise PatchError("quoted or whitespace-containing patch paths are unsupported")
            git_paths = match.groups()
            index += 1
            while index < len(lines) and not lines[index].startswith("--- "):
                metadata = lines[index].rstrip("\n")
                if metadata.startswith("index ") or metadata == "new file mode 100644":
                    index += 1
                    continue
                if metadata.startswith(
                    (
                        "new file mode ",
                        "old mode ",
                        "new mode ",
                        "deleted file mode ",
                        "rename from ",
                        "rename to ",
                        "Binary files ",
                    )
                ):
                    raise PatchError(
                        "mode changes, deletions, renames, and binary patches are unsupported"
                    )
                raise PatchError(f"unsupported patch metadata: {metadata!r}")

        if index + 1 >= len(lines) or not lines[index].startswith("--- "):
            raise PatchError("file patch is missing its --- header")
        old_path = _header_path(lines[index], "--- ")
        index += 1
        if not lines[index].startswith("+++ "):
            raise PatchError("file patch is missing its +++ header")
        new_path = _header_path(lines[index], "+++ ")
        index += 1

        if old_path is None and new_path is None:
            raise PatchError("both patch paths cannot be /dev/null")
        if new_path is None:
            raise PatchError("file deletion is unsupported in the checked solve prototype")
        if old_path is not None and old_path != new_path:
            raise PatchError("file renames are unsupported in the checked solve prototype")
        if git_paths is not None:
            expected_old = old_path or git_paths[0]
            if git_paths != (expected_old, new_path):
                raise PatchError("diff --git paths do not agree with the file headers")

        hunks: list[PatchHunk] = []
        while index < len(lines) and lines[index].startswith("@@"):
            match = _HUNK_RE.match(lines[index])
            if match is None:
                raise PatchError(f"malformed hunk header: {lines[index].rstrip()!r}")
            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count") or "1")
            new_start = int(match.group("new_start"))
            new_count = int(match.group("new_count") or "1")
            index += 1
            hunk_lines: list[str] = []
            consumed_old = 0
            consumed_new = 0
            while consumed_old < old_count or consumed_new < new_count:
                if index >= len(lines):
                    raise PatchError("patch ends inside a hunk")
                line = lines[index]
                if not line or line[0] not in " +-":
                    raise PatchError(f"invalid hunk line: {line.rstrip()!r}")
                marker = line[0]
                if marker in " -":
                    consumed_old += 1
                if marker in " +":
                    consumed_new += 1
                if consumed_old > old_count or consumed_new > new_count:
                    raise PatchError("hunk contains more lines than its header declares")
                hunk_lines.append(line)
                index += 1
            if index < len(lines) and lines[index].startswith("\\ No newline"):
                raise PatchError("patches for files without a final newline are unsupported")
            hunks.append(
                PatchHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(hunk_lines),
                )
            )

        if not hunks:
            raise PatchError(f"patch for {new_path!r} contains no hunks")
        file_patches.append(FilePatch(old_path, new_path, tuple(hunks)))

    if not file_patches:
        raise PatchError("candidate patch is empty")
    paths = [file_patch.path for file_patch in file_patches]
    if len(paths) != len(set(paths)):
        raise PatchError("candidate patch contains the same path more than once")
    return ParsedPatch(tuple(file_patches))


def apply_unified_diff(patch: ParsedPatch, root: Path) -> tuple[Path, ...]:
    root = root.resolve()
    prepared: list[tuple[Path, str, int | None]] = []
    for file_patch in patch.files:
        destination = _safe_destination(root, file_patch.path)
        if file_patch.is_new:
            if destination.exists() or destination.is_symlink():
                raise PatchError(f"new patch path already exists: {file_patch.path}")
            original = ""
            mode = 0o644
        else:
            if not destination.is_file() or destination.is_symlink():
                raise PatchError(f"modified patch path is not a regular file: {file_patch.path}")
            try:
                original = destination.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise PatchError(f"patch target is not UTF-8 text: {file_patch.path}") from error
            mode = stat.S_IMODE(destination.stat().st_mode)
        proposed = _apply_file_hunks(file_patch, original)
        prepared.append((destination, proposed, mode))

    written: list[Path] = []
    for destination, proposed, mode in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(proposed)
            os.chmod(temporary, mode)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        written.append(destination)
    return tuple(written)


def _header_path(line: str, prefix: str) -> str | None:
    raw = line[len(prefix) :].rstrip("\n")
    raw = raw.split("\t", 1)[0]
    if raw == "/dev/null":
        return None
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise PatchError(f"unsafe patch path: {raw!r}")
    if "\\" in raw or "\x00" in raw:
        raise PatchError(f"unsupported patch path: {raw!r}")
    return path.as_posix()


def _safe_destination(root: Path, relative: str) -> Path:
    destination = root.joinpath(*PurePosixPath(relative).parts)
    resolved = destination.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PatchError(f"patch path escapes the candidate workspace: {relative}") from error
    return destination


def _apply_file_hunks(file_patch: FilePatch, original: str) -> str:
    old_lines = original.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    for hunk in file_patch.hunks:
        old_index = hunk.old_start - 1 if hunk.old_start else 0
        if old_index < cursor or old_index > len(old_lines):
            raise PatchError(f"hunk for {file_patch.path} has an invalid or overlapping range")
        result.extend(old_lines[cursor:old_index])
        cursor = old_index
        for line in hunk.lines:
            marker = line[0]
            payload = line[1:]
            if marker in " -":
                if cursor >= len(old_lines) or old_lines[cursor] != payload:
                    actual = old_lines[cursor].rstrip("\n") if cursor < len(old_lines) else "<EOF>"
                    raise PatchError(
                        f"hunk for {file_patch.path} does not apply at old line "
                        f"{cursor + 1}: expected {payload.rstrip()!r}, found {actual!r}"
                    )
                if marker == " ":
                    result.append(payload)
                cursor += 1
            else:
                result.append(payload)
    result.extend(old_lines[cursor:])
    return "".join(result)
