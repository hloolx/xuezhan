import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "Tools/Blender"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("foot_plan", TOOLS / "plan_stone_slinger_foot_weights.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FootPlanTests(unittest.TestCase):
    def test_blend_band_is_bounded_and_smooth(self):
        self.assertEqual(MODULE.fade_height(.02, .08, .20), 1)
        self.assertEqual(MODULE.fade_height(.30, .08, .20), 0)
        self.assertAlmostEqual(MODULE.fade_height(.14, .08, .20), .5)
        self.assertLess(1 - MODULE.fade_height(.080001, .08, .2), 1e-8)

    def test_preserves_ball_and_mass_not_wholeboot_rigid(self):
        source = {"calf_twist_01_l": .6, "foot_l": .1, "ball_l": .3}
        after, moved = MODULE.transfer_proximal(source, "l", .5)
        self.assertEqual(after["ball_l"], .3)
        self.assertAlmostEqual(after["calf_twist_01_l"], .3)
        self.assertAlmostEqual(after["foot_l"], .4)
        self.assertAlmostEqual(sum(after.values()), 1)
        self.assertEqual(source["foot_l"], .1)

    def test_wrong_side_and_upperbody_remain_untouched(self):
        source = {"calf_r": .4, "spine_03": .6}
        after, moved = MODULE.transfer_proximal(source, "l", 1)
        self.assertEqual(after, source)
        self.assertEqual(moved, 0)

    def test_axis_rotation_stays_proper(self):
        rotation = MODULE.axis_rotation([0, 2, 0], 20)
        np.testing.assert_allclose(rotation[:3, :3] @ rotation[:3, :3].T, np.eye(3), atol=1e-15)
        self.assertAlmostEqual(np.linalg.det(rotation), 1)


if __name__ == "__main__":
    unittest.main()
