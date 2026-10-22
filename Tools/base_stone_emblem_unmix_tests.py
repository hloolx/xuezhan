from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import base_stone_emblem_unmix as study


class SourceContributionTests(unittest.TestCase):
    def test_known_linear_mixture_recovers_opacity(self):
        background = np.asarray([.04, .08, .16])
        ink = np.asarray([.4, .42, .45])
        opacity = .37
        source = (1 - opacity) * background + opacity * ink
        estimated, contribution, residual = study.unmix(source, background, ink)
        self.assertAlmostEqual(float(estimated), opacity, places=12)
        np.testing.assert_allclose(contribution, opacity * ink, atol=1e-12)
        np.testing.assert_allclose(residual, 0, atol=1e-12)

    def test_pure_background_no_foreground(self):
        background = np.asarray([.04, .08, .16])
        alpha, contribution, residual = study.unmix(background, background, np.asarray([.4, .42, .45]))
        self.assertAlmostEqual(float(alpha), 0)
        np.testing.assert_allclose(contribution, 0)

    def test_pure_source_ink_not_recolored(self):
        ink = np.asarray([.4, .42, .45])
        alpha, contribution, residual = study.unmix(ink, np.asarray([.04, .08, .16]), ink)
        self.assertAlmostEqual(float(alpha), 1)
        for color in study.prior.shared.TEAM_COLORS.values():
            np.testing.assert_allclose(study.tint_background(ink, contribution, color), ink)

    def test_nonnegative_contribution_when_background_estimate_is_too_bright(self):
        source = np.asarray([.01, .05, .1])
        alpha, contribution, residual = study.unmix(source, np.asarray([.08, .09, .2]), np.asarray([.4, .42, .45]))
        self.assertGreaterEqual(float(contribution.min()), -1e-12)
        self.assertTrue(np.all(contribution <= source + 1e-12))

    def test_srgb_roundtrip(self):
        source = np.linspace(0, 1, 1000)
        np.testing.assert_allclose(study.linear_to_srgb(study.srgb_to_linear(source)), source, atol=1e-12)

    def test_new_probe_gate_preserves_contribution_not_mixed_rgb(self):
        report = study.prior.read(study.FOLDER / "candidate_report.json")
        for probe in report["actual_game_uv_revised_probes"]:
            original = np.asarray(probe["original_linear_rgb"])
            ink = np.asarray(probe["preserved_ink_contribution_linear_rgb"])
            substrate = np.asarray(probe["recolorable_substrate_contribution_linear_rgb"])
            np.testing.assert_allclose(ink + substrate, original, atol=1e-12)
            self.assertTrue(probe["old_full_protection_gate_revised"])
            self.assertLess(probe["source_derived_alpha_bilinear"], 1)
            self.assertTrue(np.all(ink >= 0))
            self.assertTrue(np.all(substrate >= 0))

    def test_actual_corrected_preview_guards_outside_exactly(self):
        folder = study.FOLDER / "strict_guard_previews"
        data = np.load(folder / "decomposition_fields.npz")
        guard = np.asarray(Image.fromarray(data["guard"].astype(np.uint8)).resize((data["guard"].shape[1] * 6, data["guard"].shape[0] * 6), Image.Resampling.NEAREST)).astype(bool)
        original = np.asarray(Image.open(folder / "original_strict_guard_x6.png"))
        for name in ("blue", "red"):
            image = np.asarray(Image.open(folder / (name + "_strict_guard_x6.png")))
            np.testing.assert_array_equal(image[~guard], original[~guard])

    def test_no_scope_expansion_in_frozen_fields(self):
        data = np.load(study.FOLDER / "strict_guard_previews/decomposition_fields.npz")
        self.assertEqual(int(data["semantic_support"].sum()), 1217)
        self.assertFalse((data["semantic_support"] & ~data["guard"]).any())
        self.assertTrue(np.all(data["protected_ink_contribution_linear"][~data["semantic_support"]] == 0))

    def test_all43packages_and_original_sources_unchanged(self):
        context = study.render.check_team_report(study.prior.FOLDER / "ue_fresh_01.json")
        records = context["frozen_packages"] + context["source_evidence"] + context["result"]["files"]
        study.prior.check_records(records)
        self.assertEqual(len({item["path"] for item in records if Path(item["path"]).suffix == ".uasset"}), 43)

    def test_only_one_decomposition_candidate_not_ue_approval(self):
        report = study.prior.read(study.FOLDER / "candidate_report.json")
        self.assertEqual(report["candidate_budget"], {"maximum": 2, "used": 1})
        self.assertFalse(report["actual_ue_visual_approved"])
        self.assertFalse(report["runtime_approved"])
        self.assertFalse(report["content_modified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
