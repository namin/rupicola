from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.patches import parse_unified_diff
from rupicola_llm.policy import scope_violations, source_policy_violations


class PolicyTests(unittest.TestCase):
    def test_local_and_project_scopes_differ(self) -> None:
        patch = parse_unified_diff(
            """--- /dev/null
+++ b/src/Rupicola/Generated/Support.v
@@ -0,0 +1 @@
+Lemma support : True.
"""
        )
        target = "src/Rupicola/Examples/Target.v"
        self.assertTrue(scope_violations(patch, target, "local"))
        self.assertFalse(scope_violations(patch, target, "project"))

    def test_rejects_new_assumptions_and_broad_exported_hints(self) -> None:
        with tempfile.TemporaryDirectory() as original_temporary:
            with tempfile.TemporaryDirectory() as candidate_temporary:
                original = Path(original_temporary)
                candidate = Path(candidate_temporary)
                relative = Path("src/Rupicola/Generated/Unsafe.v")
                path = candidate / relative
                path.parent.mkdir(parents=True)
                path.write_text(
                    "Axiom answer : True.\n"
                    "#[export] Hint Extern 10 => exact I : compiler.\n",
                    encoding="utf-8",
                )
                violations = source_policy_violations(
                    original, candidate, (relative.as_posix(),), "project"
                )
        self.assertTrue(any("axiom" in violation for violation in violations))
        self.assertTrue(any("Hint Extern" in violation for violation in violations))

    def test_ignores_policy_words_in_comments_and_strings(self) -> None:
        with tempfile.TemporaryDirectory() as original_temporary:
            with tempfile.TemporaryDirectory() as candidate_temporary:
                original = Path(original_temporary)
                candidate = Path(candidate_temporary)
                relative = Path("src/Rupicola/Generated/Safe.v")
                path = candidate / relative
                path.parent.mkdir(parents=True)
                path.write_text(
                    '(* Never use Admitted. *)\nDefinition message := "Axiom".\n',
                    encoding="utf-8",
                )
                violations = source_policy_violations(
                    original, candidate, (relative.as_posix(),), "project"
                )
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
