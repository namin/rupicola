from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.agent_protocol import (
    InspectObligationAction,
    ReadAction,
    SearchAction,
)
from rupicola_llm.agent_tools import AgentToolError, RepositoryTools


class AgentToolTests(unittest.TestCase):
    def test_search_read_and_inspect_are_bounded_to_disclosed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "Rupicola" / "Lib" / "Rules.v"
            source.parent.mkdir(parents=True)
            source.write_text(
                "Lemma expr_compile_example : True.\nProof. exact I. Qed.\n",
                encoding="utf-8",
            )
            (root / "secret.txt").write_text("secret\n", encoding="utf-8")
            snapshot = {
                "goals": [
                    {
                        "id": "goal-1",
                        "fingerprint": "abc123",
                        "hypotheses": ["  x   :  nat"],
                        "conclusion": "  True   /\\  True ",
                        "evidence": [],
                    }
                ]
            }
            tools = RepositoryTools(root, snapshot)

            search = tools.search(SearchAction("expr_compile_example"))
            self.assertEqual(1, len(search["matches"]))
            self.assertEqual("src/Rupicola/Lib/Rules.v", search["matches"][0]["path"])

            read = tools.read(
                ReadAction("src/Rupicola/Lib/Rules.v", start_line=2, end_line=2)
            )
            self.assertIn("Proof. exact I. Qed.", read["content"])

            inspected = tools.inspect(InspectObligationAction("1", "normalized"))
            self.assertEqual("x : nat", inspected["obligation"]["hypotheses"][0])
            self.assertEqual("True /\\ True", inspected["obligation"]["conclusion"])

            with self.assertRaisesRegex(AgentToolError, "outside the disclosed"):
                tools.read(ReadAction("secret.txt"))


if __name__ == "__main__":
    unittest.main()
