import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_normal_probe", ROOT / "Tools/Blender/diagnose_mammoth_follower_normals.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothNormalProbeTests(unittest.TestCase):
    def test_tiny_angle_uses_cross_dot_not_lossy_arccos(self):
        report, _ = MODULE.vector_difference([[1., 0, 0]], [[1., 1e-8, 0]])
        self.assertAlmostEqual(report["maximum_angle_degrees"], np.degrees(1e-8), places=12)

    def test_nonfinite_normals_fail(self):
        with self.assertRaises(ValueError):
            MODULE.vector_difference([[1., 0, 0]], [[np.nan, 0, 0]])

    def test_probe_does_not_set_normals_export_or_render(self):
        source = inspect.getsource(MODULE.run)
        for forbidden in ("normals_split_custom_set", "bpy.ops.render", "export_scene", "write_bytes"):
            self.assertNotIn(forbidden, source)
        self.assertIn("finally:", source)
        self.assertIn("importer.skin_into_bind_pose = actual_skin", source)


if __name__ == "__main__":
    unittest.main()
