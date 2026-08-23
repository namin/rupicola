from __future__ import annotations

from contextlib import redirect_stdout
import io
import unittest

from rupicola_llm.cli import main


class CliTests(unittest.TestCase):
    def test_bedrock_requires_explicit_source_disclosure_confirmation(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "solve",
                    "Case.v",
                    "--theorem",
                    "case_ok",
                    "--provider",
                    "bedrock",
                    "--model-id",
                    "model",
                ]
            )
        self.assertEqual(2, exit_code)
        self.assertIn("--allow-remote-source", output.getvalue())

    def test_bedrock_requires_an_explicit_model_id(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "solve",
                    "Case.v",
                    "--theorem",
                    "case_ok",
                    "--provider",
                    "bedrock",
                    "--allow-remote-source",
                ]
            )
        self.assertEqual(2, exit_code)
        self.assertIn("--model-id is required", output.getvalue())


if __name__ == "__main__":
    unittest.main()
