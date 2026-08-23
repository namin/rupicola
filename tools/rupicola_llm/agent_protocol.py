from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, TypeAlias


class AgentProtocolError(ValueError):
    pass


class ProviderExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass(frozen=True)
class SearchAction:
    query: str
    path: str = "src/Rupicola"
    max_results: int = 10
    kind: str = "search"


@dataclass(frozen=True)
class ReadAction:
    path: str
    start_line: int = 1
    end_line: int | None = None
    kind: str = "read"


@dataclass(frozen=True)
class InspectObligationAction:
    obligation_id: str
    printing_mode: str = "raw"
    kind: str = "inspect_obligation"


@dataclass(frozen=True)
class ProposePatchAction:
    unified_diff: str
    rationale: str
    kind: str = "propose_patch"


@dataclass(frozen=True)
class CheckAction:
    mode: str = "fast"
    kind: str = "check"


@dataclass(frozen=True)
class RevertCandidateAction:
    kind: str = "revert_candidate"


@dataclass(frozen=True)
class FinishAction:
    summary: str
    kind: str = "finish"


AgentAction: TypeAlias = (
    SearchAction
    | ReadAction
    | InspectObligationAction
    | ProposePatchAction
    | CheckAction
    | RevertCandidateAction
    | FinishAction
)


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str | None
    remote: bool
    model_invoked: bool
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "remote": self.remote,
            "model_invoked": self.model_invoked,
            "configuration": self.configuration,
        }


class AgentProvider(Protocol):
    @property
    def metadata(self) -> ProviderMetadata:
        ...

    def start(
        self, context: Mapping[str, Any], tools: tuple[ToolSpec, ...]
    ) -> None:
        ...

    def next_action(self, observation: Mapping[str, Any]) -> AgentAction:
        ...

    def take_audit_record(self) -> Mapping[str, Any] | None:
        ...

    def context_manifest(self) -> Mapping[str, Any] | None:
        ...

    def usage_summary(self) -> Mapping[str, Any] | None:
        ...


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "search",
        "Search Rocq source below the disclosed read root using a literal query.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "path": {"type": "string", "default": "src/Rupicola"},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 10,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "read",
        "Read at most 200 numbered lines from one disclosed Rocq source file.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1, "default": 1},
                "end_line": {"type": ["integer", "null"], "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "inspect_obligation",
        "Inspect one residual by one-based index, goal ID, or full fingerprint.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "printing_mode": {
                    "type": "string",
                    "enum": ["raw", "normalized"],
                    "default": "raw",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "propose_patch",
        "Submit one minimal complete unified diff against the unchanged project "
        "source. Hunk counts and unchanged context must be exact; do not include "
        "cosmetic edits.",
        {
            "type": "object",
            "properties": {
                "unified_diff": {"type": "string", "minLength": 1},
                "rationale": {"type": "string", "minLength": 1, "maxLength": 4000},
            },
            "required": ["unified_diff", "rationale"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "check",
        "Validate the current patch in an isolated workspace. Fast currently "
        "uses the stricter final pipeline.",
        {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["fast", "final"],
                    "default": "fast",
                }
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "revert_candidate",
        "Discard the current unvalidated candidate patch.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        "finish",
        "Stop the bounded run and summarize the outcome.",
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "minLength": 1, "maxLength": 4000}
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    ),
)


def parse_action(value: Mapping[str, Any]) -> AgentAction:
    if not isinstance(value, Mapping):
        raise AgentProtocolError("provider action must be an object")
    _require_keys(value, {"tool", "arguments"}, required={"tool"})
    tool = _string(value.get("tool"), "tool", max_length=64)
    arguments_value = value.get("arguments", {})
    if not isinstance(arguments_value, Mapping):
        raise AgentProtocolError("action arguments must be an object")
    arguments = dict(arguments_value)

    if tool == "search":
        _require_keys(
            arguments,
            {"query", "path", "max_results"},
            required={"query"},
        )
        query = _string(arguments.get("query"), "query", max_length=200)
        if "\n" in query or "\r" in query:
            raise AgentProtocolError("search query must be a single line")
        path = _relative_path(arguments.get("path", "src/Rupicola"), "path")
        max_results = _integer(arguments.get("max_results", 10), "max_results")
        if not 1 <= max_results <= 20:
            raise AgentProtocolError("max_results must be between 1 and 20")
        return SearchAction(query, path, max_results)

    if tool == "read":
        _require_keys(
            arguments,
            {"path", "start_line", "end_line"},
            required={"path"},
        )
        path = _relative_path(arguments.get("path"), "path")
        start = _integer(arguments.get("start_line", 1), "start_line")
        end_value = arguments.get("end_line")
        end = None if end_value is None else _integer(end_value, "end_line")
        if start < 1 or (end is not None and end < start):
            raise AgentProtocolError("read line range must be positive and ordered")
        if end is not None and end - start + 1 > 200:
            raise AgentProtocolError("read action is limited to 200 lines")
        return ReadAction(path, start, end)

    if tool == "inspect_obligation":
        _require_keys(
            arguments,
            {"id", "printing_mode"},
            required={"id"},
        )
        obligation_id = _string(arguments.get("id"), "id", max_length=128)
        printing_mode = _string(
            arguments.get("printing_mode", "raw"),
            "printing_mode",
            max_length=32,
        )
        if printing_mode not in {"raw", "normalized"}:
            raise AgentProtocolError("printing_mode must be raw or normalized")
        return InspectObligationAction(obligation_id, printing_mode)

    if tool == "propose_patch":
        _require_keys(
            arguments,
            {"unified_diff", "rationale"},
            required={"unified_diff", "rationale"},
        )
        unified_diff = _string(
            arguments.get("unified_diff"), "unified_diff", max_length=1_048_576
        )
        rationale = _string(arguments.get("rationale"), "rationale", max_length=4000)
        return ProposePatchAction(unified_diff, rationale)

    if tool == "check":
        _require_keys(arguments, {"mode"})
        mode = _string(arguments.get("mode", "fast"), "mode", max_length=16)
        if mode not in {"fast", "final"}:
            raise AgentProtocolError("check mode must be fast or final")
        return CheckAction(mode)

    if tool == "revert_candidate":
        _require_keys(arguments, set())
        return RevertCandidateAction()

    if tool == "finish":
        _require_keys(arguments, {"summary"}, required={"summary"})
        return FinishAction(
            _string(arguments.get("summary"), "summary", max_length=4000)
        )

    raise AgentProtocolError(f"unknown agent tool: {tool!r}")


def action_record(action: AgentAction) -> dict[str, Any]:
    if isinstance(action, ProposePatchAction):
        encoded = action.unified_diff.encode("utf-8")
        arguments: dict[str, Any] = {
            "patch_sha256": hashlib.sha256(encoded).hexdigest(),
            "patch_bytes": len(encoded),
            "rationale": action.rationale,
        }
    elif isinstance(action, SearchAction):
        arguments = {
            "query": action.query,
            "path": action.path,
            "max_results": action.max_results,
        }
    elif isinstance(action, ReadAction):
        arguments = {
            "path": action.path,
            "start_line": action.start_line,
            "end_line": action.end_line,
        }
    elif isinstance(action, InspectObligationAction):
        arguments = {
            "id": action.obligation_id,
            "printing_mode": action.printing_mode,
        }
    elif isinstance(action, CheckAction):
        arguments = {"mode": action.mode}
    elif isinstance(action, FinishAction):
        arguments = {"summary": action.summary}
    else:
        arguments = {}
    return {"tool": action.kind, "arguments": arguments}


class ScriptedProvider:
    """Deterministic development provider for exercising the controller.

    Script files contain the same typed tool calls returned by a model adapter.
    For compact fixtures only, a propose_patch action may use ``patch_file``;
    it is resolved beneath the script directory before protocol validation.
    """

    def __init__(
        self,
        script_path: Path,
        actions: tuple[Mapping[str, Any], ...],
        metadata: ProviderMetadata,
    ) -> None:
        self.script_path = script_path
        self._actions = actions
        self._metadata = metadata
        self._index = 0
        self.context: Mapping[str, Any] | None = None
        self.tools: tuple[ToolSpec, ...] = ()
        self._last_audit: dict[str, Any] | None = None

    @classmethod
    def load(cls, path: Path) -> "ScriptedProvider":
        script_path = path.expanduser().resolve()
        try:
            document = json.loads(script_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentProtocolError(f"could not read provider script: {error}") from error
        if not isinstance(document, dict):
            raise AgentProtocolError("provider script must contain a JSON object")
        _require_keys(
            document,
            {"schema_version", "provider", "model", "actions"},
            required={"schema_version", "actions"},
        )
        if document["schema_version"] != "0.1":
            raise AgentProtocolError(
                f"unsupported provider script schema: {document['schema_version']!r}"
            )
        raw_actions = document["actions"]
        if not isinstance(raw_actions, list):
            raise AgentProtocolError("provider script actions must be an array")
        if not all(isinstance(action, dict) for action in raw_actions):
            raise AgentProtocolError("each provider script action must be an object")
        provider = document.get("provider", "scripted")
        model = document.get("model")
        metadata = ProviderMetadata(
            _string(provider, "provider", max_length=128),
            None if model is None else _string(model, "model", max_length=256),
            remote=False,
            model_invoked=False,
        )
        return cls(script_path, tuple(raw_actions), metadata)

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    def start(
        self, context: Mapping[str, Any], tools: tuple[ToolSpec, ...]
    ) -> None:
        self.context = context
        self.tools = tools

    def next_action(self, observation: Mapping[str, Any]) -> AgentAction:
        del observation
        if self._index >= len(self._actions):
            raise ProviderExhausted("scripted provider has no actions remaining")
        raw = dict(self._actions[self._index])
        self._index += 1
        self._last_audit = {
            "provider": self.metadata.provider,
            "script_action": self._index,
        }
        raw = self._expand_patch_file(raw)
        return parse_action(raw)

    def take_audit_record(self) -> Mapping[str, Any] | None:
        record = self._last_audit
        self._last_audit = None
        return record

    def context_manifest(self) -> Mapping[str, Any] | None:
        return None

    def usage_summary(self) -> Mapping[str, Any] | None:
        return None

    def _expand_patch_file(self, raw: dict[str, Any]) -> dict[str, Any]:
        if raw.get("tool") != "propose_patch":
            return raw
        arguments_value = raw.get("arguments", {})
        if not isinstance(arguments_value, dict) or "patch_file" not in arguments_value:
            return raw
        arguments = dict(arguments_value)
        if "unified_diff" in arguments:
            raise AgentProtocolError(
                "scripted propose_patch cannot set both patch_file and unified_diff"
            )
        relative = _relative_path(arguments.pop("patch_file"), "patch_file")
        script_root = self.script_path.parent.resolve()
        candidate = script_root.joinpath(*PurePosixPath(relative).parts)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(script_root)
        except ValueError as error:
            raise AgentProtocolError("patch_file escapes the script directory") from error
        if candidate.is_symlink() or not candidate.is_file():
            raise AgentProtocolError(f"patch_file is not a regular file: {relative}")
        try:
            arguments["unified_diff"] = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise AgentProtocolError(f"could not read patch_file: {error}") from error
        return {"tool": raw.get("tool"), "arguments": arguments}


def _require_keys(
    value: Mapping[str, Any], allowed: set[str], *, required: set[str] | None = None
) -> None:
    keys = set(value)
    unexpected = sorted(keys - allowed)
    missing = sorted((required or set()) - keys)
    if unexpected:
        raise AgentProtocolError(f"unexpected fields: {', '.join(unexpected)}")
    if missing:
        raise AgentProtocolError(f"missing required fields: {', '.join(missing)}")


def _string(value: Any, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value:
        raise AgentProtocolError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise AgentProtocolError(f"{name} exceeds the {max_length}-character limit")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise AgentProtocolError(f"{name} must be valid UTF-8 text") from error
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentProtocolError(f"{name} must be an integer")
    return value


def _relative_path(value: Any, name: str) -> str:
    raw = _string(value, name, max_length=1024)
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "\\" in raw or "\x00" in raw:
        raise AgentProtocolError(f"{name} must be a safe project-relative path")
    return path.as_posix()
