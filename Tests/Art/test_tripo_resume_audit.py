import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("audit_tripo_resume", Path(__file__).resolve().parents[2] / "Tools/audit_tripo_resume.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ResumeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "RawAssets/Art/Tripo_v01/tripo_raw/Example/v01"
        self.folder.mkdir(parents=True)
        self.model = self.folder / "model.glb"
        self.model.write_bytes(b"frozen model")
        self.record = {"task_id": "original-id", "output_files": [self.model.relative_to(self.root).as_posix()],
                       "sha256": {"model.glb": hashlib.sha256(self.model.read_bytes()).hexdigest()}}
        self.ledger = {"assets": {"Example": {"task_history": [self.record]}}}
        self.write("submission.intent.json", {"approved": True})
        self.write("submission.json", {"task_id": "original-id", "status": "queued"})
        self.write("task.json", {"task_id": "original-id", "status": "success"})

    def write(self, name, data):
        (self.folder / name).write_text(json.dumps(data), encoding="utf-8")

    def test_saved_identity_and_receipt_pass(self):
        report = MODULE.audit(self.root, self.ledger)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["intent_folders_checked"], 1)
        self.assertEqual(report["paid_submissions"], 0)

    def test_corrupt_model_is_not_rebaselined(self):
        self.model.write_bytes(b"changed")
        self.assertEqual(MODULE.audit(self.root, self.ledger)["status"], "failed")

    def test_missing_and_unhashed_models_fail(self):
        self.record["sha256"] = {}
        self.assertEqual(MODULE.audit(self.root, self.ledger)["status"], "failed")
        self.model.unlink()
        self.assertIn("missing", MODULE.audit(self.root, self.ledger)["failures"][0])

    def test_conflicting_ids_fail(self):
        self.write("task.json", {"task_id": "different-id", "status": "success"})
        self.assertEqual(MODULE.audit(self.root, self.ledger)["status"], "failed")

    def test_intent_without_receipt_fails(self):
        (self.folder / "submission.json").unlink()
        (self.folder / "task.json").unlink()
        self.assertEqual(MODULE.audit(self.root, self.ledger)["status"], "failed")

    def test_unrecorded_task_and_outside_path_fail(self):
        self.record["task_id"] = "missing-id"
        self.record["output_files"] = ["outside.glb"]
        report = MODULE.audit(self.root, self.ledger)
        self.assertEqual(len(report["failures"]), 2)


if __name__ == "__main__":
    unittest.main()
