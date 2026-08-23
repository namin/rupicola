from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any

from . import __version__
from .diagnose import diagnose
from .model import ResidualDelta, ValidationCheck, ValidationReport
from .patches import PatchError, ParsedPatch, apply_unified_diff, parse_unified_diff
from .policy import EXTENSION_ROOT, scope_violations, source_policy_violations
from .project import Project, ProjectError
from .rocqide import CoqIdeDriver, RocqIdeError
from .runs import RunDirectory, RunStore, RunStoreError, default_runs_root
from .source import SourcePlanError, build_replay_plan, canonical_phrase
from .workspace import CandidateWorkspace, CandidateWorkspaceError


_THEOREM_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*"
)
_MAX_PATCH_BYTES = 1_048_576
_MAX_PATCH_FILES = 16


def solve_with_patch(
    file: Path,
    theorem: str,
    candidate_patch: Path,
    *,
    scope: str = "local",
    through_line: int | None = None,
    project_root: Path | None = None,
    runs_root: Path | None = None,
    timeout_seconds: float = 120.0,
    rationale: str | None = None,
) -> tuple[dict[str, Any], int]:
    started_at = datetime.now(timezone.utc)
    target = file.expanduser().resolve()
    if _THEOREM_RE.fullmatch(theorem) is None:
        return _solve_error(f"invalid theorem identifier: {theorem!r}"), 2
    if scope not in {"local", "project"}:
        return _solve_error(f"unsupported augmentation scope: {scope!r}"), 2
    try:
        project = Project.discover(target, explicit_root=project_root)
        target_relative = target.relative_to(project.root).as_posix()
    except (ProjectError, ValueError) as error:
        return _solve_error(str(error)), 2
    if not target.is_file():
        return _solve_error(f"target source file does not exist: {target}"), 2
    try:
        patch_bytes = candidate_patch.expanduser().read_bytes()
        patch_text = patch_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return _solve_error(f"could not read candidate patch: {error}"), 2
    if len(patch_bytes) > _MAX_PATCH_BYTES:
        return _solve_error(
            f"candidate patch is {len(patch_bytes)} bytes; limit is {_MAX_PATCH_BYTES}"
        ), 2

    store = RunStore(
        runs_root if runs_root is not None else default_runs_root(project.root)
    )
    try:
        run = store.create(theorem)
    except RunStoreError as error:
        return _solve_error(str(error)), 2

    base_worktree_fingerprint = _worktree_fingerprint(project.root)
    project_metadata = project.metadata()
    patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
    run_record: dict[str, Any] = {
        "schema_version": "0.1",
        "run_id": run.run_id,
        "status": "created",
        "created_at": started_at.isoformat(),
        "finished_at": None,
        "tool": {"name": "rupicola-llm", "version": __version__},
        "policy_version": "0.1",
        "project": project_metadata,
        "target": {
            "file": target_relative,
            "theorem": theorem,
            "line": through_line,
            "source_sha256": _file_sha256(target),
        },
        "proposal": {
            "kind": "deterministic_patch",
            "sha256": patch_sha256,
            "scope": scope,
            "rationale": rationale,
            "files": [],
        },
        "model": {"invoked": False, "provider": None},
        "permissions": {
            "target": target_relative,
            "extension_root": EXTENSION_ROOT.as_posix() if scope == "project" else None,
        },
        "limits": {
            "checker_seconds": timeout_seconds,
            "patch_bytes": _MAX_PATCH_BYTES,
            "patch_files": _MAX_PATCH_FILES,
        },
        "base_worktree_fingerprint": base_worktree_fingerprint,
    }
    run.write_json("run.json", run_record)
    run.write_text("proposal.patch", patch_text)

    checks: list[ValidationCheck] = []
    final_snapshot: dict[str, Any] | None = None
    parsed_patch: ParsedPatch | None = None
    initial_exit_override: int | None = None

    initial, diagnostic_exit = diagnose(
        target,
        theorem,
        through_line=through_line,
        project_root=project.root,
        timeout_seconds=timeout_seconds,
    )
    run.write_json("obligations.initial.json", initial)
    if diagnostic_exit != 0 or initial.get("snapshot") is None:
        initial_exit_override = diagnostic_exit or 3
        checks.append(
            ValidationCheck(
                "initial_diagnosis",
                "failed",
                "the target proof could not be diagnosed",
                {"diagnostics": initial.get("diagnostics", [])},
            )
        )
    else:
        checks.append(
            ValidationCheck(
                "initial_diagnosis",
                "passed",
                f"captured {initial['snapshot']['actionable_goal_count']} actionable residuals",
            )
        )
        run_record["status"] = "diagnosed"
        run.write_json("run.json", run_record)

    initial_opening: dict[str, Any] | None = None
    if _passed(checks, "initial_diagnosis"):
        try:
            initial_opening = _opening_snapshot(
                project, target, theorem, timeout_seconds=timeout_seconds
            )
        except (OSError, SourcePlanError, RocqIdeError) as error:
            checks.append(
                ValidationCheck(
                    "frozen_target", "failed", f"could not capture target obligation: {error}"
                )
            )

    if _passed(checks, "initial_diagnosis"):
        try:
            parsed_patch = parse_unified_diff(patch_text)
            if len(parsed_patch.files) > _MAX_PATCH_FILES:
                raise PatchError(
                    f"candidate touches {len(parsed_patch.files)} files; "
                    f"limit is {_MAX_PATCH_FILES}"
                )
            run_record["proposal"]["files"] = list(parsed_patch.paths)
            violations = scope_violations(parsed_patch, target_relative, scope)
            if violations:
                checks.append(
                    ValidationCheck(
                        "scope_policy",
                        "failed",
                        "candidate patch exceeds its writable scope",
                        {"violations": violations},
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        "scope_policy",
                        "passed",
                        f"all {len(parsed_patch.files)} changed files are within {scope} scope",
                        {"files": list(parsed_patch.paths)},
                    )
                )
                run_record["status"] = "checking"
                run.write_json("run.json", run_record)
        except PatchError as error:
            checks.append(
                ValidationCheck("scope_policy", "failed", f"invalid candidate patch: {error}")
            )

    if parsed_patch is not None and _passed(checks, "scope_policy"):
        try:
            with CandidateWorkspace(project, target, run.path) as workspace:
                candidate_project = workspace.candidate_project
                assert candidate_project is not None
                try:
                    apply_unified_diff(parsed_patch, workspace.root)
                except PatchError as error:
                    checks.append(
                        ValidationCheck(
                            "patch_application", "failed", f"candidate did not apply: {error}"
                        )
                    )
                else:
                    checks.append(
                        ValidationCheck(
                            "patch_application",
                            "passed",
                            "candidate patch applied only inside the isolated workspace",
                        )
                    )

                if _passed(checks, "patch_application"):
                    violations = source_policy_violations(
                        project.root, workspace.root, parsed_patch.paths, scope
                    )
                    if violations:
                        checks.append(
                            ValidationCheck(
                                "source_policy",
                                "failed",
                                "candidate introduces disallowed Rocq source",
                                {"violations": violations},
                            )
                        )
                    else:
                        checks.append(
                            ValidationCheck(
                                "source_policy",
                                "passed",
                                "candidate introduces no configured proof escape hatch",
                            )
                        )

                if _passed(checks, "source_policy"):
                    try:
                        source_integrity = _target_source_integrity(
                            target, workspace.candidate_target, theorem
                        )
                    except (OSError, SourcePlanError) as error:
                        checks.append(
                            ValidationCheck(
                                "frozen_target",
                                "failed",
                                f"candidate target structure could not be checked: {error}",
                            )
                        )
                    else:
                        if source_integrity is not None:
                            checks.append(
                                ValidationCheck(
                                    "frozen_target",
                                    "failed",
                                    source_integrity,
                                )
                            )

                dependency_results: list[dict[str, Any]] = []
                if _passed(checks, "source_policy") and not any(
                    check.name == "frozen_target" and check.status == "failed"
                    for check in checks
                ):
                    dependency_results = _compile_candidate(
                        candidate_project,
                        workspace.root,
                        workspace.candidate_target,
                        parsed_patch,
                        run,
                        timeout_seconds,
                        stage="dependencies",
                    )
                    failed_dependency = next(
                        (
                            result
                            for result in dependency_results
                            if result["status"] != "passed"
                        ),
                        None,
                    )
                    if failed_dependency is not None:
                        checks.append(
                            ValidationCheck(
                                "candidate_compile",
                                "failed",
                                f"candidate dependency compilation failed for "
                                f"{failed_dependency['source']}",
                                {"commands": dependency_results},
                            )
                        )

                if (
                    _passed(checks, "source_policy")
                    and not any(
                        check.name == "frozen_target" and check.status == "failed"
                        for check in checks
                    )
                    and not any(
                        check.name == "candidate_compile" and check.status == "failed"
                        for check in checks
                    )
                    and initial_opening is not None
                ):
                    try:
                        candidate_opening = _opening_snapshot(
                            candidate_project,
                            workspace.candidate_target,
                            theorem,
                            timeout_seconds=timeout_seconds,
                        )
                    except (OSError, SourcePlanError, RocqIdeError) as error:
                        checks.append(
                            ValidationCheck(
                                "frozen_target",
                                "failed",
                                f"candidate target obligation could not be captured: {error}",
                            )
                        )
                    else:
                        if candidate_opening["fingerprint"] != initial_opening["fingerprint"]:
                            checks.append(
                                ValidationCheck(
                                    "frozen_target",
                                    "failed",
                                    "candidate changed the elaborated target obligation",
                                    {
                                        "initial": initial_opening["fingerprint"],
                                        "candidate": candidate_opening["fingerprint"],
                                    },
                                )
                            )
                        else:
                            checks.append(
                                ValidationCheck(
                                    "frozen_target",
                                    "passed",
                                    "the elaborated target obligation is unchanged",
                                    {"fingerprint": initial_opening["fingerprint"]},
                                )
                            )

                if _passed(checks, "frozen_target"):
                    target_results = _compile_candidate(
                        candidate_project,
                        workspace.root,
                        workspace.candidate_target,
                        parsed_patch,
                        run,
                        timeout_seconds,
                        stage="target",
                    )
                    compile_results = dependency_results + target_results
                    failed_compile = next(
                        (result for result in compile_results if result["status"] != "passed"),
                        None,
                    )
                    if failed_compile is None:
                        checks.append(
                            ValidationCheck(
                                "candidate_compile",
                                "passed",
                                f"compiled {len(compile_results)} changed Rocq modules",
                                {"commands": compile_results},
                            )
                        )
                    else:
                        checks.append(
                            ValidationCheck(
                                "candidate_compile",
                                "failed",
                                f"candidate compilation failed for {failed_compile['source']}",
                                {"commands": compile_results},
                            )
                        )

                if _passed(checks, "candidate_compile"):
                    final, final_exit = diagnose(
                        workspace.candidate_target,
                        theorem,
                        project_root=workspace.root,
                        timeout_seconds=timeout_seconds,
                    )
                    run.write_json("obligations.final.json", final)
                    if final_exit == 0 and final.get("snapshot") is not None:
                        final_snapshot = final["snapshot"]
                    if (
                        final_snapshot is not None
                        and final_snapshot["goal_count"] == 0
                        and final_snapshot["actionable_goal_count"] == 0
                    ):
                        checks.append(
                            ValidationCheck(
                                "residual_closure",
                                "passed",
                                "candidate closes every focused and auxiliary goal",
                                {"fingerprint": final_snapshot["fingerprint"]},
                            )
                        )
                    else:
                        checks.append(
                            ValidationCheck(
                                "residual_closure",
                                "failed",
                                "candidate leaves residual goals or could not be replayed",
                                {
                                    "diagnostics": final.get("diagnostics", []),
                                    "snapshot": final_snapshot,
                                },
                            )
                        )

                if _passed(checks, "residual_closure"):
                    modules = [
                        candidate_project.logical_name(
                            workspace.root.joinpath(*Path(path).parts)
                        )
                        for path in parsed_patch.paths
                        if path.endswith(".v")
                    ]
                    kernel = _run_command(
                        candidate_project.check_args(modules),
                        workspace.root,
                        timeout_seconds,
                        run,
                        "kernel-check.log",
                    )
                    if kernel["status"] == "passed":
                        checks.append(
                            ValidationCheck(
                                "kernel_check",
                                "passed",
                                "rocq check accepted every changed module",
                                {"modules": modules, "command": kernel},
                            )
                        )
                    else:
                        checks.append(
                            ValidationCheck(
                                "kernel_check",
                                "failed",
                                "rocq check rejected a changed module",
                                {"modules": modules, "command": kernel},
                            )
                        )

                if _passed(checks, "kernel_check"):
                    assumptions = _check_assumptions(
                        candidate_project,
                        workspace.root,
                        workspace.candidate_target,
                        theorem,
                        run,
                        timeout_seconds,
                    )
                    checks.append(assumptions)
        except (CandidateWorkspaceError, OSError, ProjectError) as error:
            checks.append(
                ValidationCheck(
                    "candidate_workspace",
                    "failed",
                    f"could not create or use the isolated workspace: {error}",
                )
            )

    final_worktree_fingerprint = _worktree_fingerprint(project.root)
    if (
        base_worktree_fingerprint is not None
        and final_worktree_fingerprint == base_worktree_fingerprint
    ):
        checks.append(
            ValidationCheck(
                "source_tree_unchanged",
                "passed",
                "the user's tracked and untracked non-ignored files are unchanged",
                {"fingerprint": final_worktree_fingerprint},
            )
        )
    else:
        checks.append(
            ValidationCheck(
                "source_tree_unchanged",
                "failed" if base_worktree_fingerprint is not None else "unavailable",
                "the source worktree fingerprint could not be preserved",
                {
                    "initial": base_worktree_fingerprint,
                    "final": final_worktree_fingerprint,
                },
            )
        )

    required = {
        "initial_diagnosis",
        "scope_policy",
        "patch_application",
        "source_policy",
        "frozen_target",
        "candidate_compile",
        "residual_closure",
        "kernel_check",
        "assumptions",
        "source_tree_unchanged",
    }
    present = {check.name for check in checks}
    for name in sorted(required - present):
        checks.append(
            ValidationCheck(name, "skipped", "an earlier validation gate did not pass")
        )

    initial_snapshot = initial.get("snapshot") or {
        "goals": [],
        "actionable_goal_count": 0,
    }
    delta = ResidualDelta.between(initial_snapshot, final_snapshot)
    verified = all(
        next(check for check in checks if check.name == name).status == "passed"
        for name in required
    )
    if verified:
        report_status = "verified"
    elif initial_exit_override == 3:
        report_status = "environment_error"
    elif initial_exit_override == 2:
        report_status = "error"
    else:
        report_status = "rejected"
    report = ValidationReport(report_status, tuple(checks), delta)
    run.write_json("validation.json", report.to_dict())
    run.append_jsonl(
        "attempts.jsonl",
        {
            "attempt": 1,
            "kind": "deterministic_patch",
            "proposal_sha256": patch_sha256,
            "files": list(parsed_patch.paths) if parsed_patch is not None else [],
            "validation_status": report.status,
            "residual_delta": delta.to_dict(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    finished_at = datetime.now(timezone.utc)
    run_record["status"] = report.status
    run_record["finished_at"] = finished_at.isoformat()
    run_record["elapsed_seconds"] = (finished_at - started_at).total_seconds()
    run_record["artifacts"] = {
        "initial_obligations": "obligations.initial.json",
        "final_obligations": "obligations.final.json"
        if (run.path / "obligations.final.json").is_file()
        else None,
        "proposal": "proposal.patch",
        "attempts": "attempts.jsonl",
        "validation": "validation.json",
        "summary": "summary.md",
    }
    run.write_json("run.json", run_record)
    run.write_text("summary.md", _summary_markdown(run_record, report))

    result = {
        "schema_version": "0.1",
        "run_id": run.run_id,
        "status": report.status,
        "run_directory": str(run.path),
        "proposal": str(run.path / "proposal.patch"),
        "validation": report.to_dict(),
    }
    return result, 0 if verified else (initial_exit_override or 4)


def load_run(store: RunStore, run_id: str) -> dict[str, Any]:
    run = store.open(run_id)
    return {
        "run": run.read_json("run.json"),
        "validation": run.read_json("validation.json"),
        "run_directory": str(run.path),
        "proposal": str(run.path / "proposal.patch"),
        "summary": str(run.path / "summary.md"),
    }


def format_solve_human(result: dict[str, Any]) -> str:
    if result.get("status") == "error" and "message" in result:
        return f"rupicola-llm solve: {result['message']}"
    validation = result["validation"]
    delta = validation["residual_delta"]
    lines = [
        f"Run {result['run_id']}",
        f"  status:    {result['status']}",
        f"  residuals: {delta['initial_actionable']} -> "
        f"{delta['final_actionable'] if delta['final_actionable'] is not None else '?'}",
        f"  proposal:  {result['proposal']}",
    ]
    failed = [
        check
        for check in validation["checks"]
        if check["status"] in {"failed", "unavailable"}
    ]
    if failed:
        lines.append(f"  failed:    {failed[0]['name']}: {failed[0]['summary']}")
    elif result["status"] == "verified":
        lines.append("  source tree unchanged; proposal is ready for review")
    return "\n".join(lines)


def format_show_human(result: dict[str, Any]) -> str:
    run = result["run"]
    validation = result["validation"]
    delta = validation["residual_delta"]
    lines = [
        f"Run {run['run_id']}",
        f"  status: {run['status']}",
        f"  target: {run['target']['file']}::{run['target']['theorem']}",
        f"  scope:  {run['proposal']['scope']}",
        f"  goals:  {delta['initial_actionable']} -> "
        f"{delta['final_actionable'] if delta['final_actionable'] is not None else '?'}",
        "  validation:",
    ]
    for check in validation["checks"]:
        lines.append(f"    {check['status']:<11} {check['name']}: {check['summary']}")
    lines.extend(
        (
            f"  patch:   {result['proposal']}",
            f"  summary: {result['summary']}",
        )
    )
    return "\n".join(lines)


def _opening_snapshot(
    project: Project, target: Path, theorem: str, *, timeout_seconds: float
) -> dict[str, Any]:
    source = target.read_text(encoding="utf-8")
    plan = build_replay_plan(str(target), source, theorem)
    phrases = plan.phrases[: plan.proof_index + 1]
    with CoqIdeDriver(project, timeout_seconds=timeout_seconds) as driver:
        snapshot = driver.replay(target, phrases)
    return snapshot.to_dict()


def _target_source_integrity(
    original: Path, candidate: Path, theorem: str
) -> str | None:
    original_source = original.read_text(encoding="utf-8")
    candidate_source = candidate.read_text(encoding="utf-8")
    original_plan = build_replay_plan(str(original), original_source, theorem)
    candidate_plan = build_replay_plan(str(candidate), candidate_source, theorem)

    original_declaration = canonical_phrase(
        original_plan.phrases[original_plan.declaration_index].text
    )
    candidate_declaration = canonical_phrase(
        candidate_plan.phrases[candidate_plan.declaration_index].text
    )
    if original_declaration != candidate_declaration:
        return "candidate changed the selected theorem declaration"

    original_prefix = [
        canonical_phrase(phrase.text)
        for phrase in original_plan.phrases[: original_plan.declaration_index]
    ]
    candidate_prefix = [
        canonical_phrase(phrase.text)
        for phrase in candidate_plan.phrases[: candidate_plan.declaration_index]
    ]
    candidate_index = 0
    for phrase in original_prefix:
        while (
            candidate_index < len(candidate_prefix)
            and candidate_prefix[candidate_index] != phrase
        ):
            candidate_index += 1
        if candidate_index == len(candidate_prefix):
            return "candidate changed or removed source preceding the selected theorem"
        candidate_index += 1
    return None


def _compile_candidate(
    project: Project,
    workspace_root: Path,
    target: Path,
    patch: ParsedPatch,
    run: RunDirectory,
    timeout_seconds: float,
    *,
    stage: str,
) -> list[dict[str, Any]]:
    sources = [
        workspace_root.joinpath(*Path(path).parts)
        for path in patch.paths
        if path.endswith(".v")
    ]
    if stage == "dependencies":
        sources = [source for source in sources if source.resolve() != target.resolve()]
    elif stage == "target":
        sources = [source for source in sources if source.resolve() == target.resolve()]
    else:
        raise ValueError(f"unknown candidate compilation stage: {stage}")
    sources.sort(key=str)
    results: list[dict[str, Any]] = []
    for index, source in enumerate(sources, 1):
        result = _run_command(
            project.compile_args(source),
            workspace_root,
            timeout_seconds,
            run,
            f"compile-{stage}-{index:02d}-{source.stem}.log",
        )
        result["source"] = str(source.relative_to(workspace_root))
        results.append(result)
        if result["status"] != "passed":
            break
    return results


def _check_assumptions(
    project: Project,
    workspace_root: Path,
    target: Path,
    theorem: str,
    run: RunDirectory,
    timeout_seconds: float,
) -> ValidationCheck:
    module = project.logical_name(target)
    probe_directory = workspace_root / ".rupicola-check"
    probe_directory.mkdir()
    probe = probe_directory / "AssumptionsProbe.v"
    probe.write_text(
        f"Require Import {module}.\nPrint Assumptions {theorem}.\n",
        encoding="utf-8",
    )
    result = _run_command(
        project.compile_args(probe),
        workspace_root,
        timeout_seconds,
        run,
        "assumptions.log",
    )
    output = result.get("output", "")
    if result["status"] != "passed":
        return ValidationCheck(
            "assumptions",
            "failed",
            "Print Assumptions probe did not compile",
            {"command": result},
        )
    if "Closed under the global context" in output:
        return ValidationCheck(
            "assumptions",
            "passed",
            "required theorem is closed under the global context",
            {"module": module, "theorem": theorem, "command": result},
        )
    return ValidationCheck(
        "assumptions",
        "failed",
        "required theorem reports assumptions outside the empty allowlist",
        {"module": module, "theorem": theorem, "command": result},
    )


def _run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: float,
    run: RunDirectory,
    log_name: str,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        output = str(error)
        result = {
            "status": "failed",
            "exit_code": None,
            "timed_out": False,
            "elapsed_seconds": time.monotonic() - started,
            "command": command,
            "log": f"logs/{log_name}",
            "output": output,
        }
        run.write_text(f"logs/{log_name}", output + "\n")
        return result
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        output, _ = process.communicate()
    elapsed = time.monotonic() - started
    output = output or ""
    if len(output) > 2_000_000:
        output = output[:2_000_000] + "\n[output truncated]\n"
    run.write_text(
        f"logs/{log_name}",
        json.dumps({"command": command, "cwd": str(cwd)}, ensure_ascii=False) + "\n" + output,
    )
    return {
        "status": "passed" if process.returncode == 0 and not timed_out else "failed",
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "command": command,
        "log": f"logs/{log_name}",
        "output": output,
    }


def _worktree_fingerprint(root: Path) -> str | None:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).stdout
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    digest = hashlib.sha256()
    digest.update(status)
    for encoded in listed.split(b"\x00"):
        if not encoded:
            continue
        relative = os.fsdecode(encoded)
        path = root / relative
        digest.update(encoded)
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b"F")
            digest.update(str(path.stat().st_mode & 0o777).encode("ascii"))
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"D")
    return digest.hexdigest()


def _passed(checks: list[ValidationCheck], name: str) -> bool:
    return any(check.name == name and check.status == "passed" for check in checks)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary_markdown(run: dict[str, Any], report: ValidationReport) -> str:
    delta = report.residual_delta
    lines = [
        f"# Rupicola LLM run `{run['run_id']}`",
        "",
        f"Status: **{report.status}**",
        "",
        f"Target: `{run['target']['file']}::{run['target']['theorem']}`",
        "",
        f"Residuals: {delta.initial_actionable} -> "
        f"{delta.final_actionable if delta.final_actionable is not None else '?'}",
        "",
        "## Validation",
        "",
    ]
    for check in report.checks:
        lines.append(f"- `{check.status}` **{check.name}** — {check.summary}")
    lines.extend(("", "The proposal remains unapplied in `proposal.patch`.", ""))
    return "\n".join(lines)


def _solve_error(message: str) -> dict[str, Any]:
    return {"schema_version": "0.1", "status": "error", "message": message}
