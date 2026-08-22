from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rupicola_llm.model import SourcePhrase
from rupicola_llm.project import Project
from rupicola_llm.rocqide import CoqIdeDriver, render_pp


class PrettyPrinterTests(unittest.TestCase):
    def test_ignores_annotation_name_in_tagged_ppdoc(self) -> None:
        element = ET.fromstring(
            '<ppdoc val="tag"><pair><string>constr.variable</string>'
            '<ppdoc val="string"><string>value</string></ppdoc>'
            "</pair></ppdoc>"
        )
        self.assertEqual("value", render_pp(element))


@unittest.skipUnless(shutil.which("coqidetop"), "coqidetop is not installed")
class CoqIdeIntegrationTests(unittest.TestCase):
    def test_retrieves_a_structured_live_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_file = root / "_CoqProject"
            source_file = root / "Probe.v"
            project_file.write_text("", encoding="utf-8")
            source_file.write_text("Goal True. Proof. Abort.\n", encoding="utf-8")
            project = Project(
                root=root,
                project_file=project_file,
                load_paths=(),
                rocq_args=(),
                coqidetop=shutil.which("coqidetop") or "coqidetop",
                rocq=shutil.which("rocq") or "rocq",
            )
            phrases = (
                SourcePhrase("Goal True.", 0, 10, 1, 1),
                SourcePhrase("Proof.", 11, 17, 1, 1),
            )
            with CoqIdeDriver(project, timeout_seconds=10) as driver:
                snapshot = driver.replay(source_file, phrases)
        self.assertEqual(1, len(snapshot.goals))
        self.assertEqual("focused", snapshot.goals[0].disposition)
        self.assertEqual("True", snapshot.goals[0].conclusion)


if __name__ == "__main__":
    unittest.main()

