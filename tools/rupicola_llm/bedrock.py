from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
from typing import Any, Mapping, Protocol

from .agent_protocol import (
    AgentAction,
    AgentProtocolError,
    InspectObligationAction,
    ProviderMetadata,
    ReadAction,
    SearchAction,
    ToolSpec,
    parse_action,
)
from .disclosure import (
    DisclosureError,
    context_manifest as build_context_manifest,
    ensure_no_likely_secrets,
    minimize_remote_context,
)


class BedrockError(RuntimeError):
    pass


_READ_ONLY_ACTIONS = (SearchAction, ReadAction, InspectObligationAction)
_MAX_READ_ONLY_BATCH = 4


class ConverseTransport(Protocol):
    def converse(self, request: Mapping[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AwsCliConverseTransport:
    region: str
    profile: str | None = None
    timeout_seconds: float = 180.0
    executable: str = "aws"

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise BedrockError("AWS CLI transport timeout must be positive and finite")
        if not self.executable:
            raise BedrockError("AWS CLI executable must not be empty")

    def converse(self, request: Mapping[str, Any]) -> dict[str, Any]:
        executable = shutil.which(self.executable)
        if executable is None:
            raise BedrockError(f"AWS CLI executable is unavailable: {self.executable}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="rupicola-bedrock-", suffix=".json"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                json.dump(request, stream, ensure_ascii=False, separators=(",", ":"))
            command = [
                executable,
                "bedrock-runtime",
                "converse",
                "--region",
                self.region,
                "--cli-input-json",
                f"file://{temporary}",
                "--output",
                "json",
                "--no-cli-pager",
            ]
            if self.profile is not None:
                command.extend(("--profile", self.profile))
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as error:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise BedrockError(
                    f"Bedrock Converse exceeded {self.timeout_seconds:g} seconds"
                ) from error
            if process.returncode != 0:
                message = _bounded_error(stderr or stdout)
                raise BedrockError(
                    f"AWS Bedrock Converse failed with exit {process.returncode}: {message}"
                )
            if len(stdout.encode("utf-8")) > 4_000_000:
                raise BedrockError("AWS Bedrock Converse response exceeds 4 MB")
            try:
                response = json.loads(stdout)
            except json.JSONDecodeError as error:
                raise BedrockError(
                    f"AWS Bedrock Converse returned invalid JSON: {error}"
                ) from error
            if not isinstance(response, dict):
                raise BedrockError("AWS Bedrock Converse response must be an object")
            return response
        except OSError as error:
            raise BedrockError(f"could not invoke AWS Bedrock Converse: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)


class BedrockProvider:
    def __init__(
        self,
        transport: ConverseTransport,
        *,
        model_id: str,
        region: str,
        profile: str | None,
        allow_remote_source: bool,
        max_tokens: int = 8192,
        temperature: float | None = None,
        strict_tools: bool = True,
        force_tool: bool = True,
    ) -> None:
        if not model_id or len(model_id) > 2048:
            raise BedrockError("Bedrock model ID must contain between 1 and 2048 characters")
        if re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region) is None:
            raise BedrockError(f"invalid AWS region: {region!r}")
        if not 1 <= max_tokens <= 100_000:
            raise BedrockError("Bedrock max tokens must be between 1 and 100000")
        if temperature is not None and not 0.0 <= temperature <= 1.0:
            raise BedrockError("Bedrock temperature must be between 0 and 1")
        self.transport = transport
        self.model_id = model_id
        self.region = region
        self.profile = profile
        self.allow_remote_source = allow_remote_source
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.strict_tools = strict_tools
        self.force_tool = force_tool
        self._messages: list[dict[str, Any]] = []
        self._system: list[dict[str, str]] = []
        self._tool_config: dict[str, Any] = {}
        self._optional_tool_fields: dict[str, frozenset[str]] = {}
        self._active_tool_id: str | None = None
        self._queued_actions: list[tuple[str, AgentAction]] = []
        self._completed_tool_results: list[dict[str, Any]] = []
        self._pending_error_tool_ids: list[str] = []
        self._needs_text_feedback = False
        self._batch_size = 0
        self._started = False
        self._invocations = 0
        self._usage_totals: dict[str, int] = {}
        self._model_latency_ms = 0
        self._last_audit: dict[str, Any] | None = None
        self._context_manifest: dict[str, Any] | None = None

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider="aws-bedrock-converse",
            model=self.model_id,
            remote=True,
            model_invoked=self._invocations > 0,
            configuration={
                "region": self.region,
                "profile": self.profile,
                "transport": "aws-cli",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "strict_tools": self.strict_tools,
                "force_tool": self.force_tool,
                "system_prompt_sha256": hashlib.sha256(
                    _SYSTEM_PROMPT.encode("utf-8")
                ).hexdigest(),
            },
        )

    def start(
        self, context: Mapping[str, Any], tools: tuple[ToolSpec, ...]
    ) -> None:
        if self._started:
            raise BedrockError("Bedrock provider cannot be started twice")
        if not self.allow_remote_source:
            raise DisclosureError(
                "remote Bedrock use requires explicit source-disclosure confirmation"
            )
        remote_context, removed_fields = minimize_remote_context(context)
        ensure_no_likely_secrets(remote_context)
        self._context_manifest = build_context_manifest(
            remote_context,
            provider=self.metadata.provider,
            model_id=self.model_id,
            region=self.region,
            profile=self.profile,
            removed_fields=removed_fields,
        )
        self._system = [{"text": _SYSTEM_PROMPT}]
        context_text = json.dumps(remote_context, ensure_ascii=False, sort_keys=True)
        self._messages = [
            {
                "role": "user",
                "content": [
                    {
                        "text": "Rupicola proof-repair context (JSON):\n" + context_text
                    }
                ],
            }
        ]
        bedrock_tools = [_bedrock_tool(tool, self.strict_tools) for tool in tools]
        self._optional_tool_fields = {
            tool.name: frozenset(tool.input_schema.get("properties", {}))
            - frozenset(tool.input_schema.get("required", []))
            for tool in tools
        }
        self._tool_config = {"tools": bedrock_tools}
        if self.force_tool:
            self._tool_config["toolChoice"] = {"any": {}}
        self._started = True

    def next_action(self, observation: Mapping[str, Any]) -> AgentAction:
        if not self._started:
            raise BedrockError("Bedrock provider must be started before use")
        if self._invocations:
            queued = self._consume_observation(observation)
            if queued is not None:
                return queued
        inference_config: dict[str, Any] = {"maxTokens": self.max_tokens}
        if self.temperature is not None:
            inference_config["temperature"] = self.temperature
        request = {
            "modelId": self.model_id,
            "messages": self._messages,
            "system": self._system,
            "inferenceConfig": inference_config,
            "toolConfig": self._tool_config,
        }
        ensure_no_likely_secrets(request)
        try:
            response = self.transport.converse(request)
        except Exception as error:
            self._last_audit = {
                "provider": self.metadata.provider,
                "invocation": self._invocations + 1,
                "model_id": self.model_id,
                "region": self.region,
                "status": "error",
                "error_type": type(error).__name__,
            }
            raise
        self._invocations += 1
        self._accumulate_usage(response)
        message = _assistant_message(response)
        self._messages.append(message)
        tool_uses = [
            block["toolUse"]
            for block in message["content"]
            if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
        ]
        self._last_audit = _audit_record(
            response,
            provider=self.metadata.provider,
            model_id=self.model_id,
            region=self.region,
            invocation=self._invocations,
            tool_uses=tool_uses,
            message=message,
        )
        if not tool_uses:
            self._needs_text_feedback = True
            raise AgentProtocolError(
                "Bedrock must return at least one tool use per controller turn"
            )

        parsed: list[tuple[str, AgentAction]] = []
        try:
            parsed = [
                _parse_tool_use(tool_use, self._optional_tool_fields)
                for tool_use in tool_uses
            ]
        except AgentProtocolError:
            self._pending_error_tool_ids = _valid_tool_ids(tool_uses)
            self._needs_text_feedback = not self._pending_error_tool_ids
            raise

        if len(parsed) > _MAX_READ_ONLY_BATCH:
            self._pending_error_tool_ids = [tool_id for tool_id, _ in parsed]
            raise AgentProtocolError(
                "Bedrock read-only tool batch exceeds the per-turn limit of "
                f"{_MAX_READ_ONLY_BATCH}; received {len(parsed)} calls"
            )
        if len(parsed) > 1 and not all(
            isinstance(action, _READ_ONLY_ACTIONS) for _, action in parsed
        ):
            self._pending_error_tool_ids = [tool_id for tool_id, _ in parsed]
            raise AgentProtocolError(
                "Bedrock may batch only independent read-only tool uses; "
                f"received {len(parsed)} calls including a stateful action"
            )

        self._batch_size = len(parsed)
        self._active_tool_id, first = parsed[0]
        self._queued_actions = parsed[1:]
        return first

    def take_audit_record(self) -> Mapping[str, Any] | None:
        record = self._last_audit
        self._last_audit = None
        return record

    def context_manifest(self) -> Mapping[str, Any] | None:
        return self._context_manifest

    def usage_summary(self) -> Mapping[str, Any]:
        return {
            "invocations": self._invocations,
            "tokens": dict(sorted(self._usage_totals.items())),
            "model_latency_ms": self._model_latency_ms,
        }

    def _accumulate_usage(self, response: Mapping[str, Any]) -> None:
        usage = response.get("usage")
        if isinstance(usage, Mapping):
            for name, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    self._usage_totals[str(name)] = (
                        self._usage_totals.get(str(name), 0) + value
                    )
        metrics = response.get("metrics")
        latency = metrics.get("latencyMs") if isinstance(metrics, Mapping) else None
        if isinstance(latency, int) and not isinstance(latency, bool):
            self._model_latency_ms += latency

    def _consume_observation(
        self, observation: Mapping[str, Any]
    ) -> AgentAction | None:
        safe_observation = _json_round_trip(observation)
        status = "error" if observation.get("status") == "error" else "success"
        if self._active_tool_id is not None:
            self._completed_tool_results.append(
                _tool_result(self._active_tool_id, safe_observation, status)
            )
            self._active_tool_id = None
        elif self._pending_error_tool_ids:
            self._completed_tool_results.extend(
                _tool_result(tool_id, safe_observation, "error")
                for tool_id in self._pending_error_tool_ids
            )
            self._pending_error_tool_ids = []
        elif self._needs_text_feedback:
            self._append_text_feedback(safe_observation)
            self._needs_text_feedback = False

        if self._queued_actions:
            batch_position = self._batch_size - len(self._queued_actions) + 1
            self._active_tool_id, action = self._queued_actions.pop(0)
            self._last_audit = {
                "provider": self.metadata.provider,
                "invocation": self._invocations,
                "model_id": self.model_id,
                "region": self.region,
                "status": "batched_tool_use",
                "batch_position": batch_position,
                "batch_size": self._batch_size,
                "tool_name": action.kind,
            }
            return action

        if self._completed_tool_results:
            self._messages.append(
                {"role": "user", "content": self._completed_tool_results}
            )
            self._completed_tool_results = []
            self._batch_size = 0
        return None

    def _append_text_feedback(self, observation: Any) -> None:
        self._messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Controller feedback (JSON):\n"
                            + json.dumps(
                                observation, ensure_ascii=False, sort_keys=True
                            )
                            + "\nReturn exactly one typed tool call."
                        )
                    }
                ],
            }
        )


def _parse_tool_use(
    tool_use: Mapping[str, Any],
    optional_fields: Mapping[str, frozenset[str]],
) -> tuple[str, AgentAction]:
    tool_id = tool_use.get("toolUseId")
    name = tool_use.get("name")
    arguments = tool_use.get("input")
    if not isinstance(tool_id, str) or not tool_id:
        raise AgentProtocolError("Bedrock tool use is missing toolUseId")
    if not isinstance(name, str) or not name:
        raise AgentProtocolError("Bedrock tool use is missing its name")
    if not isinstance(arguments, dict):
        raise AgentProtocolError("Bedrock tool input must be a JSON object")
    arguments = {
        key: value
        for key, value in arguments.items()
        if value is not None or key not in optional_fields.get(name, ())
    }
    return tool_id, parse_action({"tool": name, "arguments": arguments})


def _valid_tool_ids(tool_uses: list[dict[str, Any]]) -> list[str]:
    return [
        tool_id
        for tool_use in tool_uses
        if isinstance((tool_id := tool_use.get("toolUseId")), str) and tool_id
    ]


def _tool_result(tool_id: str, observation: Any, status: str) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_id,
            "content": [{"json": observation}],
            "status": status,
        }
    }


def resolve_aws_region(
    explicit: str | None,
    *,
    profile: str | None,
    executable: str = "aws",
) -> str:
    if explicit:
        return explicit
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.environ.get(name)
        if value:
            return value
    command = [executable, "configure", "get", "region"]
    if profile is not None:
        command.extend(("--profile", profile))
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BedrockError(f"could not resolve AWS region: {error}") from error
    region = result.stdout.strip()
    if result.returncode != 0 or not region:
        raise BedrockError(
            "AWS region is not configured; pass --aws-region or configure the profile"
        )
    return region


def _bedrock_tool(tool: ToolSpec, strict: bool) -> dict[str, Any]:
    schema = _bedrock_schema(tool.input_schema)
    if strict:
        schema = _strict_schema(schema)
    specification: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": {"json": schema},
    }
    if strict:
        specification["strict"] = True
    return {"toolSpec": specification}


def _bedrock_schema(value: Any) -> Any:
    unsupported = {"minimum", "maximum", "minLength", "maxLength", "default"}
    if isinstance(value, dict):
        return {
            key: _bedrock_schema(item)
            for key, item in value.items()
            if key not in unsupported
        }
    if isinstance(value, list):
        return [_bedrock_schema(item) for item in value]
    return value


def _strict_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _strict_schema(item) for key, item in value.items()}
    properties = result.get("properties")
    if result.get("type") == "object" and isinstance(properties, dict):
        required = set(result.get("required", []))
        for name in properties:
            if name not in required:
                properties[name] = _nullable_schema(properties[name])
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def _nullable_schema(value: Any) -> Any:
    if not isinstance(value, dict):
        return {"anyOf": [value, {"type": "null"}]}
    result = dict(value)
    kind = result.get("type")
    if isinstance(kind, str):
        result["type"] = [kind, "null"]
    elif isinstance(kind, list) and "null" not in kind:
        result["type"] = [*kind, "null"]
    elif kind is None:
        result = {"anyOf": [result, {"type": "null"}]}
    return result


def _assistant_message(response: Mapping[str, Any]) -> dict[str, Any]:
    output = response.get("output")
    message = output.get("message") if isinstance(output, dict) else None
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise AgentProtocolError("Bedrock response is missing an assistant message")
    content = message.get("content")
    if not isinstance(content, list):
        raise AgentProtocolError("Bedrock assistant message content must be an array")
    return _json_round_trip(message)


def _audit_record(
    response: Mapping[str, Any],
    *,
    provider: str,
    model_id: str,
    region: str,
    invocation: int,
    tool_uses: list[dict[str, Any]],
    message: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = response.get("ResponseMetadata")
    request_id = metadata.get("RequestId") if isinstance(metadata, dict) else None
    text = "\n".join(
        block["text"]
        for block in message.get("content", [])
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
    return {
        "provider": provider,
        "invocation": invocation,
        "model_id": model_id,
        "region": region,
        "status": "complete",
        "request_id": request_id,
        "stop_reason": response.get("stopReason"),
        "usage": _json_round_trip(response.get("usage", {})),
        "metrics": _json_round_trip(response.get("metrics", {})),
        "tool_use_count": len(tool_uses),
        "tool_names": [value.get("name") for value in tool_uses],
        "text": text[:4000],
    }


def _json_round_trip(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise AgentProtocolError(f"Bedrock value is not JSON-compatible: {error}") from error


def _bounded_error(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed[:8000] if collapsed else "no diagnostic output"


_SYSTEM_PROMPT = """You are an untrusted proof-repair planner for Rupicola.
The local controller and Rocq kernel, not you, decide whether a patch is valid.
Use exactly one provided tool in every response; never answer with plain text.
The adapter may accept at most four mutually independent read-only calls if the
runtime batches them, but never batch a stateful tool. Respect the retrieval
budget in the supplied limits. When it is exhausted, propose, check, or finish;
do not request more source. If a checked same-case analogue is available, read
it and adapt it directly instead of exhaustively reconstructing its proof.
Use finish only when no further useful repair is possible. Inspect the live
obligation and retrieve focused local analogues before proposing a patch.
Every proposal must be one complete unified diff against the unchanged base
source. Use exact hunk counts and copy unchanged whitespace verbatim. Prefer
one or two small hunks; never rewrite a whole file or alter comments or layout
unrelated to the proof. Prefer the smallest scope. Never introduce assumptions, admitted
proofs, unsafe casts, filesystem commands, or changes to theorem statements.
After a rejected check, use its structured failure and submit a changed patch.
"""
