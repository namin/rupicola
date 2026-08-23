from __future__ import annotations

from pathlib import Path
import shutil

from .project import LoadPath, Project


class CandidateWorkspaceError(RuntimeError):
    pass


class CandidateWorkspace:
    """A source-and-artifact copy with no writable link back to the project."""

    def __init__(self, project: Project, target: Path, parent: Path) -> None:
        self.project = project
        self.target = target.resolve()
        self.root = parent.resolve() / "workspace"
        self.target_load_path = _target_load_path(project, self.target)
        self.candidate_target = self.root / self.target.relative_to(project.root)
        self.candidate_project: Project | None = None

    def __enter__(self) -> "CandidateWorkspace":
        if self.root.exists():
            raise CandidateWorkspaceError(f"candidate workspace already exists: {self.root}")
        self.root.mkdir(parents=True)
        try:
            shutil.copy2(self.project.project_file, self.root / "_CoqProject")
            source_relative = self.target_load_path.physical.relative_to(self.project.root)
            source_destination = self.root / source_relative
            source_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.target_load_path.physical,
                source_destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", ".rupicola"),
            )

            if not self.candidate_target.is_file():
                raise CandidateWorkspaceError(
                    f"copied workspace does not contain target {self.candidate_target}"
                )
            self.candidate_project = Project.discover(
                self.candidate_target, explicit_root=self.root
            )
        except ValueError as error:
            shutil.rmtree(self.root)
            raise CandidateWorkspaceError(
                "the target Rocq load path is outside the project root"
            ) from error
        except BaseException:
            shutil.rmtree(self.root)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.root.is_dir():
            shutil.rmtree(self.root)


def _target_load_path(project: Project, target: Path) -> LoadPath:
    matches: list[LoadPath] = []
    for load_path in project.load_paths:
        try:
            target.relative_to(load_path.physical)
        except ValueError:
            continue
        matches.append(load_path)
    if not matches:
        raise CandidateWorkspaceError(
            f"target {target} is not covered by a Rocq load path in {project.project_file}"
        )
    return max(matches, key=lambda load_path: len(load_path.physical.parts))
