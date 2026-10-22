"""Offline Base_Stone preparation guards; no model, Blender, UE or network use."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location("base_stone_under_test", ROOT / "Tools/base_stone_prepare.py")
runner = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(runner)


class BaseStonePreparationTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(runner.DEFAULT_SPEC.read_text(encoding="utf-8"))

    def test_contract_is_valid(self):
        runner.validate_contract(self.spec)

    def test_source_pending_does_not_invent_input(self):
        self.spec["source"] = None
        result = runner.validate_inputs(self.spec)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "waiting_for_real_download_no_input_fabricated")

    def test_execute_pending_fails_before_blender_import(self):
        with self.assertRaisesRegex(ValueError, "Preparation blocked"):
            runner.execute(self.spec, {"ready": False, "status": "waiting"}, False, "CPU")

    def test_do_not_accept_another_asset(self):
        self.spec["asset_id"] = "Env_Pine"
        with self.assertRaises(ValueError):
            runner.validate_contract(self.spec)

    def test_do_not_claim_final_origin(self):
        self.spec["normalization"]["origin_is_gameplay_final"] = True
        with self.assertRaises(ValueError):
            runner.validate_contract(self.spec)

    def test_do_not_raise_compute_limits(self):
        for field, value in [("threads", 4), ("resolution", 1024), ("samples", 24)]:
            spec = copy.deepcopy(self.spec)
            spec["review"][field] = value
            with self.assertRaises(ValueError):
                runner.validate_contract(spec)

    def test_do_not_register_runtime(self):
        self.spec["import_policy"]["runtime_registration"] = True
        with self.assertRaises(ValueError):
            runner.validate_contract(self.spec)

    def test_path_cannot_escape_asset(self):
        with self.assertRaises(ValueError):
            runner.resolve_inside("RawAssets/Art/Tripo_v01/tripo_raw/Env_Pine/model.glb", runner.RAW)

    def test_do_not_merge_source_parts(self):
        self.spec["parts_policy"] = "join_static"
        with self.assertRaises(ValueError):
            runner.validate_contract(self.spec)

    def test_four_view_axes_and_top(self):
        self.assertEqual(runner.VIEW_DIRECTIONS["front"], (1, 0, 0))
        self.assertEqual(runner.VIEW_DIRECTIONS["left"], (0, -1, 0))
        self.assertEqual(runner.VIEW_DIRECTIONS["right"], (0, 1, 0))
        self.assertEqual(runner.VIEW_DIRECTIONS["top"], (0, 0, 1))


if __name__ == "__main__":
    unittest.main()
