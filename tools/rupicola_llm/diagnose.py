from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from .classify import classify_snapshot
from .model import Diagnostic, normalize_goal_text
from .project import Project, ProjectError
from .retrieve import retrieve_snapshot
from .rocqide import CoqIdeDriver, RocqCommandError, RocqProcessError
from .source import SourcePlanError, build_replay_plan


def diagnose(
    file: Path,
    theorem: str,
    *,
    through_line: int | None = None,
    project_root: Path | None = None,
    timeout_seconds: float = 120.0,
) -> tuple[dict[str, Any], int]:
    started_at = datetime.now(timezone.utc)
    target = file.expanduser().resolve()
    try:
        project = Project.discover(target, explicit_root=project_root)
    except ProjectError as error:
        return _early_error("project_error", str(error), file, theorem, started_at), 2

    try:
        target.relative_to(project.root)
    except ValueError:
        return (
            _error_result(
                project,
                target,
                theorem,
                started_at,
                Diagnostic(
                    "target_outside_project",
                    f"target {target} is outside project root {project.root}",
                ),
            ),
            2,
        )
    if not target.is_file():
        return (
            _error_result(
                project,
                target,
                theorem,
                started_at,
                Diagnostic("target_not_found", f"target source file does not exist: {target}"),
            ),
            2,
        )

    source = target.read_text(encoding="utf-8")
    try:
        plan = build_replay_plan(
            str(target.relative_to(project.root)), source, theorem, through_line
        )
    except SourcePlanError as error:
        return (
            _error_result(
                project,
                target,
                theorem,
                started_at,
                Diagnostic("source_plan_error", str(error)),
                source=source,
            ),
            2,
        )

    try:
        with CoqIdeDriver(project, timeout_seconds=timeout_seconds) as driver:
            snapshot = driver.replay(target, plan.phrases)
    except RocqCommandError as error:
        stale = project.inconsistent_assumptions_diagnostic(error.message)
        diagnostic = stale or Diagnostic(
            kind="rocq_command_error",
            message=error.message,
            details={
                "state_id": error.state_id,
                "location": error.location,
                "source_line": error.phrase.start_line if error.phrase else None,
                "source_phrase": normalize_goal_text(error.phrase.text)
                if error.phrase
                else None,
            },
            suggestion="Correct the reported source or build error, then rerun diagnose.",
        )
        return (
            _error_result(
                project,
                target,
                theorem,
                started_at,
                diagnostic,
                source=source,
                replay=_replay_metadata(plan),
            ),
            3,
        )
    except RocqProcessError as error:
        return (
            _error_result(
                project,
                target,
                theorem,
                started_at,
                Diagnostic(
                    "rocq_driver_error",
                    str(error),
                    suggestion="Check the pinned Rocq/coqidetop installation and retry.",
                ),
                source=source,
                replay=_replay_metadata(plan),
            ),
            3,
        )

    classified = classify_snapshot(snapshot)
    enriched = retrieve_snapshot(project, target, classified)
    finished_at = datetime.now(timezone.utc)
    status = "complete" if not enriched.goals else "residuals"
    return (
        {
            "schema_version": "0.1",
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_seconds": (finished_at - started_at).total_seconds(),
            "project": project.metadata(),
            "target": _target_metadata(project, target, theorem, source),
            "replay": _replay_metadata(plan),
            "snapshot": enriched.to_dict(),
            "diagnostics": [],
        },
        0,
    )


def _target_metadata(
    project: Project, target: Path, theorem: str, source: str | None = None
) -> dict[str, Any]:
    if source is None and target.is_file():
        source = target.read_text(encoding="utf-8")
    return {
        "file": str(target.relative_to(project.root))
        if target.is_relative_to(project.root)
        else str(target),
        "theorem": theorem,
        "source_sha256": hashlib.sha256((source or "").encode("utf-8")).hexdigest()
        if source is not None
        else None,
    }


def _replay_metadata(plan: Any) -> dict[str, Any]:
    stop = plan.stop_phrase
    return {
        "phrase_count": len(plan.phrases),
        "declaration_line": plan.phrases[plan.declaration_index].start_line,
        "proof_line": plan.phrases[plan.proof_index].start_line,
        "stop_line": stop.end_line,
        "stop_phrase": normalize_goal_text(stop.text),
    }


def _error_result(
    project: Project,
    target: Path,
    theorem: str,
    started_at: datetime,
    diagnostic: Diagnostic,
    *,
    source: str | None = None,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    return {
        "schema_version": "0.1",
        "status": "environment_error"
        if diagnostic.kind in {"stale_compiled_artifact", "rocq_driver_error"}
        else "error",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_seconds": (finished_at - started_at).total_seconds(),
        "project": project.metadata(),
        "target": _target_metadata(project, target, theorem, source),
        "replay": replay,
        "snapshot": None,
        "diagnostics": [diagnostic.to_dict()],
    }


def _early_error(
    kind: str, message: str, file: Path, theorem: str, started_at: datetime
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    return {
        "schema_version": "0.1",
        "status": "error",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_seconds": (finished_at - started_at).total_seconds(),
        "project": None,
        "target": {"file": str(file), "theorem": theorem, "source_sha256": None},
        "replay": None,
        "snapshot": None,
        "diagnostics": [Diagnostic(kind, message).to_dict()],
    }


def format_human(result: dict[str, Any]) -> str:
    target = result["target"]
    lines = [f"Rupicola diagnosis: {target['file']}::{target['theorem']}"]
    if result["status"] in {"error", "environment_error"}:
        for diagnostic in result["diagnostics"]:
            lines.append(f"error [{diagnostic['kind']}]: {diagnostic['message']}")
            details = diagnostic.get("details") or {}
            compiled = details.get("compiled_artifact")
            dependency = details.get("dependency_artifact")
            if compiled:
                lines.append(f"  compiled artifact: {compiled['path']}")
            if dependency:
                lines.append(f"  dependency:       {dependency['path']}")
            if diagnostic.get("suggestion"):
                lines.append(f"  next: {diagnostic['suggestion']}")
        return "\n".join(lines)

    snapshot = result["snapshot"]
    count = snapshot["actionable_goal_count"]
    auxiliary = snapshot["auxiliary_goal_count"]
    lines.append(f"{count} residual{'s' if count != 1 else ''} after compile_step saturation")
    if auxiliary:
        suffix = "" if auxiliary == 1 else "es"
        lines.append(
            f"{snapshot['goal_count']} total goals captured "
            f"({auxiliary} auxiliary witness{suffix})"
        )
    for index, goal in enumerate(snapshot["goals"], 1):
        classification = goal["classification"]
        lines.append(
            f"  {index}  {classification['category']:<26} "
            f"{goal['disposition']:<10} {goal['fingerprint'][:12]}"
        )
        lines.append(f"     {normalize_goal_text(goal['conclusion'])}")
        for evidence in goal.get("evidence", ())[:2]:
            lines.append(
                f"     evidence: {evidence['declaration']} "
                f"({evidence['path']}:{evidence['line']})"
            )
    if not snapshot["goal_count"]:
        lines.append("The stock compiler completed this derivation.")
    elif not count:
        lines.append("No independently actionable residuals; auxiliary goals remain.")
    return "\n".join(lines)
