import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Tools/Blender"))
import plan_stone_slinger_loop_anchor as geometry
import audit_stone_slinger_loop_anchor as audit


class LoopAnchorTests(unittest.TestCase):
    def test_variable_ring_tube_is_closed_and_unit_sections(self):
        points, faces, quality = geometry.tube(np.column_stack((np.zeros(19), np.zeros(19), np.linspace(0, .1, 19))), .004)
        _, _, topology = geometry.orient_closed_mesh(points, faces)
        self.assertEqual(topology["connected_components"], 1)
        self.assertTrue(all(quality["checks"].values()))
        self.assertEqual(len(faces), 19 * 16 - 4)

    def test_surface_plane_interpolation(self):
        points = np.array([[-1., 0, 0], [1., 0, 0], [0, 1., 1], [0, -1., 1]])
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
        section = geometry.plane_section(points, faces, np.array([0., 0., .5]), np.array([0., 0., 1.]))
        self.assertTrue(np.allclose(section[:, 2], .5))

    def test_branch_loop_has_one_closed_component_without_overlapping_pipes(self):
        path = np.column_stack((np.linspace(.03, .13, 21), np.zeros(21), np.zeros(21)))
        points, faces, quality = geometry.loop_with_stem(np.zeros(3), np.array([0., 0., 1.]), np.array([1., 0., 0.]), .015, path)
        self.assertEqual(quality["topology"]["connected_components"], 1)
        self.assertTrue(quality["topology"]["closed_two_face_edges"])
        edges = {tuple(sorted((int(face[index]), int(face[(index + 1) % 3])))) for face in faces for index in range(3)}
        self.assertEqual(len(points) - len(edges) + len(faces), 0)

    def test_bezier_endpoint_tangents(self):
        curve = geometry.bezier([[0, 0, 0], [.02, 0, 0], [.1, .08, 0], [.1, .1, 0]], 100)
        self.assertTrue(np.allclose(curve[0], [0, 0, 0]))
        self.assertTrue(np.allclose(curve[-1], [.1, .1, 0]))
        self.assertGreater(geometry.unit(curve[1] - curve[0])[0], .99)
        self.assertGreater(geometry.unit(curve[-1] - curve[-2])[1], .99)

    def test_tight_corner_fails_shape_contract(self):
        _, _, quality = geometry.tube([[0, 0, 0], [0, 0, .003], [.003, 0, .003]], .004)
        self.assertFalse(quality["checks"]["maximum_polyline_turn_at_most15degrees"])
        self.assertFalse(quality["checks"]["radius_curvature_at_most_half"])

    def test_open_boundary_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            geometry.orient_closed_mesh(np.eye(3), np.array([[0, 1, 2]]))

    def test_section_does_not_mix_another_folded_finger_lobe(self):
        points = np.array([[-1., 0, 0], [1., 0, 0], [0, 1., 1], [0, -1., 1]])
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
        combined = np.vstack((points, points + [5, 0, 0]))
        section, records = geometry.plane_section_components(combined, np.vstack((faces, faces + 4)), np.array([0., 0., .5]), np.array([0., 0., 1.]))
        self.assertEqual(len(records), 2)
        self.assertLess(section[:, 0].max(), 1)

    def test_explicit_arc_meets_curvature_without_sampling_excuse(self):
        path = geometry.tangent_arc(np.zeros(3), np.array([1., 0, 0]), np.array([0., 0, -1.]), .02)
        _, _, quality = geometry.tube(path, .004)
        self.assertTrue(all(quality["checks"].values()))
        self.assertAlmostEqual(quality["minimum_discrete_bend_radius_m"], .02)

    def test_retention_contact_uses_true03_face_interior_not_closer02proxy(self):
        first = np.array([[0., 0., .001], [.01, 0., .001], [0., .01, .001]])
        second = first - [0, 0, .001]
        points = np.vstack((first, second))
        result = audit.fixed_contact_samples(points, np.array([[0, 1, 2], [3, 4, 5]]), [{"pinky_03_r": .6}] * 3 + [{"pinky_02_r": .9}] * 3,
                                             "pinky_03_r", second, np.array([[0, 1, 2]]))
        self.assertEqual(result["triangle"], 0)
        self.assertAlmostEqual(result["gap_m"], .001)
        self.assertGreater(min(result["barycentric"]), 0)


if __name__ == "__main__":
    unittest.main()
