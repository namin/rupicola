from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest

from rupicola_llm.diagnose import diagnose


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


if __name__ == "__main__":
    unittest.main()

