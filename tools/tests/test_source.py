from __future__ import annotations

import unittest

from rupicola_llm.source import SourcePlanError, build_replay_plan, split_phrases


class SourceScannerTests(unittest.TestCase):
    def test_splits_comments_strings_qualified_names_and_dot_tactical(self) -> None:
        source = '''
(* An outer comment. (* A nested sentence. *) *)
Require Import A.B.
Definition dotted := "a.b".
Ltac dots := first [ idtac.. | idtac ].
'''
        phrases = split_phrases(source)
        self.assertEqual(3, len(phrases))
        self.assertIn("Require Import A.B.", phrases[0].text)
        self.assertIn('"a.b"', phrases[1].text)
        self.assertIn("idtac..", phrases[2].text)

    def test_builds_plan_for_derived_theorem(self) -> None:
        source = '''
Require Import A.
Derive generated in (definition) as generated_ok.
Proof.
  intros; compile_setup; repeat repeat compile_step.
  fail "not part of replay".
Abort.
'''
        plan = build_replay_plan("Case.v", source, "generated_ok")
        self.assertEqual(1, plan.declaration_index)
        self.assertIn("compile_setup", plan.stop_phrase.text)
        self.assertNotIn("not part of replay", "".join(p.text for p in plan.phrases))

    def test_builds_plan_for_ordinary_theorem_at_explicit_line(self) -> None:
        source = """Lemma answer : True.
Proof.
  idtac.
  compile_step.
Abort.
"""
        plan = build_replay_plan("Case.v", source, "answer", through_line=3)
        self.assertIn("idtac", plan.stop_phrase.text)

    def test_reports_missing_compile_marker(self) -> None:
        source = "Lemma answer : True. Proof. exact I. Qed."
        with self.assertRaisesRegex(SourcePlanError, "no compile tactic"):
            build_replay_plan("Case.v", source, "answer")

    def test_reports_unterminated_comment(self) -> None:
        with self.assertRaisesRegex(SourcePlanError, "unterminated Rocq comment"):
            split_phrases("(* never closed")


if __name__ == "__main__":
    unittest.main()
