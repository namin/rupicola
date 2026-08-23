from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.solve import _target_source_integrity


class TargetIntegrityTests(unittest.TestCase):
    ORIGINAL = """Definition meaning := True.
Lemma target : meaning.
Proof.
  compile.
Abort.
"""

    def test_allows_added_import_without_changing_existing_prefix(self) -> None:
        candidate = "Require Import Extra.\n" + self.ORIGINAL.replace(
            "  compile.\nAbort.", "  exact I.\n  compile.\nQed."
        )
        self.assertIsNone(self._compare(candidate))

    def test_rejects_changed_semantic_prefix(self) -> None:
        candidate = self.ORIGINAL.replace("meaning := True", "meaning := False")
        self.assertIn("preceding", self._compare(candidate) or "")

    def test_rejects_changed_target_declaration(self) -> None:
        candidate = self.ORIGINAL.replace("target : meaning", "target : True")
        self.assertIn("declaration", self._compare(candidate) or "")

    def _compare(self, candidate: str) -> str | None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_path = root / "Original.v"
            candidate_path = root / "Candidate.v"
            original_path.write_text(self.ORIGINAL, encoding="utf-8")
            candidate_path.write_text(candidate, encoding="utf-8")
            return _target_source_integrity(original_path, candidate_path, "target")


if __name__ == "__main__":
    unittest.main()
