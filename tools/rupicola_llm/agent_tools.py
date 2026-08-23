from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .agent_protocol import InspectObligationAction, ReadAction, SearchAction
from .model import normalize_goal_text


class AgentToolError(RuntimeError):
    pass


class RepositoryTools:
    """Read-only, bounded repository tools exposed to an untrusted provider."""

    def __init__(
        self,
        project_root: Path,
        snapshot: dict[str, Any],
        *,
        readable_roots: tuple[str, ...] = ("src/Rupicola",),
    ) -> None:
        self.project_root = project_root.resolve()
        self.snapshot = snapshot
        self.readable_roots = readable_roots
        self._resolved_roots = tuple(
            self.project_root.joinpath(*PurePosixPath(root).parts).resolve()
            for root in readable_roots
        )

    def search(self, action: SearchAction) -> dict[str, Any]:
        selected = self._resolve(action.path)
        if not selected.exists():
            raise AgentToolError(f"search path does not exist: {action.path}")
        if selected.is_symlink():
            raise AgentToolError(f"search path may not be a symlink: {action.path}")
        if selected.is_file():
            paths = (selected,)
        elif selected.is_dir():
            paths = tuple(sorted(selected.rglob("*.v")))
        else:
            raise AgentToolError(f"search path is not a file or directory: {action.path}")

        needle = action.query.casefold()
        matches: list[dict[str, Any]] = []
        scanned_files = 0
        for path in paths:
            if path.suffix != ".v" or path.is_symlink():
                continue
            self._assert_disclosed(path.resolve())
            scanned_files += 1
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    for line_number, line in enumerate(stream, 1):
                        if needle not in line.casefold():
                            continue
                        matches.append(
                            {
                                "path": path.relative_to(self.project_root).as_posix(),
                                "line": line_number,
                                "text": line.rstrip("\n")[:500],
                            }
                        )
                        if len(matches) >= action.max_results:
                            return {
                                "status": "ok",
                                "query": action.query,
                                "path": action.path,
                                "matches": matches,
                                "match_limit_reached": True,
                                "scanned_files": scanned_files,
                            }
            except OSError as error:
                raise AgentToolError(f"could not search {path}: {error}") from error
        return {
            "status": "ok",
            "query": action.query,
            "path": action.path,
            "matches": matches,
            "match_limit_reached": False,
            "scanned_files": scanned_files,
        }

    def read(self, action: ReadAction) -> dict[str, Any]:
        path = self._resolve(action.path)
        if path.suffix != ".v":
            raise AgentToolError("read permits only .v source files")
        if path.is_symlink() or not path.is_file():
            raise AgentToolError(f"read path is not a regular file: {action.path}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise AgentToolError(f"could not read {action.path}: {error}") from error
        end = action.end_line
        if end is None:
            end = min(len(lines), action.start_line + 79)
        end = min(end, action.start_line + 199, len(lines))
        if action.start_line > len(lines) + 1:
            raise AgentToolError(
                f"start_line {action.start_line} is beyond the {len(lines)}-line file"
            )
        selected = lines[action.start_line - 1 : end]
        content = "\n".join(
            f"{number:>6}  {line}"
            for number, line in enumerate(selected, action.start_line)
        )
        if len(content) > 60_000:
            content = content[:60_000] + "\n[content truncated]"
        return {
            "status": "ok",
            "path": action.path,
            "start_line": action.start_line,
            "end_line": end,
            "total_lines": len(lines),
            "content": content,
        }

    def inspect(self, action: InspectObligationAction) -> dict[str, Any]:
        goals = self.snapshot.get("goals", [])
        goal: dict[str, Any] | None = None
        if action.obligation_id.isdigit():
            index = int(action.obligation_id)
            if 1 <= index <= len(goals):
                goal = goals[index - 1]
        if goal is None:
            goal = next(
                (
                    item
                    for item in goals
                    if item.get("id") == action.obligation_id
                    or item.get("fingerprint") == action.obligation_id
                ),
                None,
            )
        if goal is None:
            raise AgentToolError(
                f"unknown obligation {action.obligation_id!r}; captured {len(goals)} goals"
            )
        result = dict(goal)
        if action.printing_mode == "normalized":
            result["hypotheses"] = [
                normalize_goal_text(value) for value in goal.get("hypotheses", [])
            ]
            result["conclusion"] = normalize_goal_text(goal.get("conclusion", ""))
        return {
            "status": "ok",
            "printing_mode": action.printing_mode,
            "obligation": result,
        }

    def _resolve(self, relative: str) -> Path:
        path = self.project_root.joinpath(*PurePosixPath(relative).parts)
        resolved = path.resolve(strict=False)
        self._assert_disclosed(resolved)
        return path

    def _assert_disclosed(self, resolved: Path) -> None:
        for root in self._resolved_roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return
        roots = ", ".join(self.readable_roots)
        raise AgentToolError(f"path is outside the disclosed read roots: {roots}")
