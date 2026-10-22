"""Offline UV raster guard tests; no Blender, network or UE process."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
from PIL import Image


module_spec = importlib.util.spec_from_file_location("base_team_mask", Path(__file__).parent / "Blender/prepare_base_stone_team_mask.py")
candidate = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(candidate)


class BaseTeamMaskTests(unittest.TestCase):
    def test_frozen_sources_and_fresh_proof(self):
        candidate.check_sources()

    def test_top_left_uv_raster(self):
        region, inside = candidate.raster_triangle(((0, 0), (1, 0), (0, 1)), 4, 4, np)
        self.assertEqual(region, (slice(0, 4), slice(0, 4)))
        self.assertTrue(inside[0, 0])
        self.assertFalse(inside[3, 3])

    def test_degenerate_uv_is_not_filled(self):
        self.assertIsNone(candidate.raster_triangle(((0, 0), (0, 0), (0, 0)), 4, 4, np))

    def test_outside_uv_does_not_wrap_into_cloth(self):
        self.assertIsNone(candidate.raster_triangle(((2, 2), (3, 2), (2, 3)), 4, 4, np))

    def test_reversed_winding_same_pixels(self):
        triangle = ((0, 0), (1, 0), (0, 1))
        first = candidate.raster_triangle(triangle, 8, 8, np)
        second = candidate.raster_triangle(tuple(reversed(triangle)), 8, 8, np)
        np.testing.assert_array_equal(first[1], second[1])

    def test_diagnostic_does_not_claim_approval(self):
        document = candidate.read_json(candidate.OWNED / "region_diagnostic_v01/region_analysis.json")
        self.assertFalse(document["delivery_mask_created"])
        self.assertTrue(document["classification"]["color_is_proposal_only"])
        self.assertTrue(all(not cluster["semantic_approval"] for cluster in document["clusters"]))

    def test_safe_gutter_never_expands_original_mask(self):
        raw = np.asarray(Image.open(candidate.OWNED / "main_cloth_candidate_v01/T_Base_Stone_MainClothMask_CANDIDATE.png")) > 0
        safe = np.asarray(Image.open(candidate.OWNED / "main_cloth_candidate_v02_safe1/T_Base_Stone_MainClothMask_CANDIDATE.png")) > 0
        self.assertFalse((safe & ~raw).any())
        self.assertEqual(int((raw & ~safe).sum()), 608)

    def test_safe_gutter_blocks_filter_footprint_without_blur(self):
        report = candidate.read_json(candidate.OWNED / "main_cloth_candidate_v02_safe1/candidate_mask_report.json")
        self.assertEqual(report["protected_uv_overlap_pixels"], 0)
        self.assertEqual(report["one_pixel_filter_footprint_protected_overlap_pixels"], 0)
        self.assertFalse(report["blur_applied"])
        self.assertFalse(report["mask_expanded"])
        self.assertFalse(report["all_cloth_coverage_approved"])


if __name__ == "__main__":
    unittest.main()
