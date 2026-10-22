import ast
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "Tools/Blender/plan_stone_slinger_sling_grip.py"
SPEC = importlib.util.spec_from_file_location("sling_plan_test", SCRIPT)
PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLAN)


class SlingGripTests(unittest.TestCase):
    def test_capped_cylinder_signed_distance(self):
        points = np.array([[0, 0, 0], [2, 0, 0], [0, 0, 2], [2, 0, 2]])
        actual = PLAN.cylinder_distances(points, np.zeros(3), np.array([0, 0, 1]), 1, (-1, 1))
        np.testing.assert_allclose(actual, [-1, 1, 1, np.sqrt(2)])

    def test_two_cords_preserve_existing_ring_count(self):
        for path in PLAN.terminal_paths().values():
            self.assertEqual(path.shape, (11, 3))
            self.assertTrue(np.all(np.linalg.norm(np.diff(path, axis=0), axis=1) > 0))

    def test_pouch_attachment_endpoints(self):
        paths = PLAN.terminal_paths()
        np.testing.assert_allclose(paths["cord_N1"][-1], [-.05, 0, -.52])
        np.testing.assert_allclose(paths["cord_P1"][-1], [.10, 0, -.52])

    def test_release_terminal_is_not_retained_terminal(self):
        paths = PLAN.terminal_paths()
        self.assertGreater(np.linalg.norm(paths["cord_N1"][0] - paths["cord_P1"][0]), .1)
        np.testing.assert_allclose(paths["cord_N1"][1] - paths["cord_N1"][0], [0, .081, 0])
        np.testing.assert_allclose(paths["cord_P1"][1] - paths["cord_P1"][0], [0, -.028, 0])

    def test_release_deformation_keeps_pouch_end(self):
        path = PLAN.terminal_paths()["cord_P1"]
        actual = path + (1 - np.arange(11) / 10)[:, None] ** 2 * np.array([.07, .10, -.05])
        np.testing.assert_array_equal(actual[-1], path[-1])
        self.assertGreater(np.linalg.norm(actual[0] - path[0]), .1)

    def test_preparation_is_unapproved_and_real_source_frozen(self):
        data = json.loads((PLAN.BRANCH / "preparation_05/grip_preparation.json").read_text(encoding="utf-8"))
        self.assertFalse(data["grip_approved"])
        self.assertFalse(data["blender_started"])
        self.assertEqual(data["source"]["sha256"], PLAN.SOURCE_SHA)
        basis = np.array(data["weapon_basis_columns"])
        np.testing.assert_allclose(basis.T @ basis, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(basis), 1)

    def test_actual_server_timing_not_axe_timing(self):
        units = json.loads((ROOT / "Content/Data/Units.json").read_text(encoding="utf-8-sig"))
        row = next(row for row in units if row["VisualKey"] == "Unit_StoneSlinger")
        self.assertEqual(row["AttackInterval"], 1.4)
        self.assertEqual(row["AttackWindup"], .45)
        self.assertEqual(row["ProjectileSpeed"], 1400)
        self.assertEqual(round(row["AttackWindup"] * 60) + 1, 28)

    def test_candidate_tool_does_not_write_animation_or_run_ue(self):
        path = ROOT / "Tools/Blender/prepare_stone_slinger_sling_pilot.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any("keyframe_insert" in call or "subprocess" in call or "export_scene" in call for call in calls))
        self.assertIn("output.mkdir", calls)


if __name__ == "__main__":
    unittest.main()
