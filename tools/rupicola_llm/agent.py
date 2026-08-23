from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
import time
from typing import Any, Mapping

from . import __version__
from .agent_protocol import (
    AgentAction,
    AgentProtocolError,
    AgentProvider,
    CheckAction,
    FinishAction,
    InspectObligationAction,
    ProposePatchAction,
    ProviderExhausted,
    ReadAction,
    RevertCandidateAction,
    SearchAction,
    TOOL_SPECS,
    action_record,
)
from .agent_tools import AgentToolError, RepositoryTools
from .diagnose import diagnose
from .patches import PatchError, parse_unified_diff
from .policy import EXTENSION_ROOT, scope_violations
from .project import Project, ProjectError
from .runs import RunDirectory, RunStore, RunStoreError, default_runs_root
from .solve import _file_sha256, _worktree_fingerprint, solve_with_patch


_THEOREM_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*"
)
_MAX_PATCH_BYTES = 1_048_576
_MAX_PATCH_FILES = 16
_READABLE_ROOTS = ("src/Rupicola",)
_AUTO_REVERT_CHECKS = {
    "scope_policy",
    "patch_application",
    "source_policy",
    "frozen_target",
    "candidate_workspace",
    "source_tree_unchanged",
}


@dataclass
class _Candidate:
    number: int
    path: Path
    sha256: str
    byte_count: int
    rationale: str
    files: tuple[str, ...]
    validation: dict[str, Any] | None = None
    child_run_id: str | None = None


def solve_with_agent(
    file: Path,
    theorem: str,
    provider: AgentProvider,
    *,
    scope: str = "local",
    through_line: int | None = None,
    project_root: Path | None = None,
    runs_root: Path | None = None,
    timeout_seconds: float = 120.0,
    max_actions: int = 24,
    max_checks: int = 3,
    max_retrievals: int = 8,
    wall_seconds: float = 900.0,
) -> tuple[dict[str, Any], int]:
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    target = file.expanduser().resolve()
    error = _validate_request(
        theorem,
        scope,
        timeout_seconds,
        max_actions,
        max_checks,
        max_retrievals,
        wall_seconds,
    )
    if error is not None:
        return _agent_error(error), 2
    try:
        project = Project.discover(target, explicit_root=project_root)
        target_relative = target.relative_to(project.root).as_posix()
    except (ProjectError, ValueError) as error_value:
        return _agent_error(str(error_value)), 2
    if not target.is_file():
        return _agent_error(f"target source file does not exist: {target}"), 2

    store = RunStore(
        runs_root if runs_root is not None else default_runs_root(project.root)
    )
    try:
        run = store.create(theorem)
    except RunStoreError as error_value:
        return _agent_error(str(error_value)), 2

    base_fingerprint = _worktree_fingerprint(project.root)
    provider_metadata = provider.metadata.to_dict()
    run_record: dict[str, Any] = {
        "schema_version": "0.1",
        "run_id": run.run_id,
        "kind": "agent_controller",
        "status": "created",
        "created_at": started_at.isoformat(),
        "finished_at": None,
        "tool": {"name": "rupicola-llm", "version": __version__},
        "policy_version": "0.1",
        "project": project.metadata(),
        "target": {
            "file": target_relative,
            "theorem": theorem,
            "line": through_line,
            "source_sha256": _file_sha256(target),
        },
        "proposal": {
            "kind": "agent_patch",
            "sha256": None,
            "scope": scope,
            "rationale": None,
            "files": [],
        },
        "model": {
            "invoked": provider_metadata["model_invoked"],
            "provider": provider_metadata["provider"],
            "model": provider_metadata["model"],
            "remote": provider_metadata["remote"],
            "configuration": provider_metadata.get("configuration", {}),
            "usage": None,
        },
        "permissions": {
            "target": target_relative,
            "extension_root": EXTENSION_ROOT.as_posix()
            if scope == "project"
            else None,
            "readable_roots": list(_READABLE_ROOTS),
        },
        "limits": {
            "actions": max_actions,
            "checks": max_checks,
            "retrievals": max_retrievals,
            "wall_seconds": wall_seconds,
            "checker_seconds": timeout_seconds,
            "patch_bytes": _MAX_PATCH_BYTES,
            "patch_files": _MAX_PATCH_FILES,
        },
        "base_worktree_fingerprint": base_fingerprint,
    }
    run.write_json("run.json", run_record)
    run.write_json("tools.json", [spec.to_dict() for spec in TOOL_SPECS])

    initial, diagnostic_exit = diagnose(
        target,
        theorem,
        through_line=through_line,
        project_root=project.root,
        timeout_seconds=timeout_seconds,
    )
    run.write_json("obligations.initial.json", initial)
    snapshot = initial.get("snapshot")
    if diagnostic_exit != 0 or snapshot is None:
        status = initial.get("status", "error")
        validation = _empty_validation(
            status,
            0,
            "initial diagnosis failed before the provider was invoked",
            check_name="initial_diagnosis",
        )
        return _finalize(
            run,
            run_record,
            status,
            validation,
            None,
            "The target could not be diagnosed.",
            started_at,
            started_monotonic,
            project,
            base_fingerprint,
            actions_used=0,
            checks_used=0,
            exit_code=diagnostic_exit or 3,
        )

    context = {
        "schema_version": "0.1",
        "objective": (
            "Produce a minimal unified diff that closes every residual goal while "
            "preserving the selected theorem statement and project policy."
        ),
        "diagnosis": initial,
        "permissions": run_record["permissions"],
        "limits": run_record["limits"],
        "checker": {
            "isolation": "disposable source copy",
            "fast_mode": "currently executes the stricter final validation pipeline",
            "acceptance": (
                "all goals closed; changed modules compile and pass rocq check; "
                "Print Assumptions is closed; source tree unchanged"
            ),
        },
    }
    run.write_json("context.initial.json", context)
    run_record["status"] = "diagnosed"
    run.write_json("run.json", run_record)

    initial_actionable = snapshot["actionable_goal_count"]
    if snapshot["goal_count"] == 0:
        validation = _empty_validation(
            "stock_complete",
            initial_actionable,
            "the stock compiler already closes the selected derivation",
            final_actionable=0,
            check_status="passed",
            check_name="stock_compile",
        )
        return _finalize(
            run,
            run_record,
            "stock_complete",
            validation,
            None,
            "No agent proposal was needed.",
            started_at,
            started_monotonic,
            project,
            base_fingerprint,
            actions_used=0,
            checks_used=0,
            exit_code=0,
        )

    try:
        provider.start(context, TOOL_SPECS)
    except Exception as error_value:  # provider adapters are outside the trust boundary
        validation = _empty_validation(
            "provider_error",
            initial_actionable,
            f"provider failed to start: {error_value}",
            check_name="provider_start",
        )
        return _finalize(
            run,
            run_record,
            "provider_error",
            validation,
            None,
            str(error_value),
            started_at,
            started_monotonic,
            project,
            base_fingerprint,
            actions_used=0,
            checks_used=0,
            exit_code=5,
        )
    manifest = _provider_context_manifest(provider)
    if manifest is not None:
        run.write_json("disclosure.json", manifest)

    tools = RepositoryTools(project.root, snapshot, readable_roots=_READABLE_ROOTS)
    observation: dict[str, Any] = {
        "status": "ok",
        "event": "context_ready",
        "actionable_goal_count": initial_actionable,
        "goal_count": snapshot["goal_count"],
    }
    current: _Candidate | None = None
    candidates: list[_Candidate] = []
    proposals_used = 0
    failed_digests: set[str] = set()
    best: _Candidate | None = None
    actions_used = 0
    checks_used = 0
    retrievals_used = 0
    status: str | None = None
    exit_code = 4
    finish_summary = ""

    while actions_used < max_actions:
        if time.monotonic() - started_monotonic >= wall_seconds:
            status = "exhausted"
            finish_summary = "The agent wall-time budget was exhausted."
            break
        try:
            action = provider.next_action(observation)
            provider_audit = _take_provider_audit(provider)
        except ProviderExhausted as error_value:
            status = "exhausted"
            finish_summary = str(error_value)
            break
        except AgentProtocolError as error_value:
            actions_used += 1
            provider_audit = _take_provider_audit(provider)
            observation = {
                "status": "error",
                "error": "invalid_action",
                "message": str(error_value),
            }
            _record_event(
                run,
                actions_used,
                None,
                observation,
                started_monotonic,
                provider_audit=provider_audit,
            )
            continue
        except Exception as error_value:  # provider adapters are untrusted
            actions_used += 1
            provider_audit = _take_provider_audit(provider)
            observation = {
                "status": "error",
                "error": "provider_error",
                "message": str(error_value),
            }
            _record_event(
                run,
                actions_used,
                None,
                observation,
                started_monotonic,
                provider_audit=provider_audit,
            )
            status = "provider_error"
            exit_code = 5
            finish_summary = f"Provider call failed: {error_value}"
            break

        actions_used += 1
        terminal = False
        try:
            if isinstance(action, SearchAction):
                if retrievals_used >= max_retrievals:
                    observation = _retrieval_budget_exhausted(max_retrievals)
                else:
                    retrievals_used += 1
                    observation = tools.search(action)
            elif isinstance(action, ReadAction):
                if retrievals_used >= max_retrievals:
                    observation = _retrieval_budget_exhausted(max_retrievals)
                else:
                    retrievals_used += 1
                    observation = tools.read(action)
            elif isinstance(action, InspectObligationAction):
                if retrievals_used >= max_retrievals:
                    observation = _retrieval_budget_exhausted(max_retrievals)
                else:
                    retrievals_used += 1
                    observation = tools.inspect(action)
            elif isinstance(action, ProposePatchAction):
                proposals_used += 1
                current, proposal_observation = _accept_proposal(
                    action,
                    run,
                    target_relative,
                    scope,
                    proposals_used,
                    failed_digests,
                )
                observation = proposal_observation
                if current is not None:
                    candidates.append(current)
            elif isinstance(action, RevertCandidateAction):
                reverted = current.sha256 if current is not None else None
                current = None
                observation = {
                    "status": "ok",
                    "event": "candidate_reverted",
                    "proposal_sha256": reverted,
                }
            elif isinstance(action, CheckAction):
                if current is None:
                    observation = {
                        "status": "error",
                        "error": "no_candidate",
                        "message": "propose a valid patch before requesting check",
                    }
                elif current.sha256 in failed_digests:
                    current = None
                    observation = {
                        "status": "error",
                        "error": "repeated_failed_digest",
                        "message": "that exact patch already failed and was reverted",
                    }
                elif checks_used >= max_checks:
                    observation = {
                        "status": "error",
                        "error": "check_budget_exhausted",
                        "message": f"the run is limited to {max_checks} checks",
                    }
                    status = "exhausted"
                    finish_summary = observation["message"]
                    terminal = True
                else:
                    checks_used += 1
                    result, child_exit = solve_with_patch(
                        target,
                        theorem,
                        current.path,
                        scope=scope,
                        through_line=through_line,
                        project_root=project.root,
                        runs_root=run.path / "checks",
                        timeout_seconds=min(timeout_seconds, wall_seconds),
                        rationale=current.rationale,
                    )
                    current.validation = result.get("validation")
                    current.child_run_id = result.get("run_id")
                    observation = _check_observation(
                        result, child_exit, action.mode, checks_used
                    )
                    _record_attempt(run, current, checks_used, result, action.mode)
                    best = _better_candidate(best, current)
                    if result.get("status") == "verified" and child_exit == 0:
                        status = "verified"
                        exit_code = 0
                        finish_summary = "The isolated final checker accepted the proposal."
                        best = current
                        terminal = True
                    elif result.get("status") in {"error", "environment_error"}:
                        status = result["status"]
                        exit_code = child_exit or 3
                        finish_summary = "The checker could not complete in this environment."
                        terminal = True
                    else:
                        failed_digests.add(current.sha256)
                        failed_check = observation.get("first_failed_check")
                        if failed_check in _AUTO_REVERT_CHECKS:
                            current = None
                            observation["candidate_reverted"] = True
            elif isinstance(action, FinishAction):
                status = "exhausted"
                finish_summary = action.summary
                observation = {
                    "status": "ok",
                    "event": "finished",
                    "summary": action.summary,
                }
                terminal = True
            else:
                raise AgentToolError(f"unsupported parsed action: {type(action).__name__}")
        except (AgentToolError, PatchError, OSError, UnicodeError) as error_value:
            observation = {
                "status": "error",
                "error": "tool_error",
                "message": str(error_value),
            }
        _record_event(
            run,
            actions_used,
            action,
            observation,
            started_monotonic,
            provider_audit=provider_audit,
        )
        if terminal:
            break

    if status is None:
        status = "exhausted"
        finish_summary = f"The {max_actions}-action budget was exhausted."

    _refresh_provider_metadata(run_record, provider)

    selected = best or current or (candidates[-1] if candidates else None)
    validation = _controller_validation(
        status,
        selected,
        initial_actionable,
        finish_summary,
    )
    return _finalize(
        run,
        run_record,
        status,
        validation,
        selected,
        finish_summary,
        started_at,
        started_monotonic,
        project,
        base_fingerprint,
        actions_used=actions_used,
        checks_used=checks_used,
        retrievals_used=retrievals_used,
        exit_code=exit_code,
    )


def _retrieval_budget_exhausted(limit: int) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "retrieval_budget_exhausted",
        "message": (
            f"the run is limited to {limit} retrieval actions; "
            "propose a patch, check the current candidate, or finish"
        ),
    }


def _accept_proposal(
    action: ProposePatchAction,
    run: RunDirectory,
    target_relative: str,
    scope: str,
    number: int,
    failed_digests: set[str],
) -> tuple[_Candidate | None, dict[str, Any]]:
    encoded = action.unified_diff.encode("utf-8")
    sha256 = hashlib.sha256(encoded).hexdigest()
    path = run.write_text(f"proposals/proposal-{number:03d}.patch", action.unified_diff)
    if len(encoded) > _MAX_PATCH_BYTES:
        return None, {
            "status": "error",
            "error": "patch_too_large",
            "message": f"patch exceeds the {_MAX_PATCH_BYTES}-byte limit",
            "proposal_sha256": sha256,
        }
    if sha256 in failed_digests:
        return None, {
            "status": "error",
            "error": "repeated_failed_digest",
            "message": "that exact patch already failed and was reverted",
            "proposal_sha256": sha256,
        }
    try:
        parsed = parse_unified_diff(action.unified_diff)
    except PatchError as error:
        return None, {
            "status": "error",
            "error": "invalid_patch",
            "message": str(error),
            "proposal_sha256": sha256,
        }
    if len(parsed.files) > _MAX_PATCH_FILES:
        return None, {
            "status": "error",
            "error": "too_many_patch_files",
            "message": f"patch exceeds the {_MAX_PATCH_FILES}-file limit",
            "proposal_sha256": sha256,
        }
    violations = scope_violations(parsed, target_relative, scope)
    if violations:
        return None, {
            "status": "error",
            "error": "scope_policy",
            "message": "candidate patch exceeds its writable scope",
            "violations": violations,
            "proposal_sha256": sha256,
        }
    candidate = _Candidate(
        number,
        path,
        sha256,
        len(encoded),
        action.rationale,
        parsed.paths,
    )
    return candidate, {
        "status": "ok",
        "event": "candidate_staged",
        "proposal": {
            "number": number,
            "sha256": sha256,
            "bytes": len(encoded),
            "files": list(parsed.paths),
        },
    }


def _check_observation(
    result: dict[str, Any], child_exit: int, requested_mode: str, attempt: int
) -> dict[str, Any]:
    validation = result.get("validation") or {}
    checks = validation.get("checks", [])
    failed = next(
        (
            check
            for check in checks
            if check.get("status") in {"failed", "unavailable"}
        ),
        None,
    )
    observation: dict[str, Any] = {
        "status": result.get("status", "error"),
        "event": "candidate_checked",
        "attempt": attempt,
        "requested_mode": requested_mode,
        "executed_mode": "final",
        "exit_code": child_exit,
        "child_run_id": result.get("run_id"),
        "residual_delta": validation.get("residual_delta"),
        "checks": [
            {
                "name": check.get("name"),
                "status": check.get("status"),
                "summary": check.get("summary"),
            }
            for check in checks
        ],
        "first_failed_check": failed.get("name") if failed else None,
    }
    if failed is not None:
        observation["failure"] = {
            "name": failed.get("name"),
            "summary": failed.get("summary"),
            "details": _bounded_value(failed.get("details", {})),
        }
    return observation


def _record_event(
    run: RunDirectory,
    sequence: int,
    action: AgentAction | None,
    observation: dict[str, Any],
    started_monotonic: float,
    *,
    provider_audit: Mapping[str, Any] | None = None,
) -> None:
    run.append_jsonl(
        "events.jsonl",
        {
            "sequence": sequence,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started_monotonic,
            "action": action_record(action)
            if action is not None
            else {"tool": "<invalid>", "arguments": {}},
            "observation": _bounded_value(observation),
            "provider": _bounded_value(provider_audit)
            if provider_audit is not None
            else None,
        },
    )


def _record_attempt(
    run: RunDirectory,
    candidate: _Candidate,
    attempt: int,
    result: dict[str, Any],
    requested_mode: str,
) -> None:
    run.append_jsonl(
        "attempts.jsonl",
        {
            "attempt": attempt,
            "kind": "agent_patch",
            "proposal_number": candidate.number,
            "proposal_sha256": candidate.sha256,
            "files": list(candidate.files),
            "requested_mode": requested_mode,
            "executed_mode": "final",
            "validation_status": result.get("status"),
            "residual_delta": (result.get("validation") or {}).get("residual_delta"),
            "child_run_id": result.get("run_id"),
            "child_run_directory": result.get("run_directory"),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _better_candidate(
    current_best: _Candidate | None, candidate: _Candidate
) -> _Candidate | None:
    candidate_score = _candidate_score(candidate)
    if candidate_score is None:
        return current_best
    if current_best is None:
        return candidate
    best_score = _candidate_score(current_best)
    if best_score is None or candidate_score < best_score:
        return candidate
    return current_best


def _candidate_score(candidate: _Candidate) -> int | None:
    if candidate.validation is None:
        return None
    final = candidate.validation.get("residual_delta", {}).get("final_actionable")
    return final if isinstance(final, int) and not isinstance(final, bool) else None


def _controller_validation(
    status: str,
    selected: _Candidate | None,
    initial_actionable: int,
    summary: str,
) -> dict[str, Any]:
    if selected is not None and selected.validation is not None:
        validation = {
            key: value
            for key, value in selected.validation.items()
        }
        validation["checks"] = [dict(check) for check in validation.get("checks", [])]
        validation["status"] = status
    else:
        return _empty_validation(status, initial_actionable, summary)
    validation["checks"].append(
        {
            "name": "agent_controller",
            "status": "passed" if status == "verified" else "failed",
            "summary": summary,
            "details": {
                "selected_proposal_sha256": selected.sha256 if selected else None,
                "selected_child_run_id": selected.child_run_id if selected else None,
            },
        }
    )
    return validation


def _empty_validation(
    status: str,
    initial_actionable: int,
    summary: str,
    *,
    final_actionable: int | None = None,
    check_status: str = "failed",
    check_name: str = "agent_controller",
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "status": status,
        "checks": [
            {
                "name": check_name,
                "status": check_status,
                "summary": summary,
                "details": {},
            }
        ],
        "residual_delta": {
            "initial_actionable": initial_actionable,
            "final_actionable": final_actionable,
            "closed_fingerprints": [],
            "opened_fingerprints": [],
        },
    }


def _finalize(
    run: RunDirectory,
    run_record: dict[str, Any],
    status: str,
    validation: dict[str, Any],
    selected: _Candidate | None,
    finish_summary: str,
    started_at: datetime,
    started_monotonic: float,
    project: Project,
    base_fingerprint: str | None,
    *,
    actions_used: int,
    checks_used: int,
    retrievals_used: int = 0,
    exit_code: int,
) -> tuple[dict[str, Any], int]:
    proposal_text = ""
    if selected is not None:
        proposal_text = selected.path.read_text(encoding="utf-8")
        run_record["proposal"].update(
            {
                "sha256": selected.sha256,
                "rationale": selected.rationale,
                "files": list(selected.files),
                "selected_proposal_number": selected.number,
            }
        )
    run.write_text("proposal.patch", proposal_text)
    if not (run.path / "events.jsonl").exists():
        run.write_text("events.jsonl", "")
    if not (run.path / "attempts.jsonl").exists():
        run.write_text("attempts.jsonl", "")

    final_fingerprint = _worktree_fingerprint(project.root)
    if base_fingerprint is not None and final_fingerprint != base_fingerprint:
        status = "rejected"
        exit_code = 4
        validation["status"] = status
        existing = next(
            (
                check
                for check in validation["checks"]
                if check.get("name") == "source_tree_unchanged"
            ),
            None,
        )
        source_check = {
            "name": "source_tree_unchanged",
            "status": "failed",
            "summary": "the source worktree changed during the agent run",
            "details": {
                "initial": base_fingerprint,
                "final": final_fingerprint,
            },
        }
        if existing is None:
            validation["checks"].append(source_check)
        else:
            existing.update(source_check)

    finished_at = datetime.now(timezone.utc)
    run_record["status"] = status
    run_record["finished_at"] = finished_at.isoformat()
    run_record["elapsed_seconds"] = (finished_at - started_at).total_seconds()
    run_record["controller"] = {
        "actions_used": actions_used,
        "checks_used": checks_used,
        "retrievals_used": retrievals_used,
        "termination": finish_summary,
        "elapsed_seconds": time.monotonic() - started_monotonic,
    }
    run_record["artifacts"] = {
        "context": "context.initial.json"
        if (run.path / "context.initial.json").is_file()
        else None,
        "disclosure": "disclosure.json"
        if (run.path / "disclosure.json").is_file()
        else None,
        "initial_obligations": "obligations.initial.json",
        "events": "events.jsonl",
        "attempts": "attempts.jsonl",
        "proposal": "proposal.patch",
        "proposals": "proposals/",
        "checks": "checks/" if (run.path / "checks").is_dir() else None,
        "validation": "validation.json",
        "summary": "summary.md",
        "tools": "tools.json",
    }
    run.write_json("validation.json", validation)
    run.write_json("run.json", run_record)
    run.write_text("summary.md", _summary_markdown(run_record, validation))
    result = {
        "schema_version": "0.1",
        "run_id": run.run_id,
        "status": status,
        "run_directory": str(run.path),
        "proposal": str(run.path / "proposal.patch"),
        "validation": validation,
        "agent": {
            **run_record["model"],
            **run_record["controller"],
        },
    }
    return result, exit_code


def _summary_markdown(run: dict[str, Any], validation: dict[str, Any]) -> str:
    delta = validation["residual_delta"]
    lines = [
        f"# Rupicola LLM agent run `{run['run_id']}`",
        "",
        f"Status: **{run['status']}**",
        "",
        f"Target: `{run['target']['file']}::{run['target']['theorem']}`",
        "",
        f"Provider: `{run['model']['provider']}`",
        "",
        f"Actions/checks: {run['controller']['actions_used']}/"
        f"{run['controller']['checks_used']}",
        "",
        f"Residuals: {delta['initial_actionable']} -> "
        f"{delta['final_actionable'] if delta['final_actionable'] is not None else '?'}",
        "",
        "## Validation",
        "",
    ]
    for check in validation["checks"]:
        lines.append(f"- `{check['status']}` **{check['name']}** — {check['summary']}")
    lines.extend(
        (
            "",
            "The selected proposal remains unapplied in `proposal.patch`.",
            "Every typed action and checker attempt is retained in the run directory.",
            "",
        )
    )
    return "\n".join(lines)


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return "[nested value truncated]"
    if isinstance(value, str):
        return value if len(value) <= 12_000 else value[:12_000] + "\n[truncated]"
    if isinstance(value, list):
        return [_bounded_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, tuple):
        return [_bounded_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {
            str(key): _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    return value


def _take_provider_audit(provider: AgentProvider) -> Mapping[str, Any] | None:
    take = getattr(provider, "take_audit_record", None)
    if not callable(take):
        return None
    try:
        value = take()
    except Exception as error:  # audit hooks cannot control proof acceptance
        return {
            "status": "unavailable",
            "error_type": type(error).__name__,
        }
    return value if isinstance(value, Mapping) else None


def _provider_context_manifest(
    provider: AgentProvider,
) -> Mapping[str, Any] | None:
    read = getattr(provider, "context_manifest", None)
    if not callable(read):
        return None
    try:
        value = read()
    except Exception as error:  # disclosure evidence is best effort after provider start
        return {
            "schema_version": "0.1",
            "status": "unavailable",
            "error_type": type(error).__name__,
        }
    return value if isinstance(value, Mapping) else None


def _refresh_provider_metadata(
    run_record: dict[str, Any], provider: AgentProvider
) -> None:
    try:
        metadata = provider.metadata.to_dict()
    except Exception:
        return
    run_record["model"].update(
        {
            "invoked": metadata["model_invoked"],
            "provider": metadata["provider"],
            "model": metadata["model"],
            "remote": metadata["remote"],
            "configuration": metadata.get("configuration", {}),
        }
    )
    usage = _provider_usage_summary(provider)
    if usage is not None:
        run_record["model"]["usage"] = _bounded_value(usage)


def _provider_usage_summary(
    provider: AgentProvider,
) -> Mapping[str, Any] | None:
    read = getattr(provider, "usage_summary", None)
    if not callable(read):
        return None
    try:
        value = read()
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _validate_request(
    theorem: str,
    scope: str,
    timeout_seconds: float,
    max_actions: int,
    max_checks: int,
    max_retrievals: int,
    wall_seconds: float,
) -> str | None:
    if _THEOREM_RE.fullmatch(theorem) is None:
        return f"invalid theorem identifier: {theorem!r}"
    if scope not in {"local", "project"}:
        return f"unsupported augmentation scope: {scope!r}"
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        return "timeout_seconds must be positive and finite"
    if isinstance(max_actions, bool) or not 1 <= max_actions <= 100:
        return "max_actions must be between 1 and 100"
    if isinstance(max_checks, bool) or not 1 <= max_checks <= 20:
        return "max_checks must be between 1 and 20"
    if isinstance(max_retrievals, bool) or not 0 <= max_retrievals <= 100:
        return "max_retrievals must be between 0 and 100"
    if not math.isfinite(wall_seconds) or wall_seconds <= 0:
        return "wall_seconds must be positive and finite"
    return None


def _agent_error(message: str) -> dict[str, Any]:
    return {"schema_version": "0.1", "status": "error", "message": message}
