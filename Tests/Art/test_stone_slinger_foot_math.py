import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location("foot_math", Path(__file__).resolve().parents[2] / "Tools/Blender/stone_slinger_foot_math.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FootMathTests(unittest.TestCase):
    def setUp(self):
        self.triangle = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])

    def test_actual_crossing_not_aabb_only(self):
        other = np.array([[.2, .2, -1], [.3, .2, 1], [.2, .3, 1]])
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, other), "proper_crossing")
        disjoint = np.array([[.8, .8, -1], [.9, .8, 1], [.8, .9, 1]])
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, disjoint), "none")

    def test_numpy_height_predicate_is_json_boolean(self):
        result = MODULE.edge_touches_band(np.float64(.075), np.float64(.1), .078, .203)
        self.assertIs(result, True)
        self.assertEqual(json.dumps({"touches_transition_band": result}), '{"touches_transition_band": true}')
        self.assertIs(MODULE.edge_touches_band(np.float64(.21), np.float64(.3), .078, .203), False)

    def test_coplanar_area_and_contact_are_distinct(self):
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, self.triangle + [.1, .1, 0]), "coplanar_area_overlap")
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, self.triangle + [1, 0, 0]), "coplanar_no_area")
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, self.triangle + [2, 0, 0]), "coplanar_no_area")

    def test_parallel_separation(self):
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, self.triangle + [0, 0, .00001]), "none")

    def test_degenerate_does_not_look_like_intersection(self):
        self.assertEqual(MODULE.triangle_contact_kind(self.triangle, np.zeros((3, 3))), "degenerate")

    def test_rigid_rotation_not_a_negative_triangle(self):
        rotation = np.diag([1., -1, -1])
        actual = self.triangle @ rotation.T
        result = MODULE.triangle_orientation(self.triangle, actual, np.array([[0, 1, 2]]), np.repeat(rotation[None], 3, axis=0))
        self.assertEqual(result["negative_triangles"], [])
        self.assertAlmostEqual(result["minimum_expected_normal_dot"], 1)

    def test_local_triangle_reversal_detected(self):
        actual = self.triangle[[0, 2, 1]]
        result = MODULE.triangle_orientation(self.triangle, actual, np.array([[0, 1, 2]]), np.repeat(np.eye(3)[None], 3, axis=0))
        self.assertEqual(result["negative_triangles"], [0])

    def test_native_identity_not_position_weld(self):
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        self.assertEqual(len(MODULE.native_edges(triangles, np.array([0, 1, 2, 0, 1, 2]))), 3)
        self.assertEqual(len(MODULE.native_edges(triangles, np.arange(6))), 6)


if __name__ == "__main__":
    unittest.main()
