import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_pair_probe_test", ROOT / "Tools/Blender/diagnose_mammoth_follower_intersections.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FIXED_SPEC = importlib.util.spec_from_file_location("mammoth_pair_probe_json_test", ROOT / "Tools/Blender/diagnose_mammoth_follower_intersections_v04.py")
FIXED = importlib.util.module_from_spec(FIXED_SPEC)
FIXED_SPEC.loader.exec_module(FIXED)


class MammothPairProbeTests(unittest.TestCase):
    def test_full_crossing_report_serializes_without_changing_predicate(self):
        first = np.array([[-1., -1, 0], [1, -1, 0], [0, 1, 0]])
        second = np.array([[0., -.5, -1], [0, -.5, 1], [0, .5, 0]])
        original = MODULE.triangle_details(first, second)
        safe = FIXED.json_safe(original)
        self.assertEqual(original, safe)
        self.assertIsInstance(safe["edge_plane_witnesses"][0]["strict_original_crossing_witness"], bool)

    def test_crossing_records_signed_depth_and_segment(self):
        first = np.array([[-1., -1, 0], [1, -1, 0], [0, 1, 0]])
        second = np.array([[0., -.5, -1], [0, -.5, 1], [0, .5, 0]])
        result = MODULE.triangle_details(first, second)
        self.assertEqual(result["kind"], "proper_crossing")
        self.assertGreater(result["intersection_segment_length_m"], .9)
        self.assertTrue(any(row["strict_original_crossing_witness"] for row in result["edge_plane_witnesses"]))

    def test_coplanar_contact_is_not_transverse_penetration(self):
        first = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        result = MODULE.triangle_details(first, first + [.1, .1, 0])
        self.assertEqual(result["kind"], "coplanar_area_overlap")
        self.assertEqual(result["maximum_strict_crossing_endpoint_margin_m"], 0)

    def test_winding_reversal_does_not_change_intersection_class(self):
        first = np.array([[-1., -1, 0], [1, -1, 0], [0, 1, 0]])
        second = np.array([[0., -.5, -1], [0, -.5, 1], [0, .5, 0]])
        before = MODULE.triangle_details(first, second)
        after = MODULE.triangle_details(first[::-1], second)
        self.assertEqual(before["kind"], after["kind"])
        np.testing.assert_allclose(before["second_vertices_signed_distance_to_first_plane_m"], -np.array(after["second_vertices_signed_distance_to_first_plane_m"]))


if __name__ == "__main__":
    unittest.main()
