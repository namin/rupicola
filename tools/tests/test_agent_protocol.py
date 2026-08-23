from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from rupicola_llm.agent_protocol import (
    AgentProtocolError,
    ProposePatchAction,
    ScriptedProvider,
    TOOL_SPECS,
    parse_action,
)


class AgentProtocolTests(unittest.TestCase):
    def test_declares_the_seven_bounded_tools(self) -> None:
        self.assertEqual(
            {
                "search",
                "read",
                "inspect_obligation",
                "propose_patch",
                "check",
                "revert_candidate",
                "finish",
            },
            {tool.name for tool in TOOL_SPECS},
        )
        self.assertTrue(
            all(
                tool.input_schema.get("additionalProperties") is False
                for tool in TOOL_SPECS
            )
        )

    def test_rejects_untyped_fields_and_unsafe_paths(self) -> None:
        with self.assertRaisesRegex(AgentProtocolError, "unexpected fields"):
            parse_action(
                {
                    "tool": "check",
                    "arguments": {"mode": "fast", "command": "make"},
                }
            )
        with self.assertRaisesRegex(AgentProtocolError, "safe project-relative"):
            parse_action(
                {
                    "tool": "read",
                    "arguments": {"path": "../secret", "start_line": 1},
                }
            )
        with self.assertRaisesRegex(AgentProtocolError, "limited to 200 lines"):
            parse_action(
                {
                    "tool": "read",
                    "arguments": {
                        "path": "src/Rupicola/Case.v",
                        "start_line": 1,
                        "end_line": 201,
                    },
                }
            )
        with self.assertRaisesRegex(AgentProtocolError, "valid UTF-8"):
            parse_action(
                {
                    "tool": "finish",
                    "arguments": {"summary": "invalid surrogate: \ud800"},
                }
            )

    def test_scripted_provider_expands_a_local_patch_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "candidate.patch").write_text(
                "--- a/Case.v\n+++ b/Case.v\n@@ -1 +1 @@\n-old\n+new\n",
                encoding="utf-8",
            )
            (root / "agent.json").write_text(
                json.dumps(
                    {
                        "schema_version": "0.1",
                        "provider": "fixture",
                        "model": "deterministic",
                        "actions": [
                            {
                                "tool": "propose_patch",
                                "arguments": {
                                    "patch_file": "candidate.patch",
                                    "rationale": "exercise the provider adapter",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            provider = ScriptedProvider.load(root / "agent.json")
            provider.start({}, TOOL_SPECS)
            action = provider.next_action({})
        self.assertIsInstance(action, ProposePatchAction)
        assert isinstance(action, ProposePatchAction)
        self.assertIn("+new", action.unified_diff)
        self.assertEqual("fixture", provider.metadata.provider)
        self.assertFalse(provider.metadata.model_invoked)


if __name__ == "__main__":
    unittest.main()
