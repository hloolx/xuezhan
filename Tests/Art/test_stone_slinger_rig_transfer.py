import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "Tools/Blender"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("slinger_transfer", TOOLS / "prepare_stone_slinger_rig_transfer.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TransferTests(unittest.TestCase):
    def test_no_weight_averaging(self):
        resolved, conflict = MODULE.resolve_weights({0: {2, 3}}, {2: {"hand": .8, "arm": .2}, 3: {"hand": .7, "arm": .3}})
        self.assertEqual(resolved, {})
        self.assertEqual(len(conflict), 1)
        self.assertAlmostEqual(conflict[0]["maximum_weight_difference"], .1)

    def test_duplicate_identical_weight_rows_are_not_averaged(self):
        weights = {"hand": .8, "arm": .2}
        resolved, conflict = MODULE.resolve_weights({0: {2, 3}}, {2: weights, 3: dict(weights)})
        self.assertEqual(resolved, {0: weights})
        self.assertEqual(conflict, [])

    def test_one_cloud_vertex_can_supply_two_kept_source_vertices(self):
        source = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [-1, 0, 0]])
        cloud = source[:3].tolist() + [source[4].tolist()]
        mapping, triangles, error = MODULE.pair_triangles(source, np.array([[0, 1, 2], [3, 2, 4]]), np.array(cloud), [[0, 1, 2], [0, 2, 3]])
        self.assertEqual(mapping[0], {0})
        self.assertEqual(mapping[3], {0})
        self.assertEqual(len(mapping), 5)
        self.assertEqual(error, 0)

    def test_reversed_winding_rejected(self):
        points = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        with self.assertRaisesRegex(ValueError, "winding"):
            MODULE.pair_triangles(points, np.array([[0, 1, 2]]), points, [[0, 2, 1]])


if __name__ == "__main__":
    unittest.main()
