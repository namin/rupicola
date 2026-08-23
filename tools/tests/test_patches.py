from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.patches import PatchError, apply_unified_diff, parse_unified_diff


class PatchTests(unittest.TestCase):
    PATCH = """diff --git a/Proof.v b/Proof.v
index 1111111..2222222 100644
--- a/Proof.v
+++ b/Proof.v
@@ -1,2 +1,2 @@
 Lemma proof : True.
-Proof. Abort.
+Proof. exact I. Qed.
diff --git a/Support.v b/Support.v
new file mode 100644
--- /dev/null
+++ b/Support.v
@@ -0,0 +1 @@
+Lemma support : True.
"""

    def test_applies_modification_and_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Proof.v").write_text(
                "Lemma proof : True.\nProof. Abort.\n", encoding="utf-8"
            )
            parsed = parse_unified_diff(self.PATCH)
            written = apply_unified_diff(parsed, root)
            self.assertEqual(2, len(written))
            self.assertIn("exact I", (root / "Proof.v").read_text(encoding="utf-8"))
            self.assertEqual(
                "Lemma support : True.\n",
                (root / "Support.v").read_text(encoding="utf-8"),
            )

    def test_rejects_traversal(self) -> None:
        patch = """--- a/../outside.v
+++ b/../outside.v
@@ -0,0 +1 @@
+bad
"""
        with self.assertRaisesRegex(PatchError, "unsafe patch path"):
            parse_unified_diff(patch)

    def test_rejects_a_hunk_that_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Proof.v").write_text("different\n", encoding="utf-8")
            parsed = parse_unified_diff(
                """--- a/Proof.v
+++ b/Proof.v
@@ -1 +1 @@
-expected
+replacement
"""
            )
            with self.assertRaisesRegex(PatchError, "does not apply"):
                apply_unified_diff(parsed, root)

    def test_rejects_mode_changes(self) -> None:
        patch = """diff --git a/Proof.v b/Proof.v
old mode 100644
new mode 100755
--- a/Proof.v
+++ b/Proof.v
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaisesRegex(PatchError, "mode changes"):
            parse_unified_diff(patch)


if __name__ == "__main__":
    unittest.main()
