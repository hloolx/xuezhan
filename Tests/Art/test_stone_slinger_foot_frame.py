import importlib.util
from pathlib import Path
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location("foot_frame", Path(__file__).resolve().parents[2] / "Tools/Blender/render_stone_slinger_foot_completion.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FootFrameTests(unittest.TestCase):
    def test_both_sides_union_frame_has_margin(self):
        for sign in (-1, 1):
            points = np.array([[-.16, sign * .1, -.075], [.17, sign * .37, .35], [.12, sign * .25, -.06], [-.1, sign * .15, .26]])
            target, size, basis = MODULE.orthographic_frame(points, (1, sign * 1.8, .5))
            normalized = (points - target) @ basis[:2].T / size + .5
            self.assertGreaterEqual(float(np.minimum(normalized, 1 - normalized).min()), .08)
            np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-15)

    def test_center_and_scale_follow_translation(self):
        points = np.array([[-.1, -.2, 0], [.2, .2, .35]])
        center, size, _ = MODULE.orthographic_frame(points, (1, 1.8, .5))
        translated, other_size, _ = MODULE.orthographic_frame(points + [3., 4., 5.], (1, 1.8, .5))
        np.testing.assert_allclose(translated, center + [3, 4, 5], atol=1e-14)
        self.assertAlmostEqual(size, other_size)


if __name__ == "__main__":
    unittest.main()
