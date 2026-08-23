from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import unittest
from unittest.mock import patch

from rupicola_llm.agent_protocol import (
    AgentProtocolError,
    FinishAction,
    ReadAction,
    SearchAction,
    TOOL_SPECS,
)
from rupicola_llm.bedrock import (
    AwsCliConverseTransport,
    BedrockError,
    BedrockProvider,
    resolve_aws_region,
)
from rupicola_llm.disclosure import DisclosureError


class _FakeTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def converse(self, request: object) -> dict[str, object]:
        self.requests.append(json.loads(json.dumps(request)))
        return self.responses.pop(0)


class BedrockProviderTests(unittest.TestCase):
    def test_maps_typed_tools_and_round_trips_controller_observation(self) -> None:
        transport = _FakeTransport(
            [
                self._response(
                    "call-1",
                    "search",
                    {
                        "query": "expr_compile_byte_or",
                        "path": None,
                        "max_results": None,
                    },
                    request_id="request-1",
                ),
                self._response(
                    "call-2",
                    "finish",
                    {"summary": "retrieval complete"},
                    request_id="request-2",
                ),
            ]
        )
        provider = self._provider(transport)
        context = self._context()
        provider.start(context, TOOL_SPECS)

        first = provider.next_action({"status": "ok", "event": "context_ready"})
        self.assertIsInstance(first, SearchAction)
        self.assertEqual("src/Rupicola", first.path)
        self.assertEqual(10, first.max_results)
        first_audit = provider.take_audit_record()
        self.assertEqual("request-1", first_audit["request_id"])
        self.assertEqual(1, first_audit["usage"]["inputTokens"])
        self.assertTrue(provider.metadata.model_invoked)

        request = transport.requests[0]
        self.assertEqual("us.anthropic.claude-sonnet-4-6", request["modelId"])
        self.assertNotIn("temperature", request["inferenceConfig"])
        self.assertNotIn("/Users/test", request["messages"][0]["content"][0]["text"])
        self.assertEqual({"any": {}}, request["toolConfig"]["toolChoice"])
        search_tool = next(
            tool["toolSpec"]
            for tool in request["toolConfig"]["tools"]
            if tool["toolSpec"]["name"] == "search"
        )
        self.assertTrue(search_tool["strict"])
        query_schema = search_tool["inputSchema"]["json"]["properties"]["query"]
        search_schema = search_tool["inputSchema"]["json"]
        self.assertNotIn("minLength", query_schema)
        self.assertNotIn("maxLength", query_schema)
        self.assertEqual(
            {"query", "path", "max_results"}, set(search_schema["required"])
        )
        self.assertEqual(
            ["string", "null"], search_schema["properties"]["path"]["type"]
        )
        self.assertFalse(search_schema["additionalProperties"])

        observation = {
            "status": "ok",
            "event": "search_complete",
            "matches": [{"path": "src/Rupicola/Lib/Api.v", "line": 1}],
        }
        second = provider.next_action(observation)
        self.assertIsInstance(second, FinishAction)
        self.assertEqual(
            {
                "invocations": 2,
                "tokens": {"inputTokens": 2, "outputTokens": 4, "totalTokens": 6},
                "model_latency_ms": 8,
            },
            provider.usage_summary(),
        )
        self.assertEqual(
            64, len(provider.metadata.configuration["system_prompt_sha256"])
        )
        tool_result = transport.requests[1]["messages"][-1]["content"][0][
            "toolResult"
        ]
        self.assertEqual("call-1", tool_result["toolUseId"])
        self.assertEqual("success", tool_result["status"])
        self.assertEqual(observation, tool_result["content"][0]["json"])
        manifest = provider.context_manifest()
        self.assertTrue(manifest["confirmed"])
        self.assertEqual(
            "not_inspected_by_client", manifest["account_invocation_logging"]
        )
        self.assertIn(
            "$.diagnosis.project.root",
            manifest["context_minimization"]["removed_fields"],
        )
        self.assertEqual("src/Rupicola/Case.v", manifest["initial_context"]["target"])

    def test_returns_invalid_tool_input_to_bedrock_as_an_error_result(self) -> None:
        transport = _FakeTransport(
            [
                self._response(
                    "bad-call",
                    "search",
                    {"query": "needle", "command": "make"},
                ),
                self._response(
                    "finish-call",
                    "finish",
                    {"summary": "corrected after protocol error"},
                ),
            ]
        )
        provider = self._provider(transport)
        provider.start(self._context(), TOOL_SPECS)
        with self.assertRaisesRegex(AgentProtocolError, "unexpected fields"):
            provider.next_action({"status": "ok"})
        corrected = provider.next_action(
            {
                "status": "error",
                "error": "invalid_action",
                "message": "unexpected fields: command",
            }
        )
        self.assertIsInstance(corrected, FinishAction)
        result = transport.requests[1]["messages"][-1]["content"][0]["toolResult"]
        self.assertEqual("bad-call", result["toolUseId"])
        self.assertEqual("error", result["status"])

    def test_non_strict_mode_preserves_optional_tool_properties(self) -> None:
        transport = _FakeTransport(
            [self._response("finish-call", "finish", {"summary": "done"})]
        )
        provider = BedrockProvider(
            transport,
            model_id="model",
            region="us-east-1",
            profile="default",
            allow_remote_source=True,
            strict_tools=False,
        )
        provider.start(self._context(), TOOL_SPECS)
        self.assertIsInstance(provider.next_action({"status": "ok"}), FinishAction)
        search = next(
            tool["toolSpec"]
            for tool in transport.requests[0]["toolConfig"]["tools"]
            if tool["toolSpec"]["name"] == "search"
        )
        self.assertNotIn("strict", search)
        self.assertEqual(
            ["query"], search["inputSchema"]["json"]["required"]
        )
        self.assertEqual(
            "string",
            search["inputSchema"]["json"]["properties"]["path"]["type"],
        )

    def test_serializes_batched_read_only_tools_and_returns_all_results(self) -> None:
        transport = _FakeTransport(
            [
                self._response_many(
                    [
                        ("read-1", "read", {"path": "src/Rupicola/A.v"}),
                        ("read-2", "read", {"path": "src/Rupicola/B.v"}),
                    ]
                ),
                self._response(
                    "finish-call", "finish", {"summary": "both files inspected"}
                ),
            ]
        )
        provider = self._provider(transport)
        provider.start(self._context(), TOOL_SPECS)

        first = provider.next_action({"status": "ok"})
        self.assertIsInstance(first, ReadAction)
        self.assertEqual("src/Rupicola/A.v", first.path)
        self.assertEqual(2, provider.take_audit_record()["tool_use_count"])

        second = provider.next_action({"status": "ok", "event": "first_read"})
        self.assertIsInstance(second, ReadAction)
        self.assertEqual("src/Rupicola/B.v", second.path)
        self.assertEqual(1, len(transport.requests))
        queued_audit = provider.take_audit_record()
        self.assertEqual("batched_tool_use", queued_audit["status"])
        self.assertEqual(2, queued_audit["batch_position"])

        finish = provider.next_action({"status": "ok", "event": "second_read"})
        self.assertIsInstance(finish, FinishAction)
        results = transport.requests[1]["messages"][-1]["content"]
        self.assertEqual(["read-1", "read-2"], [
            item["toolResult"]["toolUseId"] for item in results
        ])
        self.assertEqual(
            ["first_read", "second_read"],
            [item["toolResult"]["content"][0]["json"]["event"] for item in results],
        )

    def test_rejects_a_batch_containing_a_stateful_tool(self) -> None:
        transport = _FakeTransport(
            [
                self._response_many(
                    [
                        ("read-call", "read", {"path": "src/Rupicola/A.v"}),
                        ("check-call", "check", {}),
                    ]
                ),
                self._response(
                    "finish-call", "finish", {"summary": "corrected batch"}
                ),
            ]
        )
        provider = self._provider(transport)
        provider.start(self._context(), TOOL_SPECS)
        with self.assertRaisesRegex(AgentProtocolError, "read-only"):
            provider.next_action({"status": "ok"})

        finish = provider.next_action(
            {"status": "error", "error": "invalid_action"}
        )
        self.assertIsInstance(finish, FinishAction)
        results = transport.requests[1]["messages"][-1]["content"]
        self.assertEqual(2, len(results))
        self.assertTrue(all(item["toolResult"]["status"] == "error" for item in results))

    def test_rejects_an_oversized_read_only_batch(self) -> None:
        calls = [
            (f"read-{number}", "read", {"path": f"src/Rupicola/{number}.v"})
            for number in range(5)
        ]
        transport = _FakeTransport(
            [
                self._response_many(calls),
                self._response(
                    "finish-call", "finish", {"summary": "corrected batch"}
                ),
            ]
        )
        provider = self._provider(transport)
        provider.start(self._context(), TOOL_SPECS)
        with self.assertRaisesRegex(AgentProtocolError, "per-turn limit"):
            provider.next_action({"status": "ok"})

        finish = provider.next_action(
            {"status": "error", "error": "invalid_action"}
        )
        self.assertIsInstance(finish, FinishAction)
        results = transport.requests[1]["messages"][-1]["content"]
        self.assertEqual(5, len(results))

    def test_blocks_unconfirmed_or_secret_bearing_remote_context(self) -> None:
        provider = BedrockProvider(
            _FakeTransport([]),
            model_id="model",
            region="us-east-1",
            profile="default",
            allow_remote_source=False,
        )
        with self.assertRaisesRegex(DisclosureError, "explicit"):
            provider.start(self._context(), TOOL_SPECS)

        provider = self._provider(_FakeTransport([]))
        context = self._context()
        context["diagnosis"]["snapshot"]["goals"][0]["conclusion"] = (
            "credential AKIAABCDEFGHIJKLMNOP"
        )
        with self.assertRaisesRegex(DisclosureError, "aws_access_key"):
            provider.start(context, TOOL_SPECS)

    def test_blocks_secret_bearing_tool_results_before_the_next_request(self) -> None:
        transport = _FakeTransport(
            [
                self._response("search-call", "search", {"query": "needle"}),
                self._response("finish-call", "finish", {"summary": "done"}),
            ]
        )
        provider = self._provider(transport)
        provider.start(self._context(), TOOL_SPECS)
        self.assertIsInstance(provider.next_action({"status": "ok"}), SearchAction)
        with self.assertRaisesRegex(DisclosureError, "aws_access_key"):
            provider.next_action(
                {"status": "ok", "content": "AKIAABCDEFGHIJKLMNOP"}
            )
        self.assertEqual(1, len(transport.requests))

    def test_aws_cli_transport_uses_fixed_arguments_and_removes_request_file(self) -> None:
        response = self._response("call-1", "finish", {"summary": "done"})

        class Process:
            returncode = 0
            pid = 123

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                del timeout
                return json.dumps(response), ""

        commands: list[list[str]] = []

        def popen(command: list[str], **kwargs: object) -> Process:
            del kwargs
            commands.append(command)
            return Process()

        transport = AwsCliConverseTransport(
            region="us-east-1", profile="default", timeout_seconds=5
        )
        with (
            patch("rupicola_llm.bedrock.shutil.which", return_value="/opt/aws"),
            patch("rupicola_llm.bedrock.subprocess.Popen", side_effect=popen),
        ):
            actual = transport.converse({"modelId": "model", "messages": []})
        self.assertEqual(response, actual)
        command = commands[0]
        self.assertEqual(["/opt/aws", "bedrock-runtime", "converse"], command[:3])
        self.assertIn("default", command)
        request_argument = command[command.index("--cli-input-json") + 1]
        self.assertTrue(request_argument.startswith("file://"))
        self.assertFalse(Path(request_argument.removeprefix("file://")).exists())

    def test_resolves_region_from_environment_before_profile(self) -> None:
        with patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=True):
            self.assertEqual(
                "us-west-2", resolve_aws_region(None, profile="default")
            )

    def test_aws_cli_transport_kills_a_timed_out_process_and_cleans_up(self) -> None:
        class Process:
            returncode = None
            pid = 4321
            calls = 0

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired("aws", timeout)
                return "", ""

        command: list[str] = []

        def popen(arguments: list[str], **kwargs: object) -> Process:
            del kwargs
            command.extend(arguments)
            return Process()

        transport = AwsCliConverseTransport(
            region="us-east-1", profile="default", timeout_seconds=5
        )
        with (
            patch("rupicola_llm.bedrock.shutil.which", return_value="/opt/aws"),
            patch("rupicola_llm.bedrock.subprocess.Popen", side_effect=popen),
            patch("rupicola_llm.bedrock.os.killpg") as kill,
        ):
            with self.assertRaisesRegex(BedrockError, "exceeded 5 seconds"):
                transport.converse({"modelId": "model", "messages": []})
        kill.assert_called_once_with(4321, signal.SIGKILL)
        request = command[command.index("--cli-input-json") + 1]
        self.assertFalse(Path(request.removeprefix("file://")).exists())

    def test_aws_cli_transport_rejects_invalid_timeouts(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(BedrockError, "positive and finite"):
                    AwsCliConverseTransport("us-east-1", timeout_seconds=timeout)

    @staticmethod
    def _provider(transport: _FakeTransport) -> BedrockProvider:
        return BedrockProvider(
            transport,
            model_id="us.anthropic.claude-sonnet-4-6",
            region="us-east-1",
            profile="default",
            allow_remote_source=True,
            max_tokens=1024,
        )

    @staticmethod
    def _context() -> dict[str, object]:
        return {
            "schema_version": "0.1",
            "diagnosis": {
                "target": {"file": "src/Rupicola/Case.v"},
                "project": {
                    "root": "/Users/test/project",
                    "project_file": "/Users/test/project/_CoqProject",
                    "coqidetop": "/Users/test/bin/coqidetop",
                    "load_paths": [
                        {
                            "flag": "-R",
                            "logical": "Rupicola",
                            "physical": "/Users/test/project/src/Rupicola",
                        }
                    ],
                },
                "snapshot": {
                    "goals": [
                        {
                            "conclusion": "True",
                            "evidence": [
                                {"path": "src/Rupicola/Lib/Api.v", "line": 1}
                            ],
                        }
                    ]
                },
            },
            "permissions": {"readable_roots": ["src/Rupicola"]},
        }

    @staticmethod
    def _response(
        tool_id: str,
        name: str,
        arguments: dict[str, object],
        *,
        request_id: str = "request",
    ) -> dict[str, object]:
        return BedrockProviderTests._response_many(
            [(tool_id, name, arguments)], request_id=request_id
        )

    @staticmethod
    def _response_many(
        calls: list[tuple[str, str, dict[str, object]]],
        *,
        request_id: str = "request",
    ) -> dict[str, object]:
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Using bounded tools."},
                        *[
                            {
                                "toolUse": {
                                    "toolUseId": tool_id,
                                    "name": name,
                                    "input": arguments,
                                }
                            }
                            for tool_id, name, arguments in calls
                        ],
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
            "metrics": {"latencyMs": 4},
            "ResponseMetadata": {"RequestId": request_id},
        }


if __name__ == "__main__":
    unittest.main()
