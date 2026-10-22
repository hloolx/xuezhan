import importlib.util
from pathlib import Path
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location("slinger_rig_inspect", Path(__file__).resolve().parents[2] / "Tools/Blender/inspect_stone_slinger_rig.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FrameTests(unittest.TestCase):
    def test_rotations_are_only_proper(self):
        rotations = MODULE.proper_axis_rotations()
        self.assertEqual(len(rotations), 24)
        self.assertEqual(len({tuple(rotation.flatten()) for rotation in rotations}), 24)
        for rotation in rotations:
            self.assertAlmostEqual(np.linalg.det(rotation), 1)
            np.testing.assert_array_equal(rotation @ rotation.T, np.eye(3))

    def test_similarity_is_not_index_dependent(self):
        original = np.array([[0, 0, 0], [.3, .1, .7], [.2, .6, 1.425], [-.1, .3, .4]])
        rotation = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        translation = np.array([.1, .3, .7])
        returned = ((original - translation) / 1.425) @ rotation
        candidates = MODULE.fit_axis_candidates(original, returned[::-1])
        matching = [candidate for candidate in candidates if np.array_equal(candidate["rotation"], rotation)]
        self.assertEqual(len(matching), 1)
        np.testing.assert_allclose(matching[0]["translation_m"], translation, atol=1e-12)
        self.assertAlmostEqual(matching[0]["uniform_scale"], 1.425)

    def test_degenerate_points_are_rejected(self):
        self.assertEqual(MODULE.fit_axis_candidates(np.zeros((4, 3)), np.zeros((4, 3))), [])


class SurfaceTests(unittest.TestCase):
    def snapshot(self):
        return {"positions": np.array([[0., 0, 0], [.2, 0, .1], [.1, .3, .2], [.3, .2, .4]]),
                "triangles": np.array([[0, 1, 2], [0, 2, 3]]),
                "triangle_loops": np.array([[0, 1, 2], [3, 4, 5]]),
                "normals": np.array([[0., 0, 1]] * 6),
                "uv": np.array([[0., 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]])}

    def fit(self):
        return {"rotation": np.eye(3).tolist(), "uniform_scale": 1.0, "translation_m": [0., 0, 0]}

    def test_triangle_order_can_change_without_index_assumption(self):
        source = self.snapshot()
        returned = self.snapshot()
        returned["triangles"] = returned["triangles"][::-1]
        returned["triangle_loops"] = returned["triangle_loops"][::-1]
        result = MODULE.triangle_correspondence(source, returned, self.fit())
        self.assertTrue(result["geometry_uv_and_normals_preserved"])
        self.assertTrue(result["vertex_incidence_bijection"])

    def test_uv_change_and_bad_normal_are_not_accepted(self):
        source, returned = self.snapshot(), self.snapshot()
        returned["uv"][0, 0] = .01
        returned["normals"][0] *= -1
        result = MODULE.triangle_correspondence(source, returned, self.fit())
        self.assertFalse(result["geometry_uv_and_normals_preserved"])
        self.assertAlmostEqual(result["maximum_errors"]["normal_vector"], 2.0)

    def test_topology_split_is_separate_from_surface_equality(self):
        source, returned = self.snapshot(), self.snapshot()
        returned["positions"] = np.vstack((returned["positions"], returned["positions"][0]))
        returned["triangles"][1, 0] = 4
        result = MODULE.triangle_correspondence(source, returned, self.fit())
        self.assertTrue(result["geometry_uv_and_normals_preserved"])
        self.assertFalse(result["vertex_incidence_bijection"])
        self.assertEqual(result["source_vertex_splits"], {"0": [0, 4]})


if __name__ == "__main__":
    unittest.main()
