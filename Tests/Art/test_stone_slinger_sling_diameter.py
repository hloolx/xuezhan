import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sling_diameter", ROOT / "Tools/Blender/refine_stone_slinger_sling_diameter.py")
DIAMETER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAMETER)


class DiameterTests(unittest.TestCase):
    def test_continuous_straight_contact_cross_sections(self):
        path = DIAMETER.straight_neck_path(np.array([0., -.04, 0]), np.array([0., .04, 0]), np.array([.1, 0, -.52]))
        points, triangles = DIAMETER.transported_tube(path, .004)
        self.assertEqual(points.shape, (88, 3))
        self.assertEqual(triangles.shape, (172, 3))
        radii = points.reshape(11, 8, 3) - path[:, None]
        np.testing.assert_allclose(np.linalg.norm(radii, axis=2), .004, atol=1e-12)
        np.testing.assert_allclose(radii[0], radii[1], atol=1e-12)

    def test_pouch_endpoint_not_shifted(self):
        path = DIAMETER.joint.old.terminal_paths()["cord_N1"]
        moved = DIAMETER.offset_retained(path, np.array([.012, 0, -.006]))
        np.testing.assert_array_equal(moved[-1], path[-1])
        np.testing.assert_allclose(moved[:2], path[:2] + [.012, 0, -.006])

    def test_interior_failure_not_hidden_by_outside_vertices(self):
        path = np.column_stack((np.zeros(11), np.zeros(11), np.linspace(0, 1, 11)))
        cord, triangles = DIAMETER.transported_tube(path, .004)
        hand = np.array([[-.01, 0, .5], [.01, 0, .5], [0, .01, .5]])
        self.assertTrue(np.all(DIAMETER.signed_surface(hand, cord, triangles) > 0))
        result = DIAMETER.certify_triangle_interiors(hand, np.array([[0, 1, 2]]), np.array([0]), cord, triangles, max_depth=4, budget=3000)
        self.assertFalse(result["passed"])
        self.assertGreater(result["maximum_sample_penetration_m"], .002)

    def test_safe_complete_face_bound(self):
        path = np.column_stack((np.zeros(11), np.zeros(11), np.linspace(0, 1, 11)))
        cord, triangles = DIAMETER.transported_tube(path, .004)
        hand = np.array([[.006, 0, .5], [.006, .0003, .5], [.006, 0, .5003]])
        result = DIAMETER.certify_triangle_interiors(hand, np.array([[0, 1, 2]]), np.array([0]), cord, triangles)
        self.assertTrue(result["passed"])
        self.assertEqual(result["unresolved_face_ids"], [])

    def test_unresolved_budget_rejected(self):
        path = np.column_stack((np.zeros(11), np.zeros(11), np.linspace(0, 1, 11)))
        cord, triangles = DIAMETER.transported_tube(path, .004)
        hand = np.array([[-.01, 0, .5], [.01, 0, .5], [0, .01, .5]])
        result = DIAMETER.certify_triangle_interiors(hand, np.array([[0, 1, 2]]), np.array([0]), cord, triangles, budget=0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["unresolved_face_ids"], [0])


if __name__ == "__main__":
    unittest.main()
