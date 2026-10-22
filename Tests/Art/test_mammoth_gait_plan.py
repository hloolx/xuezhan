import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_gait_plan_test", ROOT / "Tools/plan_mammoth_gait.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothGaitPlanTests(unittest.TestCase):
    def test_unit_is_matched_by_name_and_visual_key(self):
        unit = {"Name": "BeastRider", "VisualKey": "Unit_BeastRider", "MoveSpeed": 220, "AttackWindup": .4, "AttackInterval": 1.6}
        self.assertEqual(MODULE.select_unit([{}, unit])[0], 1)
        with self.assertRaises(ValueError):
            MODULE.select_unit([unit, unit])
        with self.assertRaises(ValueError):
            MODULE.select_unit([{**unit, "VisualKey": "Unit_StoneAxe"}])

    def test_foot_uses_each_sole_baseline_not_global_zero(self):
        points = np.array([[.3, .3, .02], [.4, .3, .025], [.3, .4, .10], [.3, .3, .02]])
        measured = MODULE.measure_foot(points, [0, 1, 2, 3], [1, 1])
        self.assertEqual(measured["sole_minimum_world_z_m"], .02)
        self.assertEqual(measured["sole_unique_position_count"], 2)
        self.assertEqual(measured["sole_render_indices"], [0, 1, 3])

    def test_foot_names_do_not_override_spatial_mismatch(self):
        with self.assertRaises(ValueError):
            MODULE.measure_foot(np.array([[.3, -.3, .01]]), [0], [1, 1])
        with self.assertRaises(ValueError):
            MODULE.measure_foot(np.array([[.3, .3, .4]]), [0], [1, 1])

    def test_sagittal_axis_roundtrips_from_measured_basis(self):
        matrix = np.eye(4)
        angle = np.deg2rad(37)
        matrix[:3, :3] = [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
        result = MODULE.local_axis(matrix)
        np.testing.assert_allclose(np.array(result["world_local_axes_columns_blender"]) @ result["corresponding_local_axis"], [0, 1, 0], atol=1e-12)

    def test_mirrored_bone_basis_is_rejected(self):
        matrix = np.eye(4)
        matrix[0, 0] = -1
        with self.assertRaises(ValueError):
            MODULE.local_axis(matrix)

    def test_stance_sweep_includes_duty_fraction(self):
        result = MODULE.stride_contract(220, [0, 0, 1], [0, 0, 0], .6, .65)
        self.assertAlmostEqual(result["virtual_world_travel_per_cycle_cm"], 132)
        self.assertAlmostEqual(result["required_local_foot_stance_sweep_cm"], 85.8)
        self.assertAlmostEqual(result["illustrative_rigid_leg_plus_minus_8_degree_sweep_cm"], 200*np.sin(np.deg2rad(8)))
        self.assertTrue(result["not_a_solved_ground_contact_or_multijoint_reach_test"])

    def test_impossible_rigid_reach_is_not_clamped_to_pass(self):
        result = MODULE.stride_contract(220, [0, 0, .1], [0, 0, 0])
        self.assertIsNone(result["illustrative_angle_for_proposed_stance_sweep_degrees"])

    def test_output_cannot_escape_owned_fresh_directory(self):
        with self.assertRaises(ValueError):
            MODULE.checked_output(ROOT / "Content/Data/gait_plan_01")
        with self.assertRaises(ValueError):
            MODULE.checked_output(MODULE.BRANCH / "rig_transfer_parent_02")

    def test_no_heavy_or_model_write_api_in_planner(self):
        text = (ROOT / "Tools/plan_mammoth_gait.py").read_text(encoding="utf-8")
        self.assertNotIn("import bpy", text)
        self.assertNotIn("import unreal", text)
        self.assertNotIn("subprocess", text)
        self.assertNotIn("write_bytes", text)


if __name__ == "__main__":
    unittest.main()
