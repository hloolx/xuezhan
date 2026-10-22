import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "Tools/Blender"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("waist_transition", TOOLS / "plan_stone_slinger_waist_transition.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WaistTransitionTests(unittest.TestCase):
    def test_fixed_boundary_harmonic_field_is_unique_and_bounded(self):
        positions = {index: np.array([index, 0., 0.]) for index in range(5)}
        adjacency = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2, 4}, 4: {3}}
        amounts, boundary = MODULE.harmonic_fraction(positions, adjacency, [0, 1, 2, 3], [0])
        self.assertEqual(boundary, [3])
        self.assertEqual(amounts[0], 1)
        self.assertEqual(amounts[3], 0)
        self.assertAlmostEqual(amounts[1], 2 / 3)
        self.assertAlmostEqual(amounts[2], 1 / 3)

    def test_no_new_recipient_and_preserves_original_proportions(self):
        original = {"spine_01": .2, "spine_02": .1, "thigh_r": .62, "upperarm_r": .08}
        result = MODULE.partial_transfer(original, .5)
        self.assertEqual(set(result), set(original))
        self.assertEqual(result["upperarm_r"], .04)
        self.assertAlmostEqual(sum(result.values()), 1)
        self.assertAlmostEqual(result["spine_01"] / result["spine_02"], 2)
        self.assertEqual(MODULE.partial_transfer(original, 0), original)

    def test_checks_patch_against_outside_triangle(self):
        points = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0], [0, 0, -1], [0, 0, 1], [0, .5, 0.]])
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        result = MODULE.changed_face_crossings(points, triangles, np.arange(6), [0])
        self.assertEqual(result, [[0, 1, "proper_crossing"]])

    def test_rotation_projection_removes_only_numeric_scale(self):
        rotation = MODULE.proper_rotation(np.diag([1.000001, .999999, 1.]))
        np.testing.assert_allclose(rotation, np.eye(3), atol=1e-12)


if __name__ == "__main__":
    unittest.main()
