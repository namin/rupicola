from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.classify import classify_snapshot
from rupicola_llm.model import ProofGoal, ProofSnapshot
from rupicola_llm.project import LoadPath, Project
from rupicola_llm.retrieve import retrieve_snapshot


class RetrievalTests(unittest.TestCase):
    def test_prefers_checked_invariant_pattern_over_spec_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "src" / "Rupicola"
            examples = source_root / "Examples"
            examples.mkdir(parents=True)
            target = examples / "CountBaseline.v"
            target.write_text("", encoding="utf-8")
            (examples / "CountSpec.v").write_text(
                "Fixpoint count_byte_spec (bs : list nat) : nat := 0.\n",
                encoding="utf-8",
            )
            (examples / "CountProof.v").write_text(
                "Lemma count_byte_fold_acc bs acc :\n"
                "  List.fold_left plus bs acc = acc + count_byte_spec bs.\n"
                "Proof. Abort.\n",
                encoding="utf-8",
            )
            (source_root / "Loops.v").write_text(
                "Lemma copying_fold_left_as_ranged_for bs acc :\n"
                "  List.fold_left plus bs acc = acc.\n"
                "Proof. Abort.\n",
                encoding="utf-8",
            )
            project = Project(
                root=root,
                project_file=root / "_CoqProject",
                load_paths=(LoadPath("-R", source_root, "Rupicola"),),
                rocq_args=(),
                coqidetop="coqidetop",
                rocq="rocq",
            )
            snapshot = classify_snapshot(
                ProofSnapshot(
                    (
                        ProofGoal(
                            "1",
                            (),
                            "List.fold_left step bs 0 = count_byte_spec bs",
                            None,
                            "focused",
                        ),
                    )
                )
            )
            enriched = retrieve_snapshot(project, target, snapshot)
        self.assertTrue(enriched.goals[0].evidence)
        self.assertEqual("count_byte_fold_acc", enriched.goals[0].evidence[0].declaration)


if __name__ == "__main__":
    unittest.main()
