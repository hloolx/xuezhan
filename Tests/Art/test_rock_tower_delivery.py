import copy
import importlib.util
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rock_delivery", ROOT / "Tools/Blender/export_rock_tower_delivery.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def triangle():
    return {"material": "CW_wood", "corners": [
        {"position": [0, 0, 0], "normal": [0, 0, 1], "uv": [[0, 0]]},
        {"position": [1, 0, 0], "normal": [0, 0, 1], "uv": [[1, 0]]},
        {"position": [0, 1, 0], "normal": [0, 0, 1], "uv": [[0, 1]]}]}


class RockTowerDeliveryTests(unittest.TestCase):
    def test_import_has_no_blender_dependency(self):
        self.assertNotIn("bpy", MODULE.__dict__)

    def test_basis_reflects_y_and_scales_metres_once(self):
        self.assertEqual(MODULE.ue_point((1, 2, 3)), [100, -200, 300])
        self.assertEqual(MODULE.ue_point(MODULE.CONTRACT.PIVOT), [-4, 0, 51])

    def test_pitch_sign_matches_installed_unreal_matrix(self):
        for angle in (-65, -35, 0, 40):
            for point in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (.035, 0, .57)):
                expected = MODULE.ue_point(MODULE.CONTRACT.rotate_y(point, angle))
                actual = MODULE.ue_pitch_point(MODULE.ue_point(point), -angle)
                self.assertLess(math.dist(expected, actual), 1e-10)

    def test_surface_match_accepts_only_cyclic_order_not_reversed_winding(self):
        source = triangle()
        shifted = copy.deepcopy(source)
        shifted["corners"] = shifted["corners"][1:] + shifted["corners"][:1]
        self.assertEqual(MODULE.triangle_difference(source, shifted), (0, 0, 0))
        shifted["corners"].reverse()
        self.assertGreater(MODULE.triangle_difference(source, shifted)[0], .1)

    def test_surface_match_reports_uv_and_normal_changes(self):
        source, changed = triangle(), triangle()
        changed["corners"][0]["uv"][0][0] = .1
        changed["corners"][0]["normal"] = [0, 1, 0]
        position, uv, normal = MODULE.triangle_difference(source, changed)
        self.assertEqual(position, 0)
        self.assertAlmostEqual(uv, .1)
        self.assertGreater(normal, 1)
        changed["corners"][0]["uv"] = []
        self.assertTrue(math.isfinite(MODULE.triangle_difference(source, changed)[1]))
        self.assertGreater(MODULE.triangle_difference(source, changed)[1], 1)

    def test_material_numeric_change_fails(self):
        expected = {"CW_wood": {"base_color_linear": [.2, .1, .05, 1], "metallic": 0, "roughness": .66, "alpha": 1}}
        self.assertTrue(MODULE.compare_materials(expected, copy.deepcopy(expected))["passed"])
        changed = copy.deepcopy(expected)
        changed["CW_wood"]["metallic"] = .1
        self.assertFalse(MODULE.compare_materials(expected, changed)["passed"])
        self.assertFalse(MODULE.compare_materials(expected, {})["passed"])

    def test_frozen_approved_dcc_dry_plan_does_not_approve_ue(self):
        plan = MODULE.dry_plan()
        self.assertEqual(plan["rigid_groups"], ["Frame", "Arm", "Stone", "Cloth"])
        self.assertEqual(len(plan["adapters"]), 3)
        self.assertFalse(plan["approved_for_ue_import"])
        self.assertFalse(plan["production_approved"])
        self.assertFalse(plan["time_contract"]["authority_changed"])
        self.assertFalse(plan["ue_import_plan"]["force_front_x_axis"])
        self.assertEqual(plan["time_contract"]["release_seconds"], 0)
        self.assertEqual([item["upper_local_translation_cm"][2] for item in plan["adapters"]], [1.5, .8, 1])


if __name__ == "__main__":
    unittest.main()
