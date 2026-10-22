import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("joint_pinch", ROOT / "Tools/Blender/plan_stone_slinger_joint_pinch.py")
PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLAN)


class JointPinchTests(unittest.TestCase):
    def test_true_pad_rejects_any_02_corner(self):
        points = np.array([[0., 0, .5], [.1, 0, .5], [0, 0, .7], [0, 0, .6]])
        triangles = np.array([[0, 2, 1], [0, 2, 3]])
        weights = [{"index_03_r": 1}] * 3 + [{"index_02_r": 1}]
        bones = [{"name": "index_03_r", "head_world_review_m": [0, 0, 0], "tail_world_review_m": [0, 0, 1]}]
        np.testing.assert_array_equal(PLAN.pad_faces("index", points, triangles, weights, bones, np.array([0, 1, 0])), [0])

    def test_surface_closest_point_plane_edge_and_vertex(self):
        triangle = np.array([[[0., 0, 0], [1, 0, 0], [0, 1, 0]]])
        points = np.array([[.2, .2, 1], [.5, -.2, 0], [-1, 0, 0]])
        distances, nearest = PLAN.nearest_surface(points, triangle)
        np.testing.assert_allclose(distances, [1, .2, 1])
        np.testing.assert_allclose(nearest, [[.2, .2, 0], [.5, 0, 0], [0, 0, 0]])

    def test_actual_closed_octagonal_tube_parity(self):
        path = np.column_stack((np.zeros(11), np.zeros(11), np.linspace(0, 1, 11)))
        points, triangles = PLAN.tube_mesh(path)
        self.assertEqual(points.shape, (88, 3))
        self.assertEqual(triangles.shape, (172, 3))
        samples = np.array([[0, 0, .5], [.02, 0, .5], [0, 0, -1], [0, 0, 2]])
        np.testing.assert_array_equal(PLAN.parity_inside(samples, points[triangles]), [True, False, False, False])

    def test_tube_has_closed_edge_incidence(self):
        path = np.column_stack((np.zeros(11), np.zeros(11), np.linspace(0, 1, 11)))
        _, triangles = PLAN.tube_mesh(path)
        counts = {}
        for triangle in triangles:
            for start, end in zip(triangle, np.roll(triangle, -1)):
                key = tuple(sorted((int(start), int(end))))
                counts[key] = counts.get(key, 0) + 1
        self.assertTrue(all(value == 2 for value in counts.values()))

    def test_proper_crossing_not_just_aabb_overlap(self):
        points = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [.2, .2, -1], [.2, .2, 1], [.8, .2, 0]])
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        result = PLAN.pair_crossings(points, triangles, [0], [1], np.arange(6))
        self.assertEqual(result[0][2], "proper_crossing")

    def test_release_path_keeps_existing_pouch_end(self):
        path = PLAN.release_path(np.array([.1, .1, .1]), np.array([1., 0, 0]), np.eye(3), np.zeros(3))
        self.assertEqual(path.shape, (11, 3))
        np.testing.assert_allclose(path[-1], [.1, 0, -.52])
        self.assertAlmostEqual(np.linalg.norm(path[0] - path[1]), .04)


if __name__ == "__main__":
    unittest.main()
