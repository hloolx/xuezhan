from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_emblem_unmix_candidate02 as candidate
from base_stone_dual_mask_candidate import bilinear_sample


class FinalLocalRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = candidate.previous.prior.read(candidate.FOLDER / "candidate_report.json")
        cls.new = dict(np.load(cls.report["decomposition_fields"]["path"]))
        cls.old = dict(np.load(cls.report["candidate01_fields"]["path"]))

    def test_candidate_and_tool_records_frozen(self):
        for key in ("decomposition_fields", "candidate01_fields", "candidate01_report", "tool"):
            candidate.previous.prior.shared.check_record(self.report[key])
        for record in self.report["previews"].values():
            candidate.previous.prior.shared.check_record(record)

    def test_exact23_added_no_other_semantic_changes(self):
        added = self.new["semantic_support"] & ~self.old["semantic_support"]
        self.assertEqual(int(added.sum()), 23)
        self.assertFalse((self.old["semantic_support"] & ~self.new["semantic_support"]).any())
        np.testing.assert_array_equal(added, self.new["added_shortbar_support"])
        self.assertEqual(int(self.new["semantic_support"].sum()), 1240)

    def test_manual_source_rowspans_match(self):
        left, top, right, bottom = self.new["atlas_rectangle"]
        expected = np.zeros_like(self.new["added_shortbar_support"])
        for row, (first, last) in candidate.ROW_SPANS.items():
            expected[row - top, first - left:last - left + 1] = True
        np.testing.assert_array_equal(expected, self.new["added_shortbar_support"])

    def test_old1217_contributions_byte_identical(self):
        selection = self.old["semantic_support"]
        np.testing.assert_array_equal(self.new["protected_ink_contribution_linear"][selection], self.old["protected_ink_contribution_linear"][selection])
        np.testing.assert_array_equal(self.new["opacity"][selection], self.old["opacity"][selection])

    def test_source_background_and_guard_byte_identical(self):
        for key in ("source_linear", "local_background_linear", "guard", "atlas_rectangle"):
            np.testing.assert_array_equal(self.new[key], self.old[key])

    def test_two_guardzero_texels_not_guard_expansion(self):
        added_guard_zero = self.new["added_shortbar_support"] & ~self.new["guard"]
        left, top, right, bottom = self.new["atlas_rectangle"]
        actual = {(int(column + left), int(row + top)) for row, column in zip(*np.nonzero(added_guard_zero))}
        self.assertEqual(actual, {(222, 190), (222, 191)})
        self.assertEqual(int((self.new["added_shortbar_support"] & self.new["guard"]).sum()), 21)

    def test_nonnegative_contribution_no_source_overshoot(self):
        ink = self.new["protected_ink_contribution_linear"]
        self.assertGreaterEqual(float(ink.min()), -1e-12)
        self.assertTrue(np.all(ink <= self.new["source_linear"] + 1e-12))
        self.assertTrue(np.all(ink[~self.new["semantic_support"]] == 0))

    def test_changed_contribution_only_in23(self):
        changed = np.any(self.new["protected_ink_contribution_linear"] != self.old["protected_ink_contribution_linear"], axis=2)
        np.testing.assert_array_equal(changed, self.new["added_shortbar_support"])

    def test_two_actualUV_ink_contributions_unchanged(self):
        old_report = candidate.previous.prior.read(candidate.previous.FOLDER / "candidate_report.json")
        left, top, right, bottom = self.new["atlas_rectangle"]
        for probe in old_report["actual_game_uv_revised_probes"]:
            local_uv = [(probe["uv"][0] * 2048 - left) / (right - left), (probe["uv"][1] * 2048 - top) / (bottom - top)]
            values = [bilinear_sample(self.new["protected_ink_contribution_linear"][..., channel] * 255, local_uv)[0] for channel in range(3)]
            np.testing.assert_allclose(values, probe["preserved_ink_contribution_linear_rgb"], atol=1e-12)

    def test_new_support_other_triangle_and_noncloth_zero(self):
        for key in ("added_direct_other_triangle_overlap", "added_unconditionally_dilated1pixel_other_triangle_overlap",
                    "added_bilinear_guarded_other_triangle_overlap", "all_bilinear_guarded_other_triangle_overlap", "new_noncloth_or_held_dye_support"):
            self.assertEqual(self.report[key], 0)
        self.assertEqual(set(self.report["added_source_triangle_ownership"]), {"2286", "2346", "2377"})

    def test_corrected_actual_previews_never_change_guardzero(self):
        guard = self.new["guard"]
        upscaled = np.asarray(Image.fromarray(guard.astype(np.uint8)).resize((guard.shape[1] * 6, guard.shape[0] * 6), Image.Resampling.NEAREST)).astype(bool)
        original = np.asarray(Image.open(self.report["previews"]["original"]["path"]))
        for name in ("blue", "red"):
            image = np.asarray(Image.open(self.report["previews"][name]["path"]))
            np.testing.assert_array_equal(image[~upscaled], original[~upscaled])

    def test_original_preview_unchanged(self):
        self.assertEqual(self.report["previews"]["original"]["sha256"], "823620b40bd0ce6501bcfa6192521496705a227c9715f84dd1e024f3b8045cb2")

    def test_final_candidate_budget_and_gate_revision(self):
        self.assertEqual(self.report["decomposition_candidates_used"], 2)
        self.assertEqual(self.report["decomposition_candidates_maximum"], 2)
        self.assertIn("Root explicitly withdrew", self.report["root_gate_revision"])
        self.assertFalse(self.report["actual_ue_visual_approved"])
        self.assertFalse(self.report["runtime_approved"])

    def test_historical_config_snapshot_and43packages_frozen(self):
        self.assertEqual(self.report["runtime_config_readonly_snapshot"]["sha256"], "4d40918ab359d0faabaae168d6e3682e24880cb199276f223163ae526cee839c")
        context = candidate.previous.render.check_team_report(candidate.previous.prior.FOLDER / "ue_fresh_01.json")
        records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
        candidate.previous.prior.check_records(records)
        self.assertEqual(len({record["path"] for record in records if Path(record["path"]).suffix == ".uasset"}), 43)


if __name__ == "__main__":
    unittest.main(verbosity=2)
