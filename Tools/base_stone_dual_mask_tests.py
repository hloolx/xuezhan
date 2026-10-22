import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_dual_mask_candidate as candidate
import base_stone_dual_mask_ue as adapter
import base_stone_dual_mask_render as render
from base_stone_side_emblem_diagnostic import continuous_mask


class DualMaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = adapter.read(candidate.FOLDER / "candidate_report.json")
        cls.guard = np.asarray(Image.open(cls.report["guard_mask"]["path"]))
        cls.protection = np.asarray(Image.open(cls.report["protection_mask"]["path"]))
        cls.binary = np.asarray(Image.open(adapter.previous.FOLDER / "candidate_v02/T_Base_Stone_MainClothMask_EMBLEM_CANDIDATE.png"))

    def test_frozen_source38_and_new_destination(self):
        context = adapter.source_inputs()
        self.assertEqual(context["existing_package_count"], 38)
        self.assertNotEqual(context["destination"], adapter.previous.source_inputs()["destination"])
        self.assertEqual(context["mask_source"]["sha256"], adapter.GUARD_SHA)
        self.assertEqual(context["protection_source"]["sha256"], adapter.PROTECTION_SHA)

    def test_protection_exact1217(self):
        np.testing.assert_array_equal(self.protection > 0, (self.guard > 0) & (self.binary == 0))
        self.assertEqual(int((self.protection > 0).sum()), 1217)

    def test_core613_entire_cell_five_fractional_samples(self):
        unused, excluded, occupancy = continuous_mask(self.guard, self.binary)
        core = excluded & (occupancy == 16)
        self.assertEqual(int(core.sum()), 613)
        for row, column in zip(*np.nonzero(core)):
            for horizontal, vertical in ((0, 0), (0, .999999), (.999999, 0), (.999999, .999999), (.5, .5)):
                sample = candidate.sample_dual(self.guard, self.protection, [(column + horizontal) / 2048, (row + vertical) / 2048])
                self.assertAlmostEqual(sample["final_tint_weight"], 0, places=12)

    def test_actual_game_probe_four_weights_all_protected(self):
        for probe in self.report["actual_game_uv_probes"]:
            sample = candidate.sample_dual(self.guard, self.protection, probe["source_uv"])
            self.assertAlmostEqual(sample["final_tint_weight"], 0, places=12)
            self.assertTrue(all(item["value"] == 1 for item in sample["four_samples"]))

    def test_front45_unchanged_at_cell_corners(self):
        self.assertEqual(len(self.report["front45_entire_cells_unchanged"]), 45)
        for probe in self.report["front45_entire_cells_unchanged"]:
            column, row = probe["atlas_pixel"]
            for horizontal, vertical in ((0, 0), (.999999, .999999), (.5, .5)):
                sample = candidate.sample_dual(self.guard, self.protection, [(column + horizontal) / 2048, (row + vertical) / 2048])
                self.assertEqual(sample["protection_bilinear"], 0)
                self.assertEqual(sample["final_tint_weight"], sample["guard"])

    def test_bilinear_continuous_boundary(self):
        image = np.array([[0, 255], [0, 255]], dtype=np.uint8)
        values = [candidate.bilinear_sample(image, [position, .5])[0] for position in (.25, .375, .5, .625, .75)]
        np.testing.assert_allclose(values, [0, .25, .5, .75, 1])

    def test_clamp_no_wraparound(self):
        image = np.array([[0, 255], [255, 0]], dtype=np.uint8)
        self.assertEqual(candidate.bilinear_sample(image, [0, 0])[0], 0)
        self.assertEqual(candidate.bilinear_sample(image, [1, 0])[0], 1)

    def test_nearest_guard_zero_always_wins(self):
        guard = np.zeros((3, 3), dtype=np.uint8)
        protection = np.arange(9, dtype=np.uint8).reshape((3, 3)) * 30
        for horizontal in np.linspace(0, 1, 21):
            for vertical in np.linspace(0, 1, 21):
                self.assertEqual(candidate.sample_dual(guard, protection, [horizontal, vertical])["final_tint_weight"], 0)

    def test_final_weight_cannot_exceed_original_guard(self):
        generator = np.random.default_rng(9382)
        for uv in generator.random((500, 2)):
            sample = candidate.sample_dual(self.guard, self.protection, uv)
            self.assertGreaterEqual(sample["final_tint_weight"], 0)
            self.assertLessEqual(sample["final_tint_weight"], sample["guard"])

    def test_semantic_other_triangle_support_zero(self):
        self.assertEqual(self.report["effective_possible_support_on_other_source_triangles"], 0)
        self.assertEqual(self.report["possible_fringe_cells_outside_binary1217"], 683)

    def test_graph_contract_replaces_not_bypasses_guard(self):
        original = list(adapter.shared.LINKS)
        with adapter.graph_contract():
            self.assertNotIn(adapter.ORIGINAL_LINK, adapter.shared.LINKS)
            self.assertTrue(all(link in adapter.shared.LINKS for link in adapter.EXTRA_LINKS))
            incoming = [link for link in adapter.shared.LINKS if link[2:] == ("masked_strength", "A")]
            self.assertEqual(incoming, [("protected_mask", "", "masked_strength", "A")])
        self.assertEqual(adapter.shared.LINKS, original)

    def test_graph_contract_restores_on_error(self):
        classes, links = adapter.base.WRAPPER_CLASSES, adapter.shared.LINKS
        with self.assertRaises(RuntimeError):
            with adapter.graph_contract():
                raise RuntimeError("test")
        self.assertIs(adapter.base.WRAPPER_CLASSES, classes)
        self.assertIs(adapter.shared.LINKS, links)

    def test_sampler_settings_differ_only_in_filter(self):
        unreal = SimpleNamespace(TextureCompressionSettings=SimpleNamespace(TC_GRAYSCALE="gray"),
                                 TextureMipGenSettings=SimpleNamespace(TMGS_NO_MIPMAPS="none"),
                                 TextureFilter=SimpleNamespace(TF_NEAREST="nearest", TF_BILINEAR="bilinear"),
                                 TextureAddress=SimpleNamespace(TA_CLAMP="clamp"))
        guard, protection = adapter.shared.mask_settings(unreal), adapter.protection_settings(unreal)
        self.assertEqual([key for key in guard if guard[key] != protection[key]], ["filter"])

    def test_all12_original_matched_cameras(self):
        self.assertEqual(len(render.SHOTS), 12)
        self.assertEqual({item[2] for item in render.SHOTS}, {"wide", "flag", "side_flag"})
        for crop in ("wide", "flag", "side_flag"):
            self.assertEqual({item[1] for item in render.SHOTS if item[2] == crop}, {"original", "disabled", "blue", "red"})

    def test_missing_fifth_texture_rejected_by_residency_gate(self):
        records = {str(index): {"maximum_allowed_size": [2048, 2048], "actual_resident_size": [2048, 2048]} for index in range(4)}
        self.assertFalse(render.renderer.textures_resident(records, set(map(str, range(5)))))
        records["4"] = {"maximum_allowed_size": [2048, 2048], "actual_resident_size": [2048, 2048]}
        self.assertTrue(render.renderer.textures_resident(records, set(map(str, range(5)))))
        records["4"]["actual_resident_size"] = [1024, 1024]
        self.assertFalse(render.renderer.textures_resident(records, set(map(str, range(5)))))

    def test_initial_dump_adds_fifth_before_readiness(self):
        instance = render.DualMaskReview.__new__(render.DualMaskReview)
        instance.required_paths = {"one", "two", "three", "four"}
        instance.context = {"result": {"protection": "five"}}
        with patch.object(render.renderer.BaseReview, "request_dump", return_value="dump"):
            self.assertEqual(instance.request_dump("initial"), "dump")
            self.assertEqual(instance.required_paths, {"one", "two", "three", "four", "five"})
            self.assertEqual(instance.request_dump("side_flag"), "dump")

    def test_wrong_texture_count_blocks_dump(self):
        instance = render.DualMaskReview.__new__(render.DualMaskReview)
        instance.required_paths = {"one"}
        with self.assertRaises(ValueError):
            instance.request_dump("side_flag")

    def test_candidate_not_runtime_approval(self):
        self.assertFalse(self.report["runtime_approved"])
        self.assertFalse(self.report["production_approved"])
        self.assertFalse(self.report["content_modified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
