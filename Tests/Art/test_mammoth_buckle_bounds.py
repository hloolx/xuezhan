import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mammoth_bounds_test", ROOT / "Tools/Blender/analyze_mammoth_buckle_constraints.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MammothBoundsTests(unittest.TestCase):
    def test_shortest_permitted_path_gives_strongest_endpoint_bound(self):
        distances, previous = MODULE.shortest_upper_bound_paths(4, [(0, 1), (1, 2), (0, 2), (2, 3)], [.04, .04, .12, .02], 0)
        self.assertAlmostEqual(distances[2], .08)
        self.assertEqual(previous[2], 1)
        self.assertAlmostEqual(distances[3], .10)

    def test_disconnected_boundary_does_not_make_false_proof(self):
        distances, _ = MODULE.shortest_upper_bound_paths(3, [(0, 1)], [.04], 0)
        self.assertNotIn(2, distances)


if __name__ == "__main__":
    unittest.main()
