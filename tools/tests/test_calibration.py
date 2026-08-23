from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from rupicola_llm.diagnose import diagnose
from rupicola_llm.solve import solve_with_patch


ROOT = Path(__file__).resolve().parents[2]
RUN_CALIBRATION = os.environ.get("RUPICOLA_LLM_CALIBRATION") == "1"


@unittest.skipUnless(RUN_CALIBRATION, "set RUPICOLA_LLM_CALIBRATION=1")
@unittest.skipUnless(shutil.which("coqidetop"), "coqidetop is not installed")
class CalibrationTests(unittest.TestCase):
    CASES = (
        (
            "src/Rupicola/Examples/LLMByteOrBaseline.v",
            "baseline_byte_or_scalar_br2fn_ok",
            {"expression_compilation": 1, "internal_synthesis_witness": 1},
            1,
        ),
        (
            "src/Rupicola/Examples/LLMCountByteBaseline.v",
            "baseline_count_byte_br2fn_ok",
            {"representation_or_bounds": 1, "semantic_invariant": 1},
            2,
        ),
        (
            "src/Rupicola/Examples/LLMFindByteBaseline.v",
            "baseline_find_byte_br2fn_ok",
            {
                "control_flow_or_locals": 1,
                "representation_or_bounds": 1,
                "semantic_invariant": 1,
            },
            3,
        ),
    )

    def test_expected_residuals(self) -> None:
        for relative, theorem, expected_counts, actionable in self.CASES:
            with self.subTest(file=relative):
                result, exit_code = diagnose(ROOT / relative, theorem, timeout_seconds=30)
                self.assertEqual(0, exit_code, result.get("diagnostics"))
                snapshot = result["snapshot"]
                self.assertEqual(actionable, snapshot["actionable_goal_count"])
                self.assertEqual(expected_counts, snapshot["counts_by_class"])

    def test_fingerprints_are_stable_across_fresh_sessions(self) -> None:
        relative, theorem, _, _ = self.CASES[0]
        first, first_exit = diagnose(ROOT / relative, theorem, timeout_seconds=30)
        second, second_exit = diagnose(ROOT / relative, theorem, timeout_seconds=30)
        self.assertEqual((0, 0), (first_exit, second_exit))
        self.assertEqual(
            first["snapshot"]["fingerprint"], second["snapshot"]["fingerprint"]
        )

    def test_byte_or_candidate_is_verified_without_touching_source(self) -> None:
        target = ROOT / self.CASES[0][0]
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        fixture = ROOT / "tools/tests/fixtures/byte_or_candidate.patch"
        with tempfile.TemporaryDirectory() as temporary:
            result, exit_code = solve_with_patch(
                target,
                self.CASES[0][1],
                fixture,
                scope="project",
                runs_root=Path(temporary) / "runs",
                timeout_seconds=30,
                rationale="deterministic checked-solve acceptance fixture",
            )
            run_directory = Path(result["run_directory"])
            self.assertEqual(0, exit_code, result)
            self.assertEqual("verified", result["status"])
            self.assertTrue((run_directory / "proposal.patch").is_file())
            self.assertTrue((run_directory / "validation.json").is_file())
            self.assertFalse((run_directory / "workspace").exists())
            checks = {
                check["name"]: check["status"]
                for check in result["validation"]["checks"]
            }
            self.assertTrue(checks)
            self.assertEqual({"passed"}, set(checks.values()))
        after = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_unsafe_candidate_is_rejected_before_compilation(self) -> None:
        target = ROOT / self.CASES[0][0]
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            candidate = temporary_path / "unsafe.patch"
            candidate.write_text(
                "--- /dev/null\n"
                "+++ b/src/Rupicola/Generated/Unsafe.v\n"
                "@@ -0,0 +1 @@\n"
                "+Axiom escape : True.\n",
                encoding="utf-8",
            )
            result, exit_code = solve_with_patch(
                target,
                self.CASES[0][1],
                candidate,
                scope="project",
                runs_root=temporary_path / "runs",
                timeout_seconds=30,
            )
            self.assertEqual(4, exit_code)
            self.assertEqual("rejected", result["status"])
            checks = {
                check["name"]: check["status"]
                for check in result["validation"]["checks"]
            }
            self.assertEqual("failed", checks["source_policy"])
            self.assertEqual("skipped", checks["candidate_compile"])
            self.assertEqual("passed", checks["source_tree_unchanged"])


if __name__ == "__main__":
    unittest.main()
