from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


class DisclosureError(RuntimeError):
    pass


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret(?:[_-]?access)?[_-]?key|password|"
            r"auth[_-]?token)\b\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}"
        ),
    ),
)


def ensure_no_likely_secrets(value: Any) -> None:
    findings = scan_for_likely_secrets(value)
    if not findings:
        return
    descriptions = ", ".join(
        f"{finding['kind']} at {finding['path']}" for finding in findings
    )
    raise DisclosureError(
        "remote source disclosure blocked by likely credential material: "
        f"{descriptions}"
    )


def scan_for_likely_secrets(value: Any) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path, text in _strings(value):
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(text) is not None:
                findings.append({"kind": label, "path": path})
                if len(findings) >= 20:
                    return findings
    return findings


def context_manifest(
    context: Mapping[str, Any],
    *,
    provider: str,
    model_id: str,
    region: str,
    profile: str | None,
    removed_fields: list[str] | None = None,
) -> dict[str, Any]:
    encoded = json.dumps(
        context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    diagnosis = context.get("diagnosis", {})
    snapshot = diagnosis.get("snapshot", {}) if isinstance(diagnosis, dict) else {}
    goals = snapshot.get("goals", []) if isinstance(snapshot, dict) else []
    evidence_paths = sorted(
        {
            evidence["path"]
            for goal in goals
            if isinstance(goal, dict)
            for evidence in goal.get("evidence", [])
            if isinstance(evidence, dict) and isinstance(evidence.get("path"), str)
        }
    )
    target = diagnosis.get("target", {}) if isinstance(diagnosis, dict) else {}
    permissions = context.get("permissions", {})
    return {
        "schema_version": "0.1",
        "confirmed": True,
        "provider": provider,
        "model_id": model_id,
        "region": region,
        "profile": profile,
        "initial_context": {
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "target": target.get("file") if isinstance(target, dict) else None,
            "goal_count": len(goals),
            "evidence_paths": evidence_paths,
        },
        "retrieval": {
            "readable_roots": list(permissions.get("readable_roots", []))
            if isinstance(permissions, dict)
            else [],
            "future_tool_results_may_include_source": True,
        },
        "secret_scan": {
            "policy": "high-confidence credential patterns",
            "status": "passed",
        },
        "context_minimization": {
            "removed_fields": list(removed_fields or []),
        },
        "account_invocation_logging": "not_inspected_by_client",
    }


def minimize_remote_context(
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    try:
        minimized = json.loads(json.dumps(context, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise DisclosureError(f"proof context is not JSON-compatible: {error}") from error
    if not isinstance(minimized, dict):
        raise DisclosureError("proof context must be a JSON object")

    removed: list[str] = []
    diagnosis = minimized.get("diagnosis")
    project = diagnosis.get("project") if isinstance(diagnosis, dict) else None
    if isinstance(project, dict):
        for name in ("root", "project_file", "coqidetop"):
            if name in project:
                del project[name]
                removed.append(f"$.diagnosis.project.{name}")
        load_paths = project.get("load_paths")
        if isinstance(load_paths, list):
            for index, load_path in enumerate(load_paths):
                if isinstance(load_path, dict) and "physical" in load_path:
                    del load_path["physical"]
                    removed.append(
                        f"$.diagnosis.project.load_paths[{index}].physical"
                    )
    return minimized, removed


def _strings(value: Any, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        result: list[tuple[str, str]] = []
        for key, item in value.items():
            result.extend(_strings(item, f"{path}.{key}"))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for index, item in enumerate(value):
            result.extend(_strings(item, f"{path}[{index}]"))
        return result
    return []
