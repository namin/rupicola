from __future__ import annotations

import unittest

from rupicola_llm.disclosure import (
    DisclosureError,
    ensure_no_likely_secrets,
    minimize_remote_context,
    scan_for_likely_secrets,
)


class DisclosureTests(unittest.TestCase):
    def test_reports_paths_without_echoing_secret_values(self) -> None:
        value = {
            "safe": "Rocq source",
            "nested": [{"text": "password=supersecretvalue123"}],
        }
        findings = scan_for_likely_secrets(value)
        self.assertEqual(
            [{"kind": "assigned_secret", "path": "$.nested[0].text"}], findings
        )
        with self.assertRaises(DisclosureError) as raised:
            ensure_no_likely_secrets(value)
        self.assertNotIn("supersecretvalue123", str(raised.exception))

    def test_allows_ordinary_proof_terms_and_exit_tokens(self) -> None:
        ensure_no_likely_secrets(
            {
                "conclusion": "ExitToken -> map.remove_many locals keys = expected",
                "source": "Definition token_count := 3.",
            }
        )

    def test_removes_local_machine_paths_from_the_remote_context_copy(self) -> None:
        context = {
            "diagnosis": {
                "project": {
                    "root": "/Users/person/project",
                    "project_file": "/Users/person/project/_CoqProject",
                    "coqidetop": "/Users/person/bin/coqidetop",
                    "rocq_version": "9.1.1",
                    "load_paths": [
                        {
                            "flag": "-R",
                            "logical": "Rupicola",
                            "physical": "/Users/person/project/src/Rupicola",
                        }
                    ],
                }
            }
        }
        minimized, removed = minimize_remote_context(context)
        project = minimized["diagnosis"]["project"]
        self.assertEqual("9.1.1", project["rocq_version"])
        self.assertEqual("Rupicola", project["load_paths"][0]["logical"])
        self.assertNotIn("root", project)
        self.assertNotIn("physical", project["load_paths"][0])
        self.assertEqual(4, len(removed))
        self.assertIn("root", context["diagnosis"]["project"])


if __name__ == "__main__":
    unittest.main()
