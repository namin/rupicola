from __future__ import annotations

import unittest

from rupicola_llm.diagnose import format_human


class HumanFormatTests(unittest.TestCase):
    def test_does_not_call_auxiliary_only_snapshot_complete(self) -> None:
        result = {
            "status": "residuals",
            "target": {"file": "Case.v", "theorem": "case_ok"},
            "snapshot": {
                "goal_count": 1,
                "actionable_goal_count": 0,
                "auxiliary_goal_count": 1,
                "goals": [
                    {
                        "disposition": "shelved",
                        "fingerprint": "1234567890abcdef",
                        "conclusion": "expr",
                        "classification": {
                            "category": "internal_synthesis_witness",
                        },
                        "evidence": [],
                    }
                ],
            },
        }
        output = format_human(result)
        self.assertIn("auxiliary goals remain", output)
        self.assertNotIn("completed this derivation", output)


if __name__ == "__main__":
    unittest.main()
