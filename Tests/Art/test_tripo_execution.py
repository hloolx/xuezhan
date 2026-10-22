import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("refresh_tripo_execution", ROOT / "Tools/refresh_tripo_execution.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AuxiliaryReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.art = Path(self.directory.name)

    def receipt(self, directory, task_id="free-check", kind="animate_prerigcheck", status="success", credits=0):
        path = self.art / "reviews" / directory / "task.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"task_id": task_id, "type": kind, "status": status,
                                    "credits_consumed": credits}), encoding="utf-8")

    def test_free_check_is_recorded_without_model_or_spend(self):
        self.receipt("new_check")
        records = MODULE.collect_auxiliary_tasks(self.art, {})
        self.assertEqual(0, records["free-check"]["credits_charged"])
        self.assertEqual("reviews/new_check/task.json", records["free-check"]["evidence_file"])

    def test_image_probe_and_nested_checks_are_discovered(self):
        self.receipt("probe", "probe", "image_to_multiview", credits=10)
        self.receipt("nested/check")
        self.assertEqual(10, sum(record["credits_charged"] for record in MODULE.collect_auxiliary_tasks(self.art, {}).values()))

    def test_duplicate_model_ids_and_nonauxiliary_types_are_excluded(self):
        self.receipt("duplicate")
        self.receipt("mesh", "mesh", "multiview_to_model", credits=100)
        self.assertEqual({}, MODULE.collect_auxiliary_tasks(self.art, {"free-check": {}}))

    def test_pending_cost_is_not_confirmed_spend(self):
        self.receipt("pending", status="running", credits=10)
        self.assertIsNone(MODULE.collect_auxiliary_tasks(self.art, {})["free-check"]["credits_charged"])

    def test_duplicate_final_is_counted_once_and_conflicts_fail(self):
        self.receipt("first")
        self.receipt("second")
        self.assertEqual(1, len(MODULE.collect_auxiliary_tasks(self.art, {})))
        self.receipt("third", credits=10)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            MODULE.collect_auxiliary_tasks(self.art, {})


if __name__ == "__main__":
    unittest.main()
