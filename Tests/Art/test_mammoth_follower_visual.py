import importlib.util
import inspect
from pathlib import Path
import struct
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_visual_test", ROOT / "Tools/Blender/prepare_mammoth_follower_visual.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothFollowerVisualTests(unittest.TestCase):
    def test_pack_weights_rejects_fifth_or_unnormalized_influence(self):
        with self.assertRaises(ValueError):
            MODULE.pack_weight_row({str(index): .2 for index in range(5)}, [str(index) for index in range(5)])
        with self.assertRaises(ValueError):
            MODULE.pack_weight_row({"bone": .9}, ["bone"])

    def test_pack_weights_preserves_follower_identity(self):
        joints, weights = MODULE.pack_weight_row({"follower": 1.}, ["original", "follower"])
        self.assertEqual(joints.tolist(), [1, 0, 0, 0])
        self.assertEqual(weights.tolist(), [1., 0., 0., 0.])

    def test_proper_triangle_crossing_is_detected(self):
        first = np.array([[-1., -1, 0], [1, -1, 0], [0, 1, 0]])
        second = np.array([[0., -.5, -1], [0, -.5, 1], [0, .5, 0]])
        self.assertTrue(MODULE.proper_triangle_intersection(first, second))

    def test_intended_shared_edge_is_not_penetration(self):
        first = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        second = np.array([[1., 0, 0], [1, 1, 0], [0, 1, 0]])
        self.assertFalse(MODULE.proper_triangle_intersection(first, second))

    def test_coplanar_positive_area_overlap_is_detected(self):
        first = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        second = first + [.1, .1, 0]
        self.assertTrue(MODULE.proper_triangle_intersection(first, second))
        self.assertFalse(MODULE.proper_triangle_intersection(first, second + [0, 0, .01]))

    def test_new_flip_and_collapse_are_not_ignored(self):
        before = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        flipped = before[[0, 2, 1]]
        result = MODULE.face_changes(before, flipped, np.array([[0, 1, 2]]), [0])
        self.assertEqual(result["normal_reversed_triangles"], [0])
        collapsed = before.copy()
        collapsed[2] = [.5, 0, 0]
        result = MODULE.face_changes(before, collapsed, np.array([[0, 1, 2]]), [0])
        self.assertEqual(result["new_degenerate_triangles"], [0])

    def test_exact_failed_policy_is_reused_without_optimizer_or_constraint(self):
        source = inspect.getsource(MODULE.build_candidate) + inspect.getsource(MODULE.run)
        self.assertNotIn("optimizer.optimize(", source)
        self.assertNotIn("constraints.new", source)
        self.assertNotIn("export_scene", source)
        self.assertIn('"historical_per_edge_strain_gate": "FAIL"', source)
        self.assertIn("keyframe_insert", inspect.getsource(MODULE.bake_action))

    def test_candidate_preserves_entire_original_binary_and_surface_accessors(self):
        payload, report = MODULE.build_candidate()
        json_size = struct.unpack_from("<I", payload, 12)[0]
        document = MODULE.json.loads(payload[20:20 + json_size])
        binary_size = struct.unpack_from("<I", payload, 20 + json_size)[0]
        binary = payload[28 + json_size:28 + json_size + binary_size]
        original, original_binary = MODULE.transfer.read_container(MODULE.MODEL)
        self.assertEqual(binary[:len(original_binary)], original_binary)
        before = MODULE.transfer.source_arrays(original, original_binary)
        after = MODULE.transfer.source_arrays(document, binary)
        for name in ("POSITION", "NORMAL", "TEXCOORD_0", "indices"):
            np.testing.assert_array_equal(before[name], after[name])
        self.assertEqual(len(document["skins"][0]["joints"]), 35)
        self.assertEqual(document["materials"], original["materials"])
        self.assertEqual(document["images"], original["images"])
        self.assertLess(report["numeric_skin_rest_max_error_m"], 3e-6)
        self.assertEqual(report["historical_per_edge_strain_gate"], "FAIL")
        self.assertFalse(report["production_approved"])


if __name__ == "__main__":
    unittest.main()
