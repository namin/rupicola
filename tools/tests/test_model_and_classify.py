from __future__ import annotations

import unittest

from rupicola_llm.classify import classify_goal, classify_snapshot
from rupicola_llm.model import ProofGoal, ProofSnapshot


def goal(
    conclusion: str, *, disposition: str = "focused", goal_id: str = "1"
) -> ProofGoal:
    return ProofGoal(goal_id, (), conclusion, None, disposition)


class FingerprintTests(unittest.TestCase):
    def test_ignores_goal_ids_whitespace_and_evar_numbers(self) -> None:
        first = goal("DEXPR   mem locals ?Goal17 value", goal_id="1")
        second = goal("DEXPR mem\nlocals ?Goal99 value", goal_id="92")
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_snapshot_tracks_actionable_and_auxiliary_goals(self) -> None:
        snapshot = classify_snapshot(
            ProofSnapshot(
                (
                    goal("DEXPR mem locals ?e value"),
                    goal("expr", disposition="shelved", goal_id="2"),
                )
            )
        ).to_dict()
        self.assertEqual(2, snapshot["goal_count"])
        self.assertEqual(1, snapshot["actionable_goal_count"])
        self.assertEqual(1, snapshot["auxiliary_goal_count"])


class ClassificationTests(unittest.TestCase):
    def test_expression(self) -> None:
        self.assertEqual(
            "expression_compilation", classify_goal(goal("DEXPR m l e value")).category
        )

    def test_bounds(self) -> None:
        conclusion = "0 <= byte.unsigned x < 2 ^ width"
        self.assertEqual(
            "representation_or_bounds", classify_goal(goal(conclusion)).category
        )

    def test_semantic_invariant(self) -> None:
        conclusion = "ListArray.fold_left step bs 0 = count_byte_spec bs needle"
        self.assertEqual("semantic_invariant", classify_goal(goal(conclusion)).category)

    def test_locals_transition_wins_over_nested_loop_term(self) -> None:
        conclusion = (
            "map.remove_many (map.put locals key (ranged_for 0 n body r)) vars "
            "= map.put locals key value"
        )
        self.assertEqual(
            "control_flow_or_locals", classify_goal(goal(conclusion)).category
        )

    def test_bare_shelved_expression_is_auxiliary(self) -> None:
        classification = classify_goal(goal("expr", disposition="shelved"))
        self.assertEqual("internal_synthesis_witness", classification.category)
        self.assertFalse(classification.actionable)


if __name__ == "__main__":
    unittest.main()

