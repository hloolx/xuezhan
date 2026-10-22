from __future__ import annotations

import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_side_emblem_render as review
import base_stone_side_emblem_ue as adapter


class SideEmblemUEContracts(unittest.TestCase):
    def setUp(self):
        self.report = adapter.read(adapter.FOLDER / "candidate_v02/candidate_report.json")

    def test_exact_candidate_contract(self):
        result = adapter.validate_candidate(self.report)
        self.assertEqual(result["removed_pixels"], 1217)
        self.assertEqual(result["new_mask_pixels"], 72828)

    def test_added_pixels_rejected(self):
        self.report["added_pixels"] = 1
        with self.assertRaises(ValueError):
            adapter.validate_candidate(self.report)

    def test_other_triangle_changes_rejected(self):
        self.report["changes_on_other_source_support"] = 1
        with self.assertRaises(ValueError):
            adapter.validate_candidate(self.report)

    def test_held_or_semantic_expansion_rejected(self):
        for key, value in (("held_faces", 0), ("original_selected_faces", 720), ("global_pigment_predicate_modified", True)):
            changed = copy.deepcopy(self.report)
            changed[key] = value
            with self.assertRaises(ValueError):
                adapter.validate_candidate(changed)

    def test_front_probe_regression_rejected(self):
        self.report["front45_probes_unchanged"][0]["unchanged"] = False
        with self.assertRaises(ValueError):
            adapter.validate_candidate(self.report)

    def test_frozen34_and_unique_branch(self):
        context = adapter.source_inputs()
        self.assertEqual(context["existing_package_count"], 34)
        self.assertEqual(context["additional_previous_derived_packages_frozen"], 8)
        self.assertEqual(context["mask_source"]["sha256"], adapter.MASK_SHA)
        self.assertNotIn(context["destination"], ["/Game/ArtPilot/BaseStoneTeam/" + branch for branch in ("hfed73795f18c8098", "h06e70eec6fbb019f", "h209a2a8ebd7b9dca")])

    def test_exact12_matched_controls(self):
        self.assertEqual(len(review.SHOTS), 12)
        for camera in ("wide", "flag", "side_flag"):
            self.assertEqual({mode for label, mode, crop in review.SHOTS if crop == camera}, {"original", "disabled", "blue", "red"})

    def test_original_front_camera_unchanged(self):
        self.assertEqual(review.CAMERAS["flag"], {"target": [206, -198, 45], "offset": [300, -80, 50], "fov": 24})

    def test_side_camera_matches_game_visible_direction(self):
        side = review.CAMERAS["side_flag"]
        self.assertEqual(side["target"], [-147, 229, 43])
        self.assertEqual(side["offset"][0], 0)
        self.assertGreater(side["offset"][1], 0)
        self.assertAlmostEqual(math.degrees(math.atan2(side["offset"][2], side["offset"][1])), 20, places=6)

    def test_twelve_completion_status(self):
        instance = object.__new__(review.SideEmblemReview)
        instance.report = {"images": [{"label": label} for label, mode, crop in review.SHOTS]}
        with patch.object(review.renderer.BaseReview, "finish") as finish:
            instance.finish("actual8images_captured_pending_visual_and_pixel_control_review")
            finish.assert_called_once_with("actual12images_captured_pending_visual_and_pixel_control_review")

    def test_incomplete_completion_fails(self):
        instance = object.__new__(review.SideEmblemReview)
        instance.report = {"images": [{"label": label} for label, mode, crop in review.SHOTS[:-1]]}
        with patch.object(review.renderer.BaseReview, "finish") as finish:
            instance.finish("actual8images_captured_pending_visual_and_pixel_control_review")
            finish.assert_called_once_with("failed")

    def test_frozen_implementation_hashes(self):
        self.assertEqual(adapter.sha(review.renderer.__file__), review.RENDERER_SHA)
        self.assertEqual(adapter.sha(adapter.previous.__file__), adapter.PREVIOUS_TOOL_SHA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
