import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_followers_test", ROOT / "Tools/Blender/test_mammoth_rigid_followers.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothFollowerFeasibilityTests(unittest.TestCase):
    def test_proper_fit_recovers_rigid_motion_without_scale(self):
        source = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        rotation = np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]])
        target = source @ rotation.T + [2, 3, 4]
        matrix, _ = MODULE.proper_rigid_fit(source, target, np.ones(4))
        np.testing.assert_allclose(matrix[:3, :3], rotation, atol=1e-12)
        np.testing.assert_allclose(matrix[:3, 3], [2, 3, 4], atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(matrix[:3, :3]), 1)

    def test_mirror_cannot_be_returned_as_rigid_transform(self):
        source = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        matrix, _ = MODULE.proper_rigid_fit(source, source * [-1, 1, 1], np.ones(4))
        self.assertAlmostEqual(np.linalg.det(matrix[:3, :3]), 1)
        predicted = source @ matrix[:3, :3].T + matrix[:3, 3]
        self.assertGreater(np.linalg.norm(predicted - source * [-1, 1, 1]), .1)

    def test_collinear_fit_is_rejected(self):
        source = np.array([[0., 0, 0], [1, 0, 0], [2, 0, 0]])
        with self.assertRaisesRegex(ValueError, "collinear"):
            MODULE.proper_rigid_fit(source, source, np.ones(3))

    def test_sparse_fit_is_nonnegative_and_normalized_with_at_most_three_originals(self):
        positions = {0: np.zeros((8, 3)), 1: np.ones((8, 3)), 2: np.full((8, 3), 2.), 3: np.full((8, 3), 3.)}
        target = np.full((8, 3), 1.2)
        weights, error, _ = MODULE.fit_sparse_original(positions, target, {0: .25, 1: .25, 2: .25, 3: .25})
        self.assertLessEqual(len(weights), 3)
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertGreaterEqual(min(weights.values()), 0)
        self.assertLess(error, 1e-9)

    def test_feasibility_does_not_add_bones_or_launch_blender(self):
        source = inspect.getsource(MODULE.analyze)
        for forbidden in ("import bpy", "edit_bones", "write_bytes", "export_scene"):
            self.assertNotIn(forbidden, source)
        self.assertIn('"fit_policies_tried": 1', source)
        self.assertIn('"actual_bones_added": 0', source)


if __name__ == "__main__":
    unittest.main()
