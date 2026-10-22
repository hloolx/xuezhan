import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "Tools/Blender"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("waist_plan", TOOLS / "plan_stone_slinger_waist_weights.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WaistWeightPlanTests(unittest.TestCase):
    def test_only_existing_recipients_and_mass_preserved(self):
        original = {"spine_01": .2, "spine_02": .14, "upperarm_r": .06, "thigh_r": .6}
        result = MODULE.remove_arm_influence(original)
        self.assertEqual(set(result), {"spine_01", "spine_02", "thigh_r"})
        self.assertAlmostEqual(sum(result.values()), sum(original.values()))
        self.assertAlmostEqual(result["spine_01"] / result["thigh_r"], 1 / 3)
        self.assertEqual(original["upperarm_r"], .06)

    def test_rejects_unproven_scope(self):
        for value in ({"hand_r": .94, "upperarm_r": .06}, {"spine_01": .8, "upperarm_r": .2}, {"spine_01": 1}):
            with self.assertRaises(ValueError):
                MODULE.remove_arm_influence(value)

    def test_shortest_arm_rotation_is_proper(self):
        rotation = MODULE.rotation_between([0, 1, 0], [1, 0, 1])
        np.testing.assert_allclose(rotation @ np.array([0, 1, 0]), np.array([1, 0, 1]) / np.sqrt(2), atol=1e-12)
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(rotation), 1)

    def test_native_neighbourhood_includes_uv_duplicate_faces_without_position_weld(self):
        native = np.array([10, 11, 12, 10, 13, 14, 99, 98, 97])
        triangles = np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]])
        vertices, faces = MODULE.native_neighborhood(triangles, native, [10])
        self.assertEqual(vertices, [10, 11, 12, 13, 14])
        self.assertEqual(faces.tolist(), [0, 1])


if __name__ == "__main__":
    unittest.main()
