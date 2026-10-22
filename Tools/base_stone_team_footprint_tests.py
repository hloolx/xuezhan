import unittest
import copy

import numpy as np

import base_stone_team_footprint as footprint
import base_stone_team_footprint_ue as adapter


class NearestSamplerFootprintTests(unittest.TestCase):
    def test_small_triangle_without_any_texel_center_still_covered(self):
        region, covered = footprint.triangle_texel_support(((.1, .1), (.12, .1), (.1, .12)), 4, 4)
        self.assertTrue(covered[0, 0])

    def test_winding_independent(self):
        triangle = ((.12, .25), (.81, .43), (.27, .87))
        first = footprint.triangle_texel_support(triangle, 12, 12)
        second = footprint.triangle_texel_support(triangle[::-1], 12, 12)
        self.assertEqual(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])

    def test_outside_uv_no_wrap(self):
        self.assertIsNone(footprint.triangle_texel_support(((2, 2), (3, 2), (2, 3)), 8, 8))

    def test_negative_uv_no_wrap(self):
        self.assertIsNone(footprint.triangle_texel_support(((-2, -2), (-3, -2), (-2, -3)), 8, 8))

    def test_triangle_bbox_corner_without_intersection_is_not_selected(self):
        region, covered = footprint.triangle_texel_support(((.1, .1), (.8, .1), (.1, .8)), 10, 10)
        self.assertFalse(covered[-1, -1])

    def test_degenerate_protected_point_is_not_ignored(self):
        region, covered = footprint.triangle_texel_support(((.29, .29),) * 3, 8, 8)
        self.assertEqual(int(covered.sum()), 1)

    def test_invalid_uv_rejected(self):
        with self.assertRaises(ValueError):
            footprint.triangle_texel_support(((float("nan"), 0), (0, 1), (1, 0)), 8, 8)

    def test_protected_neighborhood_never_recolored(self):
        selected, protected, blue = (np.ones((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool), np.ones((8, 8), dtype=bool))
        protected[4, 4] = True
        mask = footprint.derive_mask(selected, protected, blue)
        self.assertFalse(mask[3:6, 3:6].any())
        self.assertFalse((footprint.dilate(mask) & protected).any())

    def test_pale_pixels_unchanged(self):
        selected, protected, blue = (np.ones((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool), np.ones((8, 8), dtype=bool))
        blue[3:5, 3:5] = False
        mask = footprint.derive_mask(selected, protected, blue)
        self.assertFalse(mask[3:5, 3:5].any())

    def test_not_simple_dilation_beyond_triangle_support(self):
        selected, protected, blue = (np.zeros((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool), np.ones((8, 8), dtype=bool))
        selected[4, 4] = True
        mask = footprint.derive_mask(selected, protected, blue)
        self.assertEqual(int(mask.sum()), 1)

    def test_frozen_old30_and_new_footprint_inputs(self):
        context = adapter.source_inputs()
        self.assertEqual(context["additional_previous_derived_packages_frozen"], 4)
        self.assertEqual(context["settings"]["semantic_mask"]["mask_pixels"], 74045)
        self.assertNotEqual(context["destination"], "/Game/ArtPilot/BaseStoneTeam/h06e70eec6fbb019f")

    def test_new_footprint_does_not_relax_white_or_noncloth_gates(self):
        report = adapter.read(adapter.TEAM / "main_cloth_candidate_v03_nearest_footprint/candidate_mask_report.json")
        for key in ("pale_or_nonblue_pixels_recolored", "protected_sampler_overlap_pixels", "one_pixel_filter_footprint_protected_overlap_pixels"):
            changed = copy.deepcopy(report)
            changed[key] = 1
            with self.assertRaises(ValueError):
                adapter.validate_footprint(changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
