import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/Blender"))
SPEC = importlib.util.spec_from_file_location("slinger_normal_repair", ROOT / "Tools/Blender/repair_stone_slinger_normals.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalNormalRepairTests(unittest.TestCase):
    def test_exact_uv_intersection_detects_overlap(self):
        first = np.array([(0, 0), (1, 0), (0, 1)], dtype=float)
        self.assertAlmostEqual(.5, MODULE.intersection_area(first, first))
        self.assertAlmostEqual(.5, MODULE.intersection_area(first, first[::-1]))

    def test_adjacent_uv_triangles_touch_without_area_overlap(self):
        first = np.array([(0, 0), (1, 0), (0, 1)], dtype=float)
        second = np.array([(1, 0), (1, 1), (0, 1)], dtype=float)
        self.assertAlmostEqual(0, MODULE.intersection_area(first, second))

    def test_barycentric_influence_hits_exact_vertex_and_fades_at_opposite_edge(self):
        triangle = np.array([(0, 0), (1, 0), (0, 1)], dtype=float)
        weights = MODULE.barycentric(np.array([(0, 0), (.5, .5)]), triangle)
        self.assertTrue(np.allclose(weights[:, 0], (1, 0)))

    def test_foreign_atlas_triangles_block_unsafe_patch(self):
        first = np.array([(.1, .1), (.6, .1), (.1, .6)])
        result = MODULE.footprint(np.array([first, first]), np.array([(0, 1, 2), (3, 4, 5)]), [0], size=32)
        self.assertFalse(result["passed"])
        self.assertTrue(result["exact_UV_triangle_overlaps"])
        self.assertTrue(result["base_texel_foreign_collisions"])

    def test_padding_cannot_modify_foreign_neighbor_texels(self):
        first = np.array([(.1, .1), (.6, .1), (.1, .6)])
        second = np.array([(.6, .1), (.6, .6), (.1, .6)])
        result = MODULE.footprint(np.array([first, second]), np.array([(0, 1, 2), (3, 4, 5)]), [0], size=32)
        self.assertTrue(result["passed"])
        self.assertGreater(result["foreign_triangle_padding_texels_excluded"], 0)
        self.assertTrue(all(0 <= pixel[2] <= 1 for pixel in result["safe_texels_gltf_top_left"]))

    def test_actual_frozen_region_is_four_vertices_nine_faces_and_isolated(self):
        arrays = MODULE.texture.read_glb(MODULE.texture.RETURNED)[2]
        region = MODULE.footprint(arrays["TEXCOORD_0"][arrays["indices"]].astype(float), arrays["indices"], [878, 879, 8242, 8243])
        self.assertTrue(region["passed"])
        self.assertEqual(9, len(region["target_faces"]))
        self.assertEqual(703, region["base_texel_count"])
        self.assertEqual(1146, region["safe_texel_count"])
        self.assertEqual(361, region["foreign_triangle_padding_texels_excluded"])


if __name__ == "__main__":
    unittest.main()
