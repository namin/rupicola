from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rupicola_llm.runs import RunStore, RunStoreError


class RunStoreTests(unittest.TestCase):
    def test_round_trips_json_and_rejects_traversal_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RunStore(Path(temporary))
            run = store.create("proof_ok")
            run.write_json("run.json", {"status": "created"})
            self.assertEqual({"status": "created"}, store.open(run.run_id).read_json("run.json"))
            with self.assertRaisesRegex(RunStoreError, "invalid run ID"):
                store.open("../outside")


if __name__ == "__main__":
    unittest.main()
