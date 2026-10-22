import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_transfer_test", ROOT / "Tools/Blender/prepare_mammoth_rig_transfer.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothTransferTests(unittest.TestCase):
    def test_coincident_source_vertices_keep_distinct_indices_and_exact_weights(self):
        joints = np.array([[0, 1, 2, 3]], dtype="u1")
        weights = np.array([[.5, .3, .15, .05]], dtype="f4")
        actual_joints, actual_weights, chosen = MODULE.resolve_weights({"0": [0], "1": [0]}, joints, weights, 2)
        self.assertEqual(len(actual_joints), 2)
        np.testing.assert_array_equal(actual_weights, weights[[0, 0]])
        np.testing.assert_array_equal(chosen, [0, 0])

    def test_inconsistent_corner_weights_cannot_be_averaged(self):
        joints = np.array([[0, 1], [0, 1]])
        with self.assertRaisesRegex(ValueError, "averaging"):
            MODULE.resolve_weights({"0": [0, 1]}, joints, np.array([[.8, .2], [.7, .3]]), 1)

    def test_equal_reordered_influences_keep_first_actual_row(self):
        joints = np.array([[0, 1], [1, 0]])
        weights = np.array([[.8, .2], [.2, .8]])
        actual_joints, actual_weights, _ = MODULE.resolve_weights({"0": [0, 1]}, joints, weights, 1)
        np.testing.assert_array_equal(actual_joints[0], joints[0])
        np.testing.assert_array_equal(actual_weights[0], weights[0])

    def test_missing_vertex_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            MODULE.resolve_weights({}, np.zeros((1, 4)), np.zeros((1, 4)), 1)

    def test_matrix_column_major_and_parent_order(self):
        matrix = np.eye(4)
        matrix[:3, 3] = [2, 3, 4]
        document = {"nodes": [{"matrix": matrix.T.reshape(-1).tolist(), "children": [1]}, {"translation": [1, 0, 0]}]}
        worlds, parents = MODULE.world_matrices(document)
        np.testing.assert_allclose(worlds[1][:3, 3], [3, 3, 4])
        self.assertEqual(parents[1], 0)

    def test_cycle_rejected(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            MODULE.world_matrices({"nodes": [{"children": [1]}, {"children": [0]}]})

    def test_inversebind_accessor_float32_column_major_roundtrip(self):
        document = {"accessors": [], "bufferViews": []}
        matrix = np.eye(4)[None]
        matrix[0, :3, 3] = [1.1, 2.2, 3.3]
        binary = bytearray(b"1234")
        index = MODULE.append_accessor(document, binary, matrix, "MAT4", 5126)
        np.testing.assert_allclose(MODULE.accessor(document, binary, index), matrix, atol=2e-7)
        self.assertEqual(binary[:4], b"1234")

    def test_skin_identity_preserves_actual_weight_values(self):
        points = np.array([[1., 2, 3]])
        skin = MODULE.skin_positions(points, np.array([[0, 1]]), np.array([[.7, .3]]), np.array([np.eye(4), np.eye(4)]))
        np.testing.assert_allclose(skin, points)

    def test_rigid_motion_does_not_count_as_buckle_deformation(self):
        before = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        after = before @ np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) + [4, 5, 6]
        report = MODULE.rigid_residual(before, after)
        self.assertLess(report["best_rigid_fit_max_residual_m"], 1e-12)
        self.assertLess(report["max_pair_relative_strain"], 1e-12)

    def test_nonrigid_buckle_stretch_is_measured(self):
        before = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        report = MODULE.rigid_residual(before, before * [1.1, 1, 1])
        self.assertGreater(report["best_rigid_fit_max_residual_m"], .01)
        self.assertAlmostEqual(report["max_pair_relative_strain"], .1)

    def test_diagnostic_retains_baseline_and_does_not_reexport_or_fix(self):
        source = inspect.getsource(MODULE.diagnose)
        self.assertIn("disable_bone_shape=True", source)
        self.assertIn("original_basis", source)
        for forbidden in ("export_scene", "save_as_mainfile", "vertex_groups.new", "edit_bones", "normals_split_custom_set"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(len(MODULE.POSES), 8)
        self.assertEqual(MODULE.TOLERANCE_M, 3e-6)

    def test_output_scope_rejects_original_and_other_agent(self):
        for path in (MODULE.BRANCH / "cleanup_v01", MODULE.BRANCH.parent / "stone_slinger_v01/rig_transfer_01"):
            with self.assertRaises(ValueError):
                MODULE.fresh_output(path)


if __name__ == "__main__":
    unittest.main()
