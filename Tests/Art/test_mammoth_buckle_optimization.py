import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_optimization_test", ROOT / "Tools/Blender/optimize_mammoth_buckle_weights.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    return {"edge_arguments": {"current_edges": np.array([[[1., 0, 0]]]), "first_delta": np.zeros((1, 1, 3)),
                               "second_delta": np.array([[[.2, .1, 0]]]), "first_indices": np.array([0]), "second_indices": np.array([1]),
                               "lengths": np.ones(1)}, "baseline_strain": np.zeros((1, 1))}


class MammothOptimizationTests(unittest.TestCase):
    def test_analytic_gradient_matches_finite_difference(self):
        data = fixture()
        alpha = np.array([0., .6])
        _, gradient, _ = MODULE.objective_gradient(alpha, data)
        epsilon = 1e-6
        plus = MODULE.objective_gradient(alpha + [0, epsilon], data)[0]
        minus = MODULE.objective_gradient(alpha - [0, epsilon], data)[0]
        self.assertAlmostEqual(gradient[1], (plus - minus) / (2 * epsilon), places=8)

    def test_bounded_solver_respects_fixed_contact_and_outside(self):
        alpha, loss, _, count = MODULE.optimize(np.array([.7, .9]), fixture(), {0: 1.}, iterations=40)
        self.assertEqual(alpha[0], 1.)
        self.assertTrue(np.all((alpha >= 0) & (alpha <= 1)))
        self.assertLess(count, 41)
        self.assertLess(loss, 1e-8)

    def test_infeasible_fixed_trial_is_not_labeled_success(self):
        _, loss, _, _ = MODULE.optimize(np.array([0., 1.]), fixture(), {0: 0., 1: 1.}, iterations=10)
        self.assertGreater(loss, .01)

    def test_actual_geometry_and_tail_cannot_be_written(self):
        source = inspect.getsource(MODULE.analyze)
        for forbidden in ("import bpy", "export_scene", "MODEL.write", "candidate.write_bytes", "encode("):
            self.assertNotIn(forbidden, source)
        self.assertIn('"tail_changes": 0', source)
        self.assertIn('"edges_worse_than_original_by_tolerance"] == 0', source)
        self.assertEqual(MODULE.MAX_ITERATIONS, 160)


if __name__ == "__main__":
    unittest.main()
