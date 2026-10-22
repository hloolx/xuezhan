import importlib.util
import inspect
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_support_test", ROOT / "Tools/Blender/compare_mammoth_buckle_support.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothSupportTests(unittest.TestCase):
    def test_only_reviewed_outer_ring_and_two_starts_per_side(self):
        source = inspect.getsource(MODULE.analyze)
        self.assertIn('original["outer12cm_native_geodesic_distances_m"]', source)
        self.assertIn('for profile in ("slowfall", "smoothstep")', source)
        self.assertIn('"candidate_count": 4', source)
        self.assertEqual(MODULE.RADIUS_M, .12)

    def test_no_model_weight_application_or_blender(self):
        source = inspect.getsource(MODULE.analyze)
        for forbidden in ("import bpy", "write_bytes", "vertex_groups", "export_scene"):
            self.assertNotIn(forbidden, source)
        self.assertIn('"tail_changes": 0', source)
        self.assertIn('"added_native_vertices": added_native', source)
        self.assertIn('"added_render_vertices": added_render', source)


if __name__ == "__main__":
    unittest.main()
