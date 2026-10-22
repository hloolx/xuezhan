import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("slinger_texture", ROOT / "Tools/Blender/review_stone_slinger_texture.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextureCorrespondenceTests(unittest.TestCase):
    def source(self):
        return {"POSITION": np.array([(0, 0, 0), (1, 0, 0), (0, 1.425, 0), (0, 0, 0), (0, 1.425, 0), (-1, 0, 0)], dtype=float),
                "NORMAL": np.array([(0, 0, 1)] * 6, dtype=float),
                "TEXCOORD_0": np.array([(0, 0), (1, 0), (0, 1), (0, 0), (0, 1), (1, 1)], dtype=float),
                "indices": np.array([(0, 1, 2), (3, 4, 5)])}

    def returned(self, source):
        result = {name: values.copy() for name, values in source.items()}
        result["POSITION"] = result["POSITION"] / 1.425 - (0, .5, 0)
        return result

    def test_reordered_vertices_and_triangles_restore_physical_frame(self):
        source = self.source()
        returned = self.returned(source)
        permutation = np.array([5, 2, 4, 0, 3, 1])
        inverse = np.argsort(permutation)
        for name in ("POSITION", "NORMAL", "TEXCOORD_0"):
            returned[name] = returned[name][permutation]
        returned["indices"] = inverse[returned["indices"]][::-1]
        result = MODULE.compare(source, returned)
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["restore_uniform_scale"], 1.425)

    def test_normal_change_does_not_invalidate_preserved_geometry(self):
        source = self.source()
        returned = self.returned(source)
        returned["NORMAL"][0] = (0, 1, 0)
        result = MODULE.compare(source, returned)
        self.assertFalse(result["passed"])
        self.assertTrue(result["geometry_and_index_connectivity_passed"])
        self.assertEqual(result["normal_change_diagnostic"]["affected_triangle_corners"], 1)

    def test_cloud_welding_is_rejected_even_with_identical_surface(self):
        source = self.source()
        returned = self.returned(source)
        returned["indices"][1, 0] = 0
        returned["indices"][1, 1] = 2
        result = MODULE.compare(source, returned)
        self.assertFalse(result["index_connectivity_bijection_preserved"])
        self.assertFalse(result["geometry_and_index_connectivity_passed"])

    def test_geometry_change_is_rejected(self):
        source = self.source()
        returned = self.returned(source)
        returned["POSITION"][0, 2] += .001
        with self.assertRaises(ValueError):
            MODULE.compare(source, returned)

    def test_reverse_winding_is_rejected(self):
        source = self.source()
        returned = self.returned(source)
        returned["indices"][0] = returned["indices"][0][::-1]
        result = MODULE.compare(source, returned)
        self.assertEqual(result["winding_reversals"], 1)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
