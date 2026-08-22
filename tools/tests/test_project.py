from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from rupicola_llm.project import LoadPath, Project, _parse_project_file


class ProjectTests(unittest.TestCase):
    def test_parses_load_paths_and_expands_arg_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_file = root / "_CoqProject"
            project_file.write_text(
                "-R src/Rupicola Rupicola\n"
                "-arg -w\n"
                "-arg -deprecated-test\n"
                "-Q /tmp/coqutil coqutil\n",
                encoding="utf-8",
            )
            load_paths, args = _parse_project_file(root, project_file)
        self.assertEqual(["Rupicola", "coqutil"], [entry.logical for entry in load_paths])
        self.assertIn("-w", args)
        self.assertIn("-deprecated-test", args)

    def test_reports_concrete_inconsistent_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rupicola = root / "rupicola"
            bedrock = root / "bedrock2"
            (rupicola / "Lib").mkdir(parents=True)
            bedrock.mkdir()
            compiled = rupicola / "Lib" / "Core.vo"
            dependency = bedrock / "ProgramLogic.vo"
            compiled.write_bytes(b"old")
            dependency.write_bytes(b"new")
            os.utime(compiled, (1, 1))
            os.utime(dependency, (2, 2))
            project = Project(
                root=root,
                project_file=root / "_CoqProject",
                load_paths=(
                    LoadPath("-R", rupicola, "Rupicola"),
                    LoadPath("-Q", bedrock, "bedrock2"),
                ),
                rocq_args=(),
                coqidetop="coqidetop",
                rocq="rocq",
            )
            diagnostic = project.inconsistent_assumptions_diagnostic(
                "Compiled library Rupicola.Lib.Core (in file Core.vo) makes "
                "inconsistent assumptions over library bedrock2.ProgramLogic"
            )
        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertEqual("stale_compiled_artifact", diagnostic.kind)
        self.assertTrue(diagnostic.details["compiled_artifact_older"])
        self.assertEqual(str(compiled.resolve()), diagnostic.details["compiled_artifact"]["path"])


if __name__ == "__main__":
    unittest.main()

