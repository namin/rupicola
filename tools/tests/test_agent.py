from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from rupicola_llm.agent import _accept_proposal, solve_with_agent
from rupicola_llm.agent_protocol import (
    CheckAction,
    InspectObligationAction,
    ProposePatchAction,
    ProviderMetadata,
    ReadAction,
    SearchAction,
)
from rupicola_llm.runs import RunStore
from rupicola_llm.solve import format_show_human, load_run


class _QueueProvider:
    metadata = ProviderMetadata("test-provider", "queue", False, True)

    def __init__(self, actions: list[object]) -> None:
        self.actions = actions
        self.observations: list[dict[str, object]] = []
        self.context = None
        self.tools = ()

    def start(self, context: object, tools: tuple[object, ...]) -> None:
        self.context = context
        self.tools = tools

    def next_action(self, observation: dict[str, object]) -> object:
        self.observations.append(observation)
        return self.actions.pop(0)


class AgentControllerTests(unittest.TestCase):
    PATCH_ONE = (
        "--- a/src/Rupicola/Case.v\n"
        "+++ b/src/Rupicola/Case.v\n"
        "@@ -1 +1 @@\n"
        "-Abort.\n"
        "+Axiom escape : True.\n"
    )
    PATCH_TWO = (
        "--- a/src/Rupicola/Case.v\n"
        "+++ b/src/Rupicola/Case.v\n"
        "@@ -1 +1 @@\n"
        "-Abort.\n"
        "+Qed.\n"
    )

    def test_does_not_restage_a_known_failed_patch_digest(self) -> None:
        action = ProposePatchAction(self.PATCH_TWO, "first version")
        with tempfile.TemporaryDirectory() as temporary:
            run = RunStore(Path(temporary)).create("case_ok")
            first, first_observation = _accept_proposal(
                action,
                run,
                "src/Rupicola/Case.v",
                "local",
                1,
                set(),
            )
            self.assertEqual("ok", first_observation["status"])
            assert first is not None
            repeated, repeated_observation = _accept_proposal(
                action,
                run,
                "src/Rupicola/Case.v",
                "local",
                2,
                {first.sha256},
            )
            self.assertIsNone(repeated)
            self.assertEqual("repeated_failed_digest", repeated_observation["error"])
            self.assertTrue((run.path / "proposals/proposal-002.patch").is_file())

    def test_repairs_after_rejection_and_selects_verified_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "src" / "Rupicola" / "Case.v"
            target.parent.mkdir(parents=True)
            target.write_text("Abort.\n", encoding="utf-8")
            project = SimpleNamespace(
                root=root,
                metadata=lambda: {
                    "root": str(root),
                    "root_commit": "test",
                    "submodules": {},
                },
            )
            diagnosis = {
                "schema_version": "0.1",
                "status": "residuals",
                "project": project.metadata(),
                "target": {"file": "src/Rupicola/Case.v", "theorem": "case_ok"},
                "replay": {},
                "snapshot": {
                    "goal_count": 1,
                    "actionable_goal_count": 1,
                    "goals": [
                        {
                            "id": "goal-1",
                            "fingerprint": "initial-goal",
                            "hypotheses": [],
                            "conclusion": "True",
                            "classification": {"actionable": True},
                            "evidence": [],
                        }
                    ],
                },
                "diagnostics": [],
            }
            rejected = self._check_result(
                "child-rejected", "rejected", None, "source_policy", "failed"
            )
            verified = self._check_result(
                "child-verified", "verified", 0, "source_policy", "passed"
            )
            provider = _QueueProvider(
                [
                    SearchAction("Abort", max_results=2),
                    ReadAction("src/Rupicola/Case.v", 1, 1),
                    InspectObligationAction("1"),
                    ProposePatchAction(self.PATCH_ONE, "unsafe first attempt"),
                    CheckAction("fast"),
                    ProposePatchAction(self.PATCH_TWO, "repair after policy rejection"),
                    CheckAction("final"),
                ]
            )

            with (
                patch("rupicola_llm.agent.Project.discover", return_value=project),
                patch("rupicola_llm.agent.diagnose", return_value=(diagnosis, 0)),
                patch(
                    "rupicola_llm.agent.solve_with_patch",
                    side_effect=[(rejected, 4), (verified, 0)],
                ) as checker,
                patch("rupicola_llm.agent._worktree_fingerprint", return_value="same"),
            ):
                result, exit_code = solve_with_agent(
                    target,
                    "case_ok",
                    provider,
                    scope="local",
                    runs_root=root / "runs",
                    timeout_seconds=5,
                    max_actions=8,
                    max_checks=2,
                    wall_seconds=30,
                )

            self.assertEqual(0, exit_code, result)
            self.assertEqual("verified", result["status"])
            self.assertEqual(2, checker.call_count)
            self.assertEqual(7, result["agent"]["actions_used"])
            self.assertEqual(2, result["agent"]["checks_used"])
            self.assertTrue(provider.observations[5]["candidate_reverted"])

            run = Path(result["run_directory"])
            self.assertEqual(self.PATCH_TWO, (run / "proposal.patch").read_text())
            events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
            attempts = [
                json.loads(line) for line in (run / "attempts.jsonl").read_text().splitlines()
            ]
            self.assertEqual(7, len(events))
            self.assertEqual(2, len(attempts))
            self.assertNotIn("unified_diff", events[3]["action"]["arguments"])
            self.assertEqual("child-verified", attempts[1]["child_run_id"])
            loaded = load_run(RunStore(root / "runs"), result["run_id"])
            self.assertEqual("agent_controller", loaded["run"]["kind"])
            self.assertIn("agent_controller", format_show_human(loaded))

    @staticmethod
    def _check_result(
        run_id: str,
        status: str,
        final_actionable: int | None,
        check_name: str,
        check_status: str,
    ) -> dict[str, object]:
        return {
            "schema_version": "0.1",
            "run_id": run_id,
            "status": status,
            "run_directory": f"/tmp/{run_id}",
            "proposal": f"/tmp/{run_id}/proposal.patch",
            "validation": {
                "schema_version": "0.1",
                "status": status,
                "checks": [
                    {
                        "name": check_name,
                        "status": check_status,
                        "summary": f"{check_name} {check_status}",
                        "details": {},
                    }
                ],
                "residual_delta": {
                    "initial_actionable": 1,
                    "final_actionable": final_actionable,
                    "closed_fingerprints": [],
                    "opened_fingerprints": [],
                },
            },
        }


if __name__ == "__main__":
    unittest.main()
